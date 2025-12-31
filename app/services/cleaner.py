"""
Text cleaner service for preparing content for TTS.

This module handles:
- Removing markdown artifacts
- Cleaning HTML remnants
- Normalizing text for speech synthesis
- Splitting text into TTS-compatible chunks
"""
import re
from typing import List
from app.core.config import config, TTSConfig
from app.core.logging import logger


class TextCleaner:
    """
    Text cleaner for TTS preparation.
    
    Removes markdown, HTML artifacts, and normalizes text
    for natural speech synthesis.
    """
    
    # Patterns to remove
    PATTERNS_TO_REMOVE = [
        # Markdown headers (must be at line start)
        (r'^#+ *', '', re.MULTILINE),
        # Horizontal rules
        (r'^-{3,}$', '', re.MULTILINE),
        (r'^\*{3,}$', '', re.MULTILINE),
        (r'^_{3,}$', '', re.MULTILINE),
        # Bold/italic markers
        (r'\*\*([^*]+)\*\*', r'\1', 0),  # **bold**
        (r'\*([^*]+)\*', r'\1', 0),        # *italic*
        (r'__([^_]+)__', r'\1', 0),        # __bold__
        (r'_([^_]+)_', r'\1', 0),          # _italic_
        # Markdown links: [text](url) -> text
        (r'\[([^\]]+)\]\([^\)]+\)', r'\1', 0),
        # Markdown images: ![alt](url) -> nothing
        (r'!\[[^\]]*\]\([^\)]+\)', '', 0),
        # HTML tags (any remaining)
        (r'<[^>]+>', '', 0),
        # Page number markers [5], [26], etc.
        (r'\[\d+\]', '', 0),
        # Footnote markers {1}, {26}, etc.
        (r'\{\d+\}', '', 0),
        # Reference markers like [i], [ii], [a], [*]
        (r'\[[ivxlcdm]+\]', '', re.IGNORECASE),
        (r'\[[a-z]\]', '', re.IGNORECASE),
        (r'\[\*+\]', '', 0),
        # Multiple commas (artifact from quote processing)
        (r',{2,}', ',', 0),
        # Multiple periods (not ellipsis)
        (r'\.{4,}', '...', 0),
        # Multiple spaces
        (r' {2,}', ' ', 0),
        # Space before punctuation
        (r' +([,.!?;:])', r'\1', 0),
        # Multiple newlines (more than 2)
        (r'\n{3,}', '\n\n', 0),
    ]
    
    # Special characters to normalize for speech
    SPEECH_NORMALIZATIONS = [
        # Em-dash handling:
        # 1. Em-dash followed by comma/punctuation -> just the punctuation (pause)
        (r'\s*—\s*([,.!?;:])', r' \1 '),
        # 2. Em-dash at start of dialogue (Russian style) -> nothing (quote follows)
        (r'—\s*"', '"'),
        (r'—\s*«', '«'),
        # 3. Regular em-dash -> comma for pause
        (r'\s*—\s*', ', '),
        # En-dash to hyphen in words
        (r'(\w)–(\w)', r'\1-\2'),
        # En-dash between numbers (range) -> to "до" for speech
        (r'(\d)\s*–\s*(\d)', r'\1-\2'),
        # Ellipsis normalization
        (r'\.{3,}', '...'),
        # Remove special Unicode characters that TTS might mispronounce
        ('«', '"'),
        ('»', '"'),
        ('„', '"'),
        ('"', '"'),
        ('\u2018', "'"),  # Left single quotation mark '
        ('\u2019', "'"),  # Right single quotation mark '
        # Clean up multiple commas (may be created by em-dash handling)
        (r',\s*,', ','),
        # Clean up comma before period
        (r',\s*\.', '.'),
        # Roman numerals in chapter numbers (common issue)
        # Keep as-is for now, TTS handles them reasonably
    ]
    
    def __init__(self, tts_config: TTSConfig = None):
        """
        Initialize the text cleaner.
        
        Args:
            tts_config: TTS configuration for chunking settings
        """
        self.tts_config = tts_config or config.tts
    
    def clean(self, text: str) -> str:
        """
        Clean text for TTS processing.
        
        Args:
            text: Raw text with potential markdown/HTML artifacts
            
        Returns:
            Cleaned text suitable for TTS
        """
        if not text:
            return ""
        
        # Apply removal patterns
        for item in self.PATTERNS_TO_REMOVE:
            if len(item) == 3:
                pattern, replacement, flags = item
            else:
                pattern, replacement = item
                flags = re.MULTILINE
            text = re.sub(pattern, replacement, text, flags=flags)
        
        # Apply speech normalizations
        for pattern, replacement in self.SPEECH_NORMALIZATIONS:
            text = re.sub(pattern, replacement, text)
        
        # Final cleanup
        text = text.strip()
        # Remove any remaining markdown artifacts at the start
        text = re.sub(r'^[#\s]+', '', text)
        
        return text
    
    def prepare_for_tts(self, chapter_num: int, chapter_title: str, text: str) -> str:
        """
        Prepare chapter text for TTS with proper announcement.
        
        Args:
            chapter_num: Chapter number
            chapter_title: Chapter title
            text: Chapter content
            
        Returns:
            Text ready for TTS synthesis with chapter announcement
        """
        # Clean the text first
        cleaned = self.clean(text)
        
        # Clean the title (remove markdown, numbers at start if duplicate)
        clean_title = self.clean(chapter_title)
        # Remove leading numbers if they duplicate chapter_num
        clean_title = re.sub(r'^\d+\.\s*', '', clean_title)
        
        # Create chapter announcement
        # Russian-style: "Глава первая" or just use number for longer books
        announcement = f"Глава {chapter_num}. {clean_title}." if clean_title else f"Глава {chapter_num}."
        
        # Add pause after announcement (period provides natural pause)
        full_text = f"{announcement}\n\n{cleaned}"
        
        return full_text
        
        # Normalize whitespace
        text = text.strip()
        
        return text
    
    def split_into_chunks(self, text: str, max_bytes: int = None) -> List[str]:
        """
        Split text into chunks suitable for TTS API (max 5000 bytes).
        
        Splits on sentence boundaries to maintain natural speech flow.
        
        Args:
            text: Text to split
            max_bytes: Maximum bytes per chunk (default from config)
            
        Returns:
            List of text chunks
        """
        if max_bytes is None:
            max_bytes = self.tts_config.max_chunk_bytes
        
        if not text:
            return []
        
        chunks = []
        current_chunk = ""
        
        # Split into sentences first
        sentences = self._split_sentences(text)
        
        for sentence in sentences:
            sentence_bytes = len(sentence.encode('utf-8'))
            current_bytes = len(current_chunk.encode('utf-8'))
            
            # Check if adding this sentence would exceed limit
            if current_bytes + sentence_bytes + 1 > max_bytes:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                
                # Handle very long sentences by splitting on other boundaries
                if sentence_bytes > max_bytes:
                    sub_chunks = self._split_long_sentence(sentence, max_bytes)
                    chunks.extend(sub_chunks[:-1])
                    current_chunk = sub_chunks[-1] if sub_chunks else ""
                else:
                    current_chunk = sentence
            else:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
        
        # Don't forget the last chunk
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        logger.debug(f"Split text into {len(chunks)} chunks")
        return chunks
    
    def _split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences.
        
        Args:
            text: Text to split
            
        Returns:
            List of sentences
        """
        # Handle common sentence-ending patterns
        # Be careful with abbreviations (e.g., "г." for "год")
        
        # First, protect common abbreviations
        protected = text
        abbreviations = [
            (r'(\s)г\.(\s)', r'\1г<DOT>\2'),  # year
            (r'(\s)гг\.(\s)', r'\1гг<DOT>\2'),  # years
            (r'(\s)т\.(\s*)е\.', r'\1т<DOT>\2е<DOT>'),  # т.е.
            (r'(\s)т\.(\s*)д\.', r'\1т<DOT>\2д<DOT>'),  # т.д.
            (r'(\s)т\.(\s*)п\.', r'\1т<DOT>\2п<DOT>'),  # т.п.
            (r'(\s)и\.(\s*)о\.', r'\1и<DOT>\2о<DOT>'),  # и.о.
            (r'(\s)с\.(\s)', r'\1с<DOT>\2'),  # село or сравни
            (r'(\s)р\.(\s)', r'\1р<DOT>\2'),  # река
            (r'(\s)ул\.(\s)', r'\1ул<DOT>\2'),  # улица
            (r'(\s)д\.(\s)', r'\1д<DOT>\2'),  # дом
            (r'([А-Я])\.(\s*)([А-Я])\.', r'\1<DOT>\2\3<DOT>'),  # initials
        ]
        
        for pattern, repl in abbreviations:
            protected = re.sub(pattern, repl, protected)
        
        # Split on sentence-ending punctuation
        sentences = re.split(r'(?<=[.!?])\s+', protected)
        
        # Restore protected abbreviations
        sentences = [s.replace('<DOT>', '.') for s in sentences]
        
        # Filter out empty sentences
        sentences = [s.strip() for s in sentences if s.strip()]
        
        return sentences
    
    def _split_long_sentence(self, sentence: str, max_bytes: int) -> List[str]:
        """
        Split a very long sentence into smaller parts.
        
        Args:
            sentence: Long sentence to split
            max_bytes: Maximum bytes per chunk
            
        Returns:
            List of sentence parts
        """
        parts = []
        
        # Try splitting on commas, semicolons, or other natural breaks
        sub_parts = re.split(r'([,;:]\s*)', sentence)
        
        current_part = ""
        for i, sub in enumerate(sub_parts):
            if not sub:
                continue
                
            test_part = current_part + sub
            if len(test_part.encode('utf-8')) > max_bytes:
                if current_part:
                    parts.append(current_part.strip())
                
                # If even this sub-part is too long, split by words
                if len(sub.encode('utf-8')) > max_bytes:
                    word_parts = self._split_by_words(sub, max_bytes)
                    parts.extend(word_parts[:-1])
                    current_part = word_parts[-1] if word_parts else ""
                else:
                    current_part = sub
            else:
                current_part = test_part
        
        if current_part:
            parts.append(current_part.strip())
        
        return parts
    
    def _split_by_words(self, text: str, max_bytes: int) -> List[str]:
        """
        Split text by words when other methods fail.
        
        Args:
            text: Text to split
            max_bytes: Maximum bytes per chunk
            
        Returns:
            List of word groups
        """
        words = text.split()
        parts = []
        current_part = ""
        
        for word in words:
            test_part = current_part + " " + word if current_part else word
            if len(test_part.encode('utf-8')) > max_bytes:
                if current_part:
                    parts.append(current_part.strip())
                current_part = word
            else:
                current_part = test_part
        
        if current_part:
            parts.append(current_part.strip())
        
        return parts


def clean_text(text: str) -> str:
    """
    Convenience function to clean text.
    
    Args:
        text: Raw text
        
    Returns:
        Cleaned text
    """
    cleaner = TextCleaner()
    return cleaner.clean(text)


def split_for_tts(text: str, max_bytes: int = None) -> List[str]:
    """
    Convenience function to split text for TTS.
    
    Args:
        text: Text to split
        max_bytes: Maximum bytes per chunk
        
    Returns:
        List of text chunks
    """
    cleaner = TextCleaner()
    cleaned = cleaner.clean(text)
    return cleaner.split_into_chunks(cleaned, max_bytes)
