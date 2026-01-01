"""
Storage abstraction layer for audiobook pipeline.

Supports:
- Local filesystem (development, local runs)
- Google Cloud Storage (GCP deployment)

Auto-detects environment and uses appropriate storage backend.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List
import os
from dataclasses import dataclass

from app.core.logging import logger


@dataclass
class StorageConfig:
    """Configuration for storage backends."""
    # Local filesystem
    base_dir: Path = Path("audiobook")
    
    # GCS
    gcs_bucket: Optional[str] = None
    gcs_project: Optional[str] = None
    
    # Shared
    temp_suffix: str = ".tmp"


class StorageAdapter(ABC):
    """Abstract interface for storage operations."""
    
    @abstractmethod
    def write_bytes(self, path: str, content: bytes, atomic: bool = True) -> None:
        """
        Write bytes to storage.
        
        Args:
            path: Path to file (relative to storage root)
            content: Bytes to write
            atomic: If True, use atomic write (temp file + rename)
        """
        pass
    
    @abstractmethod
    def write_text(self, path: str, content: str, atomic: bool = True) -> None:
        """Write text to storage."""
        pass
    
    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """Read bytes from storage."""
        pass
    
    @abstractmethod
    def read_text(self, path: str) -> str:
        """Read text from storage."""
        pass
    
    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if path exists in storage."""
        pass
    
    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete file from storage."""
        pass
    
    @abstractmethod
    def list_files(self, prefix: str) -> List[str]:
        """List files matching prefix."""
        pass
    
    @abstractmethod
    def mkdir(self, path: str) -> None:
        """Create directory (no-op for blob storage)."""
        pass
    
    @abstractmethod
    def get_local_path(self, path: str) -> Optional[Path]:
        """
        Get local filesystem path if available (for tools like ffmpeg).
        Returns None for remote storage.
        """
        pass


class LocalStorageAdapter(StorageAdapter):
    """Storage adapter for local filesystem."""
    
    def __init__(self, config: StorageConfig):
        self.config = config
        self.base_dir = config.base_dir
        logger.info(f"Initialized LocalStorageAdapter: {self.base_dir.absolute()}")
    
    def _get_full_path(self, path: str) -> Path:
        """Convert relative path to full filesystem path."""
        return self.base_dir / path
    
    def write_bytes(self, path: str, content: bytes, atomic: bool = True) -> None:
        """Write bytes to local filesystem."""
        full_path = self._get_full_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        if atomic:
            # Atomic write: temp file + rename
            temp_path = full_path.with_suffix(full_path.suffix + self.config.temp_suffix)
            temp_path.write_bytes(content)
            temp_path.replace(full_path)
        else:
            full_path.write_bytes(content)
    
    def write_text(self, path: str, content: str, atomic: bool = True) -> None:
        """Write text to local filesystem."""
        self.write_bytes(path, content.encode('utf-8'), atomic)
    
    def read_bytes(self, path: str) -> bytes:
        """Read bytes from local filesystem."""
        full_path = self._get_full_path(path)
        return full_path.read_bytes()
    
    def read_text(self, path: str) -> str:
        """Read text from local filesystem."""
        return self.read_bytes(path).decode('utf-8')
    
    def exists(self, path: str) -> bool:
        """Check if file exists."""
        return self._get_full_path(path).exists()
    
    def delete(self, path: str) -> None:
        """Delete file."""
        full_path = self._get_full_path(path)
        if full_path.exists():
            full_path.unlink()
    
    def list_files(self, prefix: str) -> List[str]:
        """List files matching prefix."""
        prefix_path = self._get_full_path(prefix)
        
        if prefix_path.is_dir():
            # List all files in directory
            return [str(p.relative_to(self.base_dir)) for p in prefix_path.glob("**/*") if p.is_file()]
        else:
            # Glob pattern
            parent = prefix_path.parent
            pattern = prefix_path.name
            if parent.exists():
                return [str(p.relative_to(self.base_dir)) for p in parent.glob(pattern) if p.is_file()]
            return []
    
    def mkdir(self, path: str) -> None:
        """Create directory."""
        full_path = self._get_full_path(path)
        full_path.mkdir(parents=True, exist_ok=True)
    
    def get_local_path(self, path: str) -> Optional[Path]:
        """Return local filesystem path."""
        return self._get_full_path(path)


class GCSStorageAdapter(StorageAdapter):
    """Storage adapter for Google Cloud Storage."""
    
    def __init__(self, config: StorageConfig):
        self.config = config
        
        if not config.gcs_bucket:
            raise ValueError("GCS bucket name is required")
        
        try:
            from google.cloud import storage
            self.client = storage.Client(project=config.gcs_project)
            self.bucket = self.client.bucket(config.gcs_bucket)
            logger.info(f"Initialized GCSStorageAdapter: gs://{config.gcs_bucket}/")
        except ImportError:
            raise ImportError("google-cloud-storage is required for GCS storage. Install with: pip install google-cloud-storage")
    
    def write_bytes(self, path: str, content: bytes, atomic: bool = True) -> None:
        """Write bytes to GCS."""
        blob = self.bucket.blob(path)
        
        # GCS uploads are atomic by default
        blob.upload_from_string(content, content_type='application/octet-stream')
        logger.debug(f"Uploaded to gs://{self.config.gcs_bucket}/{path}")
    
    def write_text(self, path: str, content: str, atomic: bool = True) -> None:
        """Write text to GCS."""
        blob = self.bucket.blob(path)
        blob.upload_from_string(content, content_type='text/plain; charset=utf-8')
    
    def read_bytes(self, path: str) -> bytes:
        """Read bytes from GCS."""
        blob = self.bucket.blob(path)
        return blob.download_as_bytes()
    
    def read_text(self, path: str) -> str:
        """Read text from GCS."""
        return self.read_bytes(path).decode('utf-8')
    
    def exists(self, path: str) -> bool:
        """Check if blob exists."""
        blob = self.bucket.blob(path)
        return blob.exists()
    
    def delete(self, path: str) -> None:
        """Delete blob."""
        blob = self.bucket.blob(path)
        blob.delete()
    
    def list_files(self, prefix: str) -> List[str]:
        """List blobs matching prefix."""
        blobs = self.client.list_blobs(self.config.gcs_bucket, prefix=prefix)
        return [blob.name for blob in blobs]
    
    def mkdir(self, path: str) -> None:
        """No-op for GCS (no directories)."""
        pass
    
    def get_local_path(self, path: str) -> Optional[Path]:
        """
        GCS doesn't have local paths.
        For tools like ffmpeg that need local files, caller must download first.
        """
        return None


def create_storage_adapter(config: Optional[StorageConfig] = None) -> StorageAdapter:
    """
    Factory function to create appropriate storage adapter.
    
    Auto-detects environment:
    - If GCP_STORAGE_BUCKET env var is set → GCSStorageAdapter
    - Otherwise → LocalStorageAdapter
    
    Args:
        config: Storage configuration (creates default if None)
        
    Returns:
        Appropriate StorageAdapter instance
    """
    if config is None:
        config = StorageConfig()
    
    # Check for GCS environment variables
    gcs_bucket = os.getenv("GCP_STORAGE_BUCKET") or os.getenv("GCS_BUCKET")
    gcs_project = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    
    if gcs_bucket:
        # Running in GCP or configured for GCS
        config.gcs_bucket = gcs_bucket
        config.gcs_project = gcs_project
        logger.info("Detected GCS environment, using GCSStorageAdapter")
        return GCSStorageAdapter(config)
    else:
        # Running locally
        logger.info("No GCS environment detected, using LocalStorageAdapter")
        return LocalStorageAdapter(config)
