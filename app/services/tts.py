"""
Google Cloud Text-to-Speech service.

This module handles:
- Converting text to speech using GCP TTS API
- Managing audio file generation
- Handling API rate limits and errors
- Atomic file writes for safety
"""
import os
from pathlib import Path
from typing import List, Optional
from google.cloud import texttospeech
from google.api_core import exceptions as gcp_exceptions

from app.core.config import config, TTSConfig, OutputConfig
from app.core.logging import logger
from app.core.atomic_ops import verify_mp3_file
from app.storage.storage_ops import atomic_write_storage, verify_mp3_storage
from app.services.cleaner import TextCleaner


class TTSError(Exception):
    """Custom exception for TTS errors."""
    pass


class GoogleTTSService:
    """
    Google Cloud Text-to-Speech service.
    
    Handles conversion of text to audio using GCP TTS API.
    """
    
    def __init__(
        self,
        tts_config: Optional[TTSConfig] = None,
        output_config: Optional[OutputConfig] = None
    ):
        """
        Initialize the TTS service.
        
        Args:
            tts_config: TTS configuration
            output_config: Output directory configuration
        """
        self.tts_config = tts_config or config.tts
        self.output_config = output_config or config.output
        self.client = None
        self.cleaner = TextCleaner(self.tts_config)
        
    def _ensure_client(self):
        """Ensure TTS client is initialized."""
        if self.client is None:
            try:
                self.client = texttospeech.TextToSpeechClient()
                logger.info("Google TTS client initialized")
            except Exception as e:
                raise TTSError(
                    f"Failed to initialize Google TTS client. "
                    f"Make sure you have authenticated with 'gcloud auth application-default login'. "
                    f"Error: {e}"
                )
    
    def _get_voice_params(self) -> texttospeech.VoiceSelectionParams:
        """Get voice selection parameters."""
        return texttospeech.VoiceSelectionParams(
            language_code=self.tts_config.language_code,
            name=self.tts_config.voice_name
        )
    
    def _get_audio_config(self) -> texttospeech.AudioConfig:
        """Get audio configuration."""
        encoding = getattr(
            texttospeech.AudioEncoding,
            self.tts_config.audio_encoding,
            texttospeech.AudioEncoding.MP3
        )
        return texttospeech.AudioConfig(
            audio_encoding=encoding,
            speaking_rate=self.tts_config.speaking_rate,
            pitch=self.tts_config.pitch
        )
    
    def synthesize_text(self, text: str) -> bytes:
        """
        Synthesize a single text chunk to audio.
        
        Args:
            text: Text to synthesize (must be under 5000 bytes)
            
        Returns:
            Audio content as bytes
            
        Raises:
            TTSError: If synthesis fails
        """
        self._ensure_client()
        
        # Validate text size
        text_bytes = len(text.encode('utf-8'))
        if text_bytes > 5000:
            raise TTSError(f"Text chunk too large: {text_bytes} bytes (max 5000)")
        
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        try:
            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=self._get_voice_params(),
                audio_config=self._get_audio_config()
            )
            return response.audio_content
            
        except gcp_exceptions.InvalidArgument as e:
            raise TTSError(f"Invalid TTS request: {e}")
        except gcp_exceptions.ResourceExhausted as e:
            raise TTSError(f"TTS quota exceeded: {e}")
        except Exception as e:
            raise TTSError(f"TTS synthesis failed: {e}")
    
    def synthesize_chapter(
        self,
        chapter_num: int,
        chapter_title: str,
        text: str
    ) -> List[str]:
        """
        Synthesize a complete chapter to audio files.
        
        Args:
            chapter_num: Chapter number
            chapter_title: Chapter title (for filename)
            text: Chapter text content
            
        Returns:
            List of paths to generated audio files
        """
        logger.info(f"Synthesizing chapter {chapter_num}: {chapter_title}")
        
        # Ensure output directories exist (no-op for remote storage)
        self.output_config.ensure_dirs()
        self.output_config.storage.mkdir(str(self.output_config.parts_subdir))
        
        # Prepare text for TTS (includes chapter announcement and cleaning)
        prepared_text = self.cleaner.prepare_for_tts(chapter_num, chapter_title, text)
        chunks = self.cleaner.split_into_chunks(prepared_text)
        
        if not chunks:
            logger.warning(f"No content to synthesize for chapter {chapter_num}")
            return []
        
        logger.info(f"Chapter {chapter_num}: {len(chunks)} chunks to synthesize")
        
        # Sanitize title for filename
        safe_title = self._sanitize_filename(chapter_title)
        
        # Generate audio files with atomic writes
        audio_files = []
        for part_num, chunk in enumerate(chunks, start=1):
            filename = f"chapter_{chapter_num:02d}_part_{part_num:03d}_of_{len(chunks):03d}_{safe_title}.mp3"
            
            # Paths in storage should be relative to book root for clarity
            # But the current config handles base_dir. We want the full relative path from storage root.
            # Usually: book_dir/parts/filename
            if self.output_config.book_subdir:
                storage_path = f"{self.output_config.book_subdir}/{self.output_config.parts_subdir}/{filename}"
            else:
                storage_path = f"{self.output_config.parts_subdir}/{filename}"
            
            # Skip if file already exists and is valid (resumability)
            if self.output_config.storage.exists(storage_path) and verify_mp3_storage(self.output_config.storage, storage_path):
                logger.info(f"Part {part_num}/{len(chunks)} already exists, skipping")
                audio_files.append(storage_path)
                continue
            
            try:
                logger.info(f"Synthesizing part {part_num}/{len(chunks)}... ")
                audio_content = self.synthesize_text(chunk)
                
                # Atomic write to storage
                atomic_write_storage(
                    self.output_config.storage,
                    storage_path,
                    audio_content
                )
                
                # Verify the file was written correctly
                if not verify_mp3_storage(self.output_config.storage, storage_path):
                    raise TTSError(f"Generated MP3 file failed validation: {storage_path}")
                
                audio_files.append(storage_path)
                logger.info(f"✓ Created {filename} ({len(audio_content)} bytes)")
                
            except TTSError as e:
                logger.error(f"Failed to synthesize part {part_num} of chapter {chapter_num}: {e}")
                # Don't continue with partial chapter - raise to trigger cleanup
                raise
            except Exception as e:
                logger.error(f"Unexpected error synthesizing part {part_num}: {e}")
                raise TTSError(f"Failed to synthesize part {part_num}") from e
        
        logger.info(f"Chapter {chapter_num}: Successfully generated {len(audio_files)} audio files")
        return audio_files
    
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


def create_tts_service(
    tts_config: Optional[TTSConfig] = None,
    output_config: Optional[OutputConfig] = None
) -> GoogleTTSService:
    """
    Factory function to create a TTS service instance.
    
    Args:
        tts_config: TTS configuration
        output_config: Output configuration
        
    Returns:
        Configured GoogleTTSService instance
    """
    return GoogleTTSService(tts_config, output_config)
