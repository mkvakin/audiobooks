"""
Storage-aware wrappers for atomic operations.

These functions bridge the storage adapter with the application logic,
providing storage-agnostic atomic operations.
"""
from pathlib import Path
from typing import Optional
import tempfile

from app.storage import StorageAdapter
from app.core.logging import logger


def atomic_write_storage(
    storage: StorageAdapter,
    path: str,
    content: bytes
) -> None:
    """
    Write bytes to storage atomically.
    
    Args:
        storage: Storage adapter to use
        path: Relative path in storage
        content: Bytes to write
    """
    # Storage adapters handle atomicity internally
    storage.write_bytes(path, content, atomic=True)


def verify_mp3_storage(storage: StorageAdapter, path: str) -> bool:
    """
    Verify MP3 file integrity in storage.
    
    Args:
        storage: Storage adapter
        path: Path to MP3 file
        
    Returns:
        True if valid MP3
    """
    if not storage.exists(path):
        return False
    
    try:
        # Read first 10 bytes to check header
        content = storage.read_bytes(path)
        
        if len(content) < 128:
            logger.warning(f"MP3 too small: {path}")
            return False
        
        header = content[:10]
        
        # Check for ID3 tag or MP3 sync frame
        if header[:3] == b'ID3':
            return True
        
        if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
            return True
        
        logger.warning(f"Invalid MP3 header: {path}")
        return False
        
    except Exception as e:
        logger.warning(f"MP3 verification failed for {path}: {e}")
        return False


def is_chapter_completed_storage(
    storage: StorageAdapter,
    book_dir: str,
    chapter_num: int,
    chapter_title: str
) -> bool:
    """
    Check if chapter is completed in storage.
    
    Args:
        storage: Storage adapter
        book_dir: Book directory path
        chapter_num: Chapter number
        chapter_title: Chapter title
        
    Returns:
        True if completed and valid
    """
    from app.core.atomic_ops import get_chapter_final_path
    from pathlib import Path
    
    # Get expected filename
    temp_path = get_chapter_final_path(Path(book_dir), chapter_num, chapter_title)
    relative_path = f"{book_dir}/{temp_path.name}"
    
    # Check if exists and valid
    if not storage.exists(relative_path):
        return False
    
    if not verify_mp3_storage(storage, relative_path):
        logger.warning(f"Chapter {chapter_num} exists but appears corrupted")
        return False
    
    return True


def cleanup_parts_storage(
    storage: StorageAdapter,
    parts_dir: str
) -> int:
    """
    Clean up part files from storage.
    
    Args:
        storage: Storage adapter
        parts_dir: Parts directory path
        
    Returns:
        Number of files deleted
    """
    try:
        files = storage.list_files(parts_dir)
        count = 0
        
        for file_path in files:
            if "part_" in file_path and file_path.endswith(".mp3"):
                try:
                    storage.delete(file_path)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")
        
        if count > 0:
            logger.info(f"Cleaned up {count} part file(s)")
        
        return count
    except Exception as e:
        logger.error(f"Failed to cleanup parts: {e}")
        return 0


def get_temp_local_path(storage: StorageAdapter, remote_path: str) -> Optional[Path]:
    """
    Get a temporary local path for a remote file.
    
    For local storage, returns the actual path.
    For remote storage (GCS), downloads to temp file.
    
    Args:
        storage: Storage adapter
        remote_path: Path in storage
        
    Returns:
        Local Path if available, None if file doesn't exist
    """
    # Check if storage has local paths
    local_path = storage.get_local_path(remote_path)
    
    if local_path:
        # Local storage - return direct path
        return local_path if local_path.exists() else None
    
    # Remote storage - download to temp file
    if not storage.exists(remote_path):
        return None
    
    try:
        content = storage.read_bytes(remote_path)
        
        # Create temp file with same extension
        suffix = Path(remote_path).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            return Path(tmp.name)
    except Exception as e:
        logger.error(f"Failed to download {remote_path} to temp file: {e}")
        return None
