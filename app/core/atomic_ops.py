"""
Atomic file operations for safe audio file handling.

This module provides utilities for:
- Writing files atomically (using temp files + rename)
- Cleaning up temporary files from interrupted operations
- Validating MP3 file integrity
"""
import os
from pathlib import Path
from typing import Optional, List
import struct

from app.core.logging import logger


def atomic_write(filepath: Path, content_bytes: bytes, temp_suffix: str = ".tmp") -> Path:
    """
    Write bytes to a file atomically using a temporary file.
    
    This prevents partial/corrupted files if the process is interrupted.
    
    Args:
        filepath: Target file path
        content_bytes: Bytes to write
        temp_suffix: Suffix for temporary file (default: .tmp)
        
    Returns:
        Path to the written file
        
    Raises:
        OSError: If write or rename fails
    """
    # Create temp file path (same directory as target)
    temp_filepath = filepath.with_suffix(filepath.suffix + temp_suffix)
    
    try:
        # Write to temporary file
        with open(temp_filepath, 'wb') as f:
            f.write(content_bytes)
        
        # Atomic rename (on POSIX systems, this is atomic)
        temp_filepath.rename(filepath)
        
        logger.debug(f"Atomically wrote {len(content_bytes)} bytes to {filepath.name}")
        return filepath
        
    except Exception as e:
        # Clean up temp file if something went wrong
        if temp_filepath.exists():
            temp_filepath.unlink()
        raise OSError(f"Failed to atomically write {filepath}: {e}") from e


def cleanup_temp_files(directory: Path, temp_suffix: str = ".tmp") -> int:
    """
    Remove all temporary files from a directory.
    
    Useful for cleaning up after a crashed/interrupted process.
    
    Args:
        directory: Directory to clean
        temp_suffix: Suffix identifying temp files (default: .tmp)
        
    Returns:
        Number of temp files removed
    """
    if not directory.exists():
        return 0
    
    count = 0
    pattern = f"*{temp_suffix}"
    
    for temp_file in directory.glob(pattern):
        try:
            temp_file.unlink()
            logger.debug(f"Removed temp file: {temp_file.name}")
            count += 1
        except Exception as e:
            logger.warning(f"Failed to remove temp file {temp_file}: {e}")
    
    # Also check subdirectories (like parts/)
    for subdir in directory.iterdir():
        if subdir.is_dir():
            count += cleanup_temp_files(subdir, temp_suffix)
    
    if count > 0:
        logger.info(f"Cleaned up {count} temporary file(s)")
    
    return count


def verify_mp3_file(filepath: Path) -> bool:
    """
    Verify basic integrity of an MP3 file.
    
    Checks:
    - File exists and is not empty
    - Has valid MP3 header (ID3 or sync frame)
    
    Args:
        filepath: Path to MP3 file
        
    Returns:
        True if file appears to be a valid MP3, False otherwise
    """
    if not filepath.exists():
        logger.debug(f"MP3 verification failed: {filepath} does not exist")
        return False
    
    # Check file size
    size = filepath.stat().st_size
    if size == 0:
        logger.warning(f"MP3 verification failed: {filepath} is empty")
        return False
    
    if size < 128:  # MP3 files should be at least this large
        logger.warning(f"MP3 verification failed: {filepath} is too small ({size} bytes)")
        return False
    
    # Check for valid MP3 header
    try:
        with open(filepath, 'rb') as f:
            header = f.read(10)
            
            # Check for ID3 tag (common at start of MP3)
            if header[:3] == b'ID3':
                logger.debug(f"MP3 verified: {filepath.name} has ID3 tag")
                return True
            
            # Check for MP3 sync frame (0xFF 0xFB or 0xFF 0xFA)
            if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
                logger.debug(f"MP3 verified: {filepath.name} has valid sync frame")
                return True
            
            logger.warning(f"MP3 verification failed: {filepath} has invalid header")
            return False
            
    except Exception as e:
        logger.warning(f"MP3 verification failed for {filepath}: {e}")
        return False


def cleanup_parts_directory(parts_dir: Path, keep_pattern: Optional[str] = None) -> int:
    """
    Clean up part files from a directory.
    
    Args:
        parts_dir: Directory containing part files
        keep_pattern: Optional glob pattern for files to keep
        
    Returns:
        Number of part files removed
    """
    if not parts_dir.exists():
        return 0
    
    count = 0
    
    for part_file in parts_dir.glob("chapter_*_part_*.mp3"):
        # Skip files matching keep pattern
        if keep_pattern and part_file.match(keep_pattern):
            continue
        
        try:
            part_file.unlink()
            logger.debug(f"Removed part file: {part_file.name}")
            count += 1
        except Exception as e:
            logger.warning(f"Failed to remove part file {part_file}: {e}")
    
    if count > 0:
        logger.info(f"Cleaned up {count} part file(s)")
    
    return count


def get_chapter_final_path(
    output_dir: Path,
    chapter_num: int,
    chapter_title: str
) -> Path:
    """
    Get the expected path for a chapter's final merged MP3.
    
    Args:
        output_dir: Base output directory
        chapter_num: Chapter number
        chapter_title: Chapter title (will be sanitized)
        
    Returns:
        Path to final merged chapter file
    """
    import re
    
    # Transliterate Cyrillic to Latin
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
    
    transliterated = ''.join(cyrillic_map.get(c, c) for c in chapter_title)
    
    # Sanitize title for filename - use only a-z, 0-9, _, -
    safe = transliterated.lower()
    safe = re.sub(r'[^a-z0-9\s_-]', '', safe)
    safe = re.sub(r'\s+', '_', safe)
    safe = re.sub(r'[_-]+', '_', safe)
    safe = safe[:50]
    safe = safe.strip('_-')
    safe_title = safe or "untitled"
    
    return output_dir / f"chapter_{chapter_num:02d}_{safe_title}.mp3"


def is_chapter_completed(
    output_dir: Path,
    chapter_num: int,
    chapter_title: str
) -> bool:
    """
    Check if a chapter has already been completed.
    
    A chapter is considered completed if its final merged MP3 file
    exists and passes basic validation.
    
    Args:
        output_dir: Base output directory
        chapter_num: Chapter number
        chapter_title: Chapter title
        
    Returns:
        True if chapter is completed, False otherwise
    """
    final_path = get_chapter_final_path(output_dir, chapter_num, chapter_title)
    
    if not final_path.exists():
        return False
    
    # Verify the file is valid
    if not verify_mp3_file(final_path):
        logger.warning(f"Chapter {chapter_num} file exists but appears corrupted, will reprocess")
        return False
    
    return True
