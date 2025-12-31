"""
Audio merger service using FFmpeg.

This module handles:
- Merging multiple audio parts into single chapter files
- FFmpeg integration
- Audio file management
- Atomic merge operations for safety
"""
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional
import shutil

from app.core.config import config, OutputConfig
from app.core.logging import logger
from app.core.atomic_ops import verify_mp3_file


class MergerError(Exception):
    """Custom exception for merger errors."""
    pass


class AudioMerger:
    """
    Audio file merger using FFmpeg.
    
    Merges multiple audio parts into single chapter files.
    """
    
    def __init__(self, output_config: Optional[OutputConfig] = None):
        """
        Initialize the audio merger.
        
        Args:
            output_config: Output directory configuration
        """
        self.output_config = output_config or config.output
        self._check_ffmpeg()
    
    def _check_ffmpeg(self):
        """Check if FFmpeg is available."""
        if not shutil.which('ffmpeg'):
            raise MergerError(
                "FFmpeg not found. Please install FFmpeg:\n"
                "  macOS: brew install ffmpeg\n"
                "  Ubuntu: sudo apt-get install ffmpeg"
            )
        logger.debug("FFmpeg found")
    
    def merge_chapter_parts(
        self,
        chapter_num: int,
        chapter_title: str,
        part_files: List[Path]
    ) -> Optional[Path]:
        """
        Merge multiple audio parts into a single chapter file.
        
        Args:
            chapter_num: Chapter number
            chapter_title: Chapter title (for filename)
            part_files: List of audio part files to merge
            
        Returns:
            Path to merged audio file, or None if no files to merge
        """
        if not part_files:
            logger.warning(f"No parts to merge for chapter {chapter_num}")
            return None
        
        # If only one part, just copy it
        if len(part_files) == 1:
            safe_title = self._sanitize_filename(chapter_title)
            output_file = self.output_config.book_dir / f"chapter_{chapter_num:02d}_{safe_title}.mp3"
            shutil.copy(part_files[0], output_file)
            logger.info(f"Chapter {chapter_num}: Single part copied to {output_file.name}")
            return output_file
        
        logger.info(f"Merging {len(part_files)} parts for chapter {chapter_num}")
        
        # Sort parts by name to ensure correct order
        part_files = sorted(part_files)
        
        # Create concat list file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for part_file in part_files:
                # FFmpeg concat format requires escaped paths
                escaped_path = str(part_file.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
            concat_file = Path(f.name)
        
        try:
            # Generate output filename
            safe_title = self._sanitize_filename(chapter_title)
            output_file = self.output_config.book_dir / f"chapter_{chapter_num:02d}_{safe_title}.mp3"
            
            # Use temporary file for atomic operation
            # Note: Use .tmp.mp3 so FFmpeg recognizes it as MP3 format
            temp_output = output_file.with_name(output_file.stem + '.tmp.mp3')
            
            # Run FFmpeg concat
            cmd = [
                'ffmpeg',
                '-y',  # Overwrite output
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_file),
                '-c', 'copy',  # Copy without re-encoding
                str(temp_output)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise MergerError(f"FFmpeg failed: {result.stderr}")
            
            # Verify the merged file is valid
            if not verify_mp3_file(temp_output):
                raise MergerError(f"Merged file failed validation: {temp_output}")
            
            # Atomic rename to final name
            temp_output.rename(output_file)
            
            logger.info(f"Chapter {chapter_num}: Merged to {output_file.name}")
            return output_file
            
        finally:
            # Clean up concat file
            concat_file.unlink(missing_ok=True)
    
    def merge_all_chapters(self, chapters_data: List[dict]) -> List[Path]:
        """
        Merge parts for all chapters.
        
        Args:
            chapters_data: List of dicts with 'num', 'title', 'parts' keys
            
        Returns:
            List of merged chapter file paths
        """
        merged_files = []
        
        for chapter in chapters_data:
            merged = self.merge_chapter_parts(
                chapter['num'],
                chapter['title'],
                chapter['parts']
            )
            if merged:
                merged_files.append(merged)
        
        logger.info(f"Merged {len(merged_files)} chapters")
        return merged_files
    
    
    def _transliterate_cyrillic(self, text: str) -> str:
        """
        Transliterate Cyrillic characters to Latin.
        
        Args:
            text: Text that may contain Cyrillic
            
        Returns:
            Text with Cyrillic converted to Latin
        """
        cyrillic_map = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
            'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
            'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
            'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
            'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
            'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
        }
        
        result = []
        for char in text:
            result.append(cyrillic_map.get(char, char))
        return ''.join(result)
    
    def _sanitize_filename(self, title: str) -> str:
        """
        Sanitize a title for use in a filename.
        Uses only a-z, 0-9, _ and - characters.
        Transliterates Cyrillic to Latin.
        
        Args:
            title: Original title
            
        Returns:
            Sanitized filename-safe string
        """
        import re
        
        # First transliterate Cyrillic to Latin
        safe = self._transliterate_cyrillic(title)
        # Convert to lowercase
        safe = safe.lower()
        # Remove all non-alphanumeric (except space, underscore, hyphen)
        safe = re.sub(r'[^a-z0-9\s_-]', '', safe)
        # Replace spaces with underscores
        safe = re.sub(r'\s+', '_', safe)
        # Remove multiple underscores/hyphens
        safe = re.sub(r'[_-]+', '_', safe)
        # Limit length
        safe = safe[:50]
        # Remove trailing underscores/hyphens
        safe = safe.strip('_-')
        
        return safe or "untitled"


def create_merger(output_config: Optional[OutputConfig] = None) -> AudioMerger:
    """
    Factory function to create an audio merger instance.
    
    Args:
        output_config: Output configuration
        
    Returns:
        Configured AudioMerger instance
    """
    return AudioMerger(output_config)
