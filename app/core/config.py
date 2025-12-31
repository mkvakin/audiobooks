"""
Configuration settings for the audiobook pipeline.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TTSConfig:
    """Google Cloud TTS configuration."""
    voice_name: str = "ru-RU-Wavenet-B"  # Male voice
    language_code: str = "ru-RU"
    audio_encoding: str = "MP3"
    speaking_rate: float = 1.0
    pitch: float = 0.0
    max_chunk_bytes: int = 4800  # Slightly under 5000 for safety


@dataclass
class ScraperConfig:
    """Web scraper configuration."""
    default_encoding: str = "windows-1251"
    fallback_encodings: list = field(default_factory=lambda: ["utf-8", "cp1251", "koi8-r"])
    request_timeout: int = 30
    retry_attempts: int = 3
    retry_delay: float = 1.0
    user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AudiobookBot/1.0"


@dataclass
class OutputConfig:
    """Output configuration."""
    base_dir: Path = field(default_factory=lambda: Path("audiobook"))
    parts_subdir: str = "parts"
    text_subdir: str = "text"
    chapter_prefix: str = "chapter"
    book_subdir: Optional[str] = None  # Will be set per-book
    temp_file_suffix: str = ".tmp"  # Suffix for temporary files during atomic writes
    cleanup_parts_after_merge: bool = True  # Remove part files after successful merge
    
    @property
    def book_dir(self) -> Path:
        """Get the book-specific directory."""
        if self.book_subdir:
            return self.base_dir / self.book_subdir
        return self.base_dir
    
    @property
    def parts_dir(self) -> Path:
        return self.book_dir / self.parts_subdir
    
    @property
    def text_dir(self) -> Path:
        return self.book_dir / self.text_subdir
    
    def ensure_dirs(self):
        """Create output directories if they don't exist."""
        self.book_dir.mkdir(parents=True, exist_ok=True)
        self.parts_dir.mkdir(parents=True, exist_ok=True)
        self.text_dir.mkdir(parents=True, exist_ok=True)
    
    def for_book(self, author: str, title: str) -> "OutputConfig":
        """
        Create a new config with book-specific subdirectory.
        
        Args:
            author: Book author
            title: Book title
            
        Returns:
            New OutputConfig with book_subdir set
        """
        import re
        
        # Sanitize author and title for directory name
        def sanitize(s: str) -> str:
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
            transliterated = ''.join(cyrillic_map.get(c, c) for c in s)
            
            # Convert to lowercase and use only a-z, 0-9, _, -
            safe = transliterated.lower()
            safe = re.sub(r'[^a-z0-9\s_-]', '', safe)
            safe = re.sub(r'\s+', '_', safe)
            safe = re.sub(r'[_-]+', '_', safe)
            safe = safe.strip('_-')
            # Limit length
            return safe[:50] if len(safe) > 50 else safe
        
        safe_author = sanitize(author) or "unknown"
        safe_title = sanitize(title) or "unknown"
        
        book_subdir = f"{safe_author}_{safe_title}"
        
        return OutputConfig(
            base_dir=self.base_dir,
            parts_subdir=self.parts_subdir,
            text_subdir=self.text_subdir,
            chapter_prefix=self.chapter_prefix,
            book_subdir=book_subdir
        )


@dataclass
class AppConfig:
    """Main application configuration."""
    tts: TTSConfig = field(default_factory=TTSConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    
    # GCP settings
    gcp_project_id: Optional[str] = None
    
    # Processing settings
    force_reprocess: bool = False  # Reprocess even if chapter MP3 already exists
    
    def __post_init__(self):
        self.gcp_project_id = os.environ.get("GCP_PROJECT_ID", self.gcp_project_id)


# Default configuration instance
config = AppConfig()
