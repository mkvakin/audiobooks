"""
Book to Audiobook Pipeline - Main Application.

This module provides the main pipeline that orchestrates:
1. Web scraping from militera.lib.ru
2. Text cleaning for TTS
3. Audio synthesis via Google Cloud TTS
4. Audio merging with FFmpeg
5. Sequential chapter processing with resume capability

Usage:
    python -m app.main "http://militera.lib.ru/memo/russian/slaschov_ya/index.html"
"""
import argparse
import sys
from pathlib import Path
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.config import config, AppConfig
from app.core.logging import logger, setup_logging
from app.core.atomic_ops import (
    cleanup_temp_files,
    get_chapter_final_path
)
from app.storage.storage_ops import (
    is_chapter_completed_storage,
    cleanup_parts_storage
)
from app.services.scraper import MiliteraScraper, Book
from app.services.cleaner import TextCleaner
from app.services.tts import GoogleTTSService
from app.services.merger import AudioMerger


class AudiobookPipeline:
    """
    Main pipeline for converting books to audiobooks.
    
    Orchestrates the complete workflow from URL to finished audiobook.
    """
    
    def __init__(self, app_config: Optional[AppConfig] = None):
        """
        Initialize the pipeline.
        
        Args:
            app_config: Application configuration
        """
        self.config = app_config or config
        self.scraper = MiliteraScraper(self.config.scraper)
        self.cleaner = TextCleaner(self.config.tts)
        self.tts = GoogleTTSService(self.config.tts, self.config.output)
        self.merger = AudioMerger(self.config.output)
    
    def process_book(self, toc_url: str, skip_tts: bool = False) -> Book:
        """
        Process a complete book from URL to audiobook.
        Uses sequential chapter processing:
        1. Check if chapter is already completed (final MP3 exists)
        2. If not, synthesize TTS parts
        3. Immediately merge parts into final MP3
        4. Clean up part files
        5. Move to next chapter
        
        Args:
            toc_url: URL of the book's Table of Contents page
            skip_tts: If True, only extract and save text (no audio)
            
        Returns:
            Book object with all content
        """
        logger.info(f"Starting audiobook pipeline for: {toc_url}")
        
        # Step 1: Extract book content
        logger.info("Step 1/3: Extracting book content...")
        book = self.scraper.extract_book(toc_url)
        logger.info(f"Extracted: '{book.title}' by {book.author} ({len(book.chapters)} chapters)")
        
        # Set up book-specific output directory
        self._setup_book_output(book)
        
        # Clean up any leftover temp files from previous crashes
        # Note: Local cleanup only
        local_book_dir = self.config.output.storage.get_local_path("")
        if local_book_dir:
            cleanup_temp_files(local_book_dir, self.config.output.temp_file_suffix)
        
        # Step 2: Save extracted text (for reference/debugging)
        logger.info("Step 2/3: Saving extracted text...")
        self._save_text_files(book)
        
        if skip_tts:
            logger.info("Skipping TTS (--extract-only flag)")
            return book
        
        # Step 3: Process chapters in parallel
        logger.info(f"Step 3/3: Processing chapters (TTS + merge) with {self.config.max_workers} workers...")
        logger.info("=" * 60)
        
        completed_chapters = []
        failed_chapters = []
        
        # Filter chapters with content
        chapters_to_process = [c for c in book.chapters if c.content]
        
        if not chapters_to_process:
            logger.warning("No chapters with content to process")
            return book
        
        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # Submit all chapters for processing
            future_to_chapter = {
                executor.submit(self._process_single_chapter, chapter): chapter
                for chapter in chapters_to_process
            }
            
            try:
                # Process results as they complete
                for future in as_completed(future_to_chapter):
                    chapter = future_to_chapter[future]
                    try:
                        success = future.result()
                        if success:
                            completed_chapters.append(chapter.number)
                        else:
                            failed_chapters.append(chapter.number)
                    except Exception as e:
                        logger.error(f"Chapter {chapter.number} failed with error: {e}")
                        failed_chapters.append(chapter.number)
            except KeyboardInterrupt:
                logger.info("\nInterrupted by user")
                logger.info(f"Completed chapters: {sorted(completed_chapters)}")
                logger.info(f"You can resume by running the same command again")
                # Shutdown executor gracefully
                executor.shutdown(wait=False, cancel_futures=True)
                raise
        
        logger.info("=" * 60)
        logger.info(f"Pipeline complete!")
        logger.info(f"Completed chapters: {len(completed_chapters)} - {sorted(completed_chapters)}")
        if failed_chapters:
            logger.warning(f"Failed chapters: {sorted(failed_chapters)}")
        
        # Log location
        if self.config.output.book_subdir:
            location = f"{self.config.output.book_subdir} in storage"
        else:
            location = "storage root"
        logger.info(f"Output location: {location}")
        
        return book
    
    def _process_single_chapter(self, chapter) -> bool:
        """
        Process a single chapter: TTS synthesis + merge + cleanup.
        
        Args:
            chapter: Chapter object with number, title, content
            
        Returns:
            True if successful, False otherwise
        """
        chapter_num = chapter.number
        chapter_title = chapter.title
        
        # Check if already completed
        if is_chapter_completed_storage(
            self.config.output.storage,
            self.config.output.book_subdir or "",
            chapter_num,
            chapter_title
        ) and not self.config.force_reprocess:
            final_filename = get_chapter_final_path(Path("."), chapter_num, chapter_title).name
            logger.info(f"Chapter {chapter_num}: Already completed ({final_filename}), skipping")
            return True
        
        logger.info(f"\nChapter {chapter_num}: {chapter_title}")
        logger.info("-" * 60)
        
        parts = []
        try:
            # Phase 1: Synthesize TTS parts
            logger.info(f"Phase 1/3: Synthesizing audio...")
            parts = self.tts.synthesize_chapter(
                chapter_num,
                chapter_title,
                chapter.content
            )
            
            if not parts:
                logger.warning(f"No parts generated for chapter {chapter_num}")
                return False
            
            # Phase 2: Merge parts into final MP3
            logger.info(f"Phase 2/3: Merging {len(parts)} parts...")
            merged_file = self.merger.merge_chapter_parts(
                chapter_num,
                chapter_title,
                parts
            )
            
            if not merged_file:
                logger.error(f"Merge failed for chapter {chapter_num}")
                return False
            
            # Phase 3: Clean up part files
            if self.config.output.cleanup_parts_after_merge:
                logger.info(f"Phase 3/3: Cleaning up part files...")
                parts_subdir = str(self.config.output.parts_subdir)
                if self.config.output.book_subdir:
                    parts_subdir = f"{self.config.output.book_subdir}/{parts_subdir}"
                
                cleanup_parts_storage(self.config.output.storage, parts_subdir)
            
            # Get actual filename for logging
            final_filename = Path(merged_file).name
            logger.info(f"✓ Chapter {chapter_num} complete: {final_filename}")
            return True
            
        except Exception as e:
            logger.error(f"Chapter {chapter_num} failed: {e}")
            
            # Clean up partial work
            logger.info("Cleaning up partial work...")
            for part_path in parts:
                try:
                    if self.config.output.storage.exists(part_path):
                        self.config.output.storage.delete(part_path)
                except:
                    pass
            
            return False
    
    def _setup_book_output(self, book: Book):
        """
        Set up book-specific output directories.
        
        Args:
            book: Book object with title and author
        """
        # Create book-specific config
        book_output = self.config.output.for_book(book.author, book.title)
        self.config.output = book_output
        
        # Ensure directories exist
        book_output.ensure_dirs()
        
        # Update TTS and merger with new output config
        self.tts = GoogleTTSService(self.config.tts, book_output)
        self.merger = AudioMerger(book_output)
        
        if book_output.book_subdir:
            logger.info(f"Output location: {book_output.book_subdir} in storage")
        else:
            logger.info("Output location: storage root")
    
        text_subdir = str(self.config.output.text_subdir)
        if self.config.output.book_subdir:
            text_dir_in_storage = f"{self.config.output.book_subdir}/{text_subdir}"
        else:
            text_dir_in_storage = text_subdir
            
        self.config.output.storage.mkdir(text_dir_in_storage)
        
        for chapter in book.chapters:
            if chapter.content:
                # Save raw extracted text
                raw_filename = f"chapter_{chapter.number:02d}_raw.txt"
                raw_path = f"{text_dir_in_storage}/{raw_filename}"
                
                raw_content = f"# {chapter.title}\n\n{chapter.content}"
                self.config.output.storage.write_text(raw_path, raw_content)
                
                # Save cleaned text (exactly what will be spoken by TTS)
                prepared = self.cleaner.prepare_for_tts(
                    chapter.number, 
                    chapter.title, 
                    chapter.content
                )
                clean_filename = f"chapter_{chapter.number:02d}_clean.txt"
                clean_path = f"{text_dir_in_storage}/{clean_filename}"
                
                self.config.output.storage.write_text(clean_path, prepared)
        
        logger.info(f"Saved text files to: {text_dir_in_storage}")
    
    def extract_only(self, toc_url: str) -> Book:
        """
        Only extract book content without synthesis.
        
        Args:
            toc_url: URL of the book's Table of Contents page
            
        Returns:
            Book object with all content
        """
        return self.process_book(toc_url, skip_tts=True)
    
    def merge_only_mode(self):
        """
        Legacy merge-only mode for backward compatibility.
        Note: With sequential processing, this is less useful.
        """
        logger.info("Merge-only mode (legacy)")
        logger.warning("This mode is deprecated with sequential processing.")
        logger.info("The new pipeline processes chapters one at a time (TTS + merge).")


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Convert books from militera.lib.ru to audiobooks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Extract and convert a book to audiobook
    python -m app.main "http://militera.lib.ru/memo/russian/slaschov_ya/index.html"
    
    # Extract text only (no audio synthesis)
    python -m app.main --extract-only "http://militera.lib.ru/memo/russian/slaschov_ya/index.html"
    
    # Merge existing part files
    python -m app.main --merge-only
    
    # Specify custom output directory
    python -m app.main --output-dir ./my_audiobook "http://..."
        """
    )
    
    parser.add_argument(
        "url",
        nargs="?",
        help="URL of the book's Table of Contents page"
    )
    
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only extract text, skip audio synthesis"
    )
    
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="(Deprecated) Merge mode no longer needed with sequential processing"
    )
    
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path("audiobook"),
        help="Output directory (default: audiobook)"
    )
    
    parser.add_argument(
        "--voice",
        default="ru-RU-Wavenet-B",
        help="Google TTS voice name (default: ru-RU-Wavenet-B)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocess even if chapter MP3 already exists"
    )
    
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=3,
        help="Number of chapters to process in parallel (default: 3)"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    import logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)
    
    # Configure application
    config.output.base_dir = args.output_dir
    config.tts.voice_name = args.voice
    config.force_reprocess = args.force
    config.max_workers = args.workers
    
    # Create pipeline
    pipeline = AudiobookPipeline()
    
    try:
        if args.merge_only:
            # Deprecated mode
            pipeline.merge_only_mode()
        elif args.url:
            if args.extract_only:
                pipeline.extract_only(args.url)
            else:
                pipeline.process_book(args.url)
        else:
            parser.print_help()
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
