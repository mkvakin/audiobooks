"""
Web scraper service for extracting book content from militera.lib.ru.

This module handles:
- Fetching ToC (Table of Contents) pages
- Extracting chapter links
- Downloading chapter content with proper encoding handling
- Parsing HTML content to extract clean text
- Following pagination links ("Дальше" / Next page)
"""
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup, Tag

from app.core.config import config, ScraperConfig
from app.core.logging import logger


@dataclass
class Chapter:
    """Represents a book chapter."""
    number: int
    title: str
    url: str
    content: Optional[str] = None


@dataclass
class Book:
    """Represents a book with its metadata and chapters."""
    title: str
    author: str
    toc_url: str
    chapters: List[Chapter]
    toc_urls: Set[str] = field(default_factory=set)  # All URLs from ToC for pagination detection


class MiliteraScraperError(Exception):
    """Custom exception for scraper errors."""
    pass


class MiliteraScraper:
    """
    Scraper for militera.lib.ru book content.
    
    Handles:
    - Windows-1251 encoding (common for Russian legacy sites)
    - ToC parsing to discover chapter links
    - Chapter content extraction with HTML cleaning
    - Following pagination links ("Дальше" / Next page)
    """
    
    # Pagination link text patterns (Russian)
    PAGINATION_PATTERNS = [
        r'дальше',      # "further/next"
        r'далее',       # "further"
        r'продолжение', # "continuation"
        r'след\.?',     # "next" abbreviated
        r'следующ',     # "following"
        r'вперед',      # "forward"
        r'>>',          # navigation arrows
        r'→',           # arrow
    ]
    
    # Patterns to skip (not pagination)
    SKIP_PATTERNS = [
        r'^index\.html$',
        r'^app\.html$',
        r'^#',           # anchor links
        r'^mailto:',     # email links
        r'^https?://',   # external links
        r'\.jpg$', r'\.png$', r'\.gif$',  # images
    ]
    
    def __init__(self, scraper_config: Optional[ScraperConfig] = None):
        """
        Initialize the scraper.
        
        Args:
            scraper_config: Scraper configuration (uses default if not provided)
        """
        self.config = scraper_config or config.scraper
        self.session = self._create_session()
        self._toc_urls: Set[str] = set()  # URLs from ToC to avoid double-navigation
    
    def _create_session(self) -> requests.Session:
        """Create a configured requests session."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
        })
        return session
    
    def _is_pagination_link(self, link: Tag, current_url: str) -> Optional[str]:
        """
        Check if a link is a pagination link (e.g., "Дальше" / Next).
        
        Uses a hybrid approach:
        1. Boolean rules (fast) - check patterns and URL structure
        2. Skip links that are in ToC (would cause double navigation)
        
        Args:
            link: BeautifulSoup link element
            current_url: Current page URL for resolving relative links
            
        Returns:
            Full URL if pagination link, None otherwise
        """
        href = link.get("href", "")
        if not href:
            return None
        
        # Skip patterns (mailto, anchors, images, external, etc.)
        for pattern in self.SKIP_PATTERNS:
            if re.search(pattern, href, re.IGNORECASE):
                return None
        
        # Build full URL
        full_url = urljoin(current_url, href)
        
        # Skip if URL is in ToC (would be double navigation to another chapter)
        if full_url in self._toc_urls:
            logger.debug(f"Skipping link in ToC: {href}")
            return None
        
        # Skip if same as current page
        if full_url == current_url:
            return None
        
        # Check link text for pagination patterns
        link_text = link.get_text(strip=True).lower()
        
        for pattern in self.PAGINATION_PATTERNS:
            if re.search(pattern, link_text, re.IGNORECASE):
                # Additional check: sequential file pattern (e.g., 01.html → 01a.html or 02.html)
                if self._is_sequential_url(current_url, full_url):
                    logger.debug(f"Found pagination link: '{link_text}' -> {href}")
                    return full_url
        
        return None
    
    def _is_sequential_url(self, current_url: str, next_url: str) -> bool:
        """
        Check if URLs appear to be sequential pages of the same chapter.
        
        Patterns detected:
        - 01.html -> 01a.html, 01b.html (letter suffix)
        - 01.html -> 02.html (number sequence) - only if same directory
        - chapter1.html -> chapter1_2.html (underscore continuation)
        
        Args:
            current_url: Current page URL
            next_url: Potential next page URL
            
        Returns:
            True if URLs appear sequential
        """
        current_path = urlparse(current_url).path
        next_path = urlparse(next_url).path
        
        # Must be same directory
        current_dir = current_path.rsplit('/', 1)[0]
        next_dir = next_path.rsplit('/', 1)[0]
        if current_dir != next_dir:
            return False
        
        # Extract filenames without extension
        current_name = current_path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
        next_name = next_path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
        
        # Pattern 1: Same base with letter suffix (01 -> 01a, 01a -> 01b)
        if next_name.startswith(current_name) and len(next_name) == len(current_name) + 1:
            suffix = next_name[-1]
            if suffix.isalpha():
                return True
        
        # Pattern 2: Letter increment (01a -> 01b)
        if len(current_name) > 0 and current_name[-1].isalpha():
            base = current_name[:-1]
            if next_name.startswith(base) and len(next_name) == len(current_name):
                current_suffix = current_name[-1]
                next_suffix = next_name[-1]
                if next_suffix.isalpha() and ord(next_suffix) == ord(current_suffix) + 1:
                    return True
        
        # Pattern 3: Underscore continuation (chapter1 -> chapter1_2)
        if next_name.startswith(current_name + "_"):
            return True
        
        return True  # Be permissive if text matches pagination pattern
    
    def _fetch_with_encoding(self, url: str) -> Tuple[str, str]:
        """
        Fetch a URL and detect/handle encoding properly.
        
        Args:
            url: URL to fetch
            
        Returns:
            Tuple of (content, detected_encoding)
            
        Raises:
            MiliteraScraperError: If fetch fails after retries
        """
        last_error = None
        
        for attempt in range(self.config.retry_attempts):
            try:
                response = self.session.get(
                    url,
                    timeout=self.config.request_timeout
                )
                response.raise_for_status()
                
                # Try to detect encoding from content-type header
                content_type = response.headers.get("Content-Type", "")
                encoding = None
                
                if "charset=" in content_type:
                    encoding = content_type.split("charset=")[-1].strip()
                
                # Check meta tag in HTML for encoding
                if not encoding:
                    # First decode with a safe encoding to parse meta tags
                    temp_content = response.content.decode("latin-1", errors="replace")
                    meta_match = re.search(
                        r'<meta[^>]+charset=["\']?([^"\'\s>]+)',
                        temp_content,
                        re.IGNORECASE
                    )
                    if meta_match:
                        encoding = meta_match.group(1)
                
                # Default to Windows-1251 for militera.lib.ru
                if not encoding:
                    encoding = self.config.default_encoding
                
                # Decode content with detected encoding
                try:
                    content = response.content.decode(encoding, errors="replace")
                except (UnicodeDecodeError, LookupError):
                    # Try fallback encodings
                    for fallback in self.config.fallback_encodings:
                        try:
                            content = response.content.decode(fallback, errors="replace")
                            encoding = fallback
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue
                    else:
                        # Last resort: decode with replacement
                        content = response.content.decode("utf-8", errors="replace")
                        encoding = "utf-8"
                
                logger.debug(f"Fetched {url} with encoding {encoding}")
                return content, encoding
                
            except requests.RequestException as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < self.config.retry_attempts - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
        
        raise MiliteraScraperError(f"Failed to fetch {url} after {self.config.retry_attempts} attempts: {last_error}")
    
    def parse_toc(self, toc_url: str) -> Book:
        """
        Parse a Table of Contents page to extract book info and chapter links.
        
        Args:
            toc_url: URL of the ToC page (index.html)
            
        Returns:
            Book object with chapters populated
        """
        logger.info(f"Parsing ToC from: {toc_url}")
        
        content, encoding = self._fetch_with_encoding(toc_url)
        # Use lxml parser - handles malformed HTML better (e.g., unclosed tags)
        soup = BeautifulSoup(content, "lxml")
        
        # Extract book metadata
        # Title is typically in a div with specific class or structure
        title_elem = soup.find("div", class_="") or soup.find("title")
        title = "Unknown Book"
        author = "Unknown Author"
        
        # Try to extract from title tag
        if soup.title:
            title_text = soup.title.get_text()
            # Parse title like "ВОЕННАЯ ЛИТЕРАТУРА --[ Мемуары ]-- Слащов-Крымский Я. А. Крым, 1920"
            if "--" in title_text:
                parts = title_text.split("--")
                if len(parts) >= 3:
                    author_title = parts[-1].strip()
                    # Split author and title
                    if "." in author_title:
                        # Find last occurrence of pattern like "Я. А." or similar
                        match = re.search(r'^(.+?\.\s*[А-Я]\.)\s*(.+)$', author_title)
                        if match:
                            author = match.group(1).strip()
                            title = match.group(2).strip()
                        else:
                            title = author_title
        
        # Find chapter links in the content area
        chapters = []
        chapter_num = 0
        seen_urls = set()  # Track seen URLs to avoid duplicates
        
        # Look for the content div
        content_div = soup.find("div", class_="b") or soup.body
        
        if content_div:
            # Find all paragraph links that look like chapter links
            for p in content_div.find_all("p"):
                link = p.find("a")
                if link and link.get("href"):
                    href = link.get("href")
                    chapter_title = link.get_text(strip=True)
                    
                    # Skip non-chapter links (illustrations, etc.)
                    if href.endswith(".html") and chapter_title:
                        # Filter out navigation links
                        if href not in ["index.html"] and not href.startswith("http"):
                            full_url = urljoin(toc_url, href)
                            
                            # Skip duplicate URLs
                            if full_url in seen_urls:
                                logger.debug(f"Skipping duplicate URL: {full_url}")
                                continue
                            seen_urls.add(full_url)
                            
                            chapter_num += 1
                            
                            # Clean title - remove page numbers like [5]
                            clean_title = re.sub(r'\s*\[\d+\]\s*$', '', chapter_title)
                            
                            chapters.append(Chapter(
                                number=chapter_num,
                                title=clean_title,
                                url=full_url
                            ))
                            logger.debug(f"Found chapter {chapter_num}: {clean_title}")
        
        logger.info(f"Found {len(chapters)} chapters in '{title}' by {author}")
        
        return Book(
            title=title,
            author=author,
            toc_url=toc_url,
            chapters=chapters,
            toc_urls=seen_urls  # Store all chapter URLs for pagination detection
        )
    
    def fetch_chapter_content(self, chapter: Chapter, toc_urls: Optional[Set[str]] = None) -> str:
        """
        Fetch and extract the text content of a chapter, following pagination links.
        
        Args:
            chapter: Chapter object with URL
            toc_urls: Set of URLs from ToC (to avoid double navigation)
            
        Returns:
            Clean text content of the chapter (may span multiple pages)
        """
        logger.info(f"Fetching chapter {chapter.number}: {chapter.title}")
        
        # Store ToC URLs for pagination detection
        if toc_urls:
            self._toc_urls = toc_urls
        
        all_text_parts = []
        visited_urls = set()
        current_url = chapter.url
        page_num = 1
        max_pages = 50  # Safety limit to prevent infinite loops
        
        while current_url and page_num <= max_pages:
            # Avoid revisiting pages
            if current_url in visited_urls:
                logger.debug(f"Already visited: {current_url}")
                break
            visited_urls.add(current_url)
            
            # Fetch and parse page
            text_parts, next_url = self._extract_page_content(current_url, page_num > 1)
            all_text_parts.extend(text_parts)
            
            if next_url:
                logger.info(f"Following pagination link to page {page_num + 1}: {next_url}")
                # Small delay between pagination requests
                time.sleep(0.3)
            
            current_url = next_url
            page_num += 1
        
        if page_num > 2:
            logger.info(f"Chapter {chapter.number} spans {page_num - 1} pages")
        
        # Join with double newlines for paragraph separation
        full_text = "\n\n".join(all_text_parts)
        
        logger.info(f"Extracted {len(full_text)} characters from chapter {chapter.number}")
        
        return full_text
    
    def _extract_page_content(self, url: str, is_continuation: bool = False) -> Tuple[List[str], Optional[str]]:
        """
        Extract text content from a single page.
        
        Args:
            url: Page URL
            is_continuation: If True, skip duplicate heading from continuation pages
            
        Returns:
            Tuple of (text_parts list, next_page_url or None)
        """
        content, encoding = self._fetch_with_encoding(url)
        # Use lxml parser - militera.lib.ru has unclosed <p> tags which html.parser mishandles
        soup = BeautifulSoup(content, "lxml")
        
        # Find the main content div
        content_div = soup.find("div", class_="b")
        
        if not content_div:
            # Fallback: try to find body content excluding navigation
            content_div = soup.body
        
        if not content_div:
            logger.warning(f"No content found for {url}")
            return [], None
        
        text_parts = []
        
        # Get the chapter title/heading if present (only for first page)
        if not is_continuation:
            heading = content_div.find(["h1", "h2", "h3", "h4"])
            if heading:
                heading_text = heading.get_text(strip=True)
                text_parts.append(heading_text)
        
        # Get all paragraphs
        for p in content_div.find_all("p"):
            para_text = p.get_text(strip=True)
            if para_text:
                # Clean up the text
                para_text = self._clean_paragraph(para_text)
                if para_text:
                    text_parts.append(para_text)
        
        # Look for pagination link
        next_url = None
        for link in content_div.find_all("a"):
            pagination_url = self._is_pagination_link(link, url)
            if pagination_url:
                next_url = pagination_url
                break  # Take first matching pagination link
        
        return text_parts, next_url
    
    def _clean_paragraph(self, text: str) -> str:
        """
        Clean a paragraph of text.
        
        Args:
            text: Raw paragraph text
            
        Returns:
            Cleaned text
        """
        # Remove page number markers like [5]
        text = re.sub(r'\s*\[\d+\]\s*', ' ', text)
        
        # Remove footnote markers like {1}
        text = re.sub(r'\s*\{\d+\}\s*', ' ', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove leading/trailing whitespace
        text = text.strip()
        
        return text
    
    def extract_book(self, toc_url: str) -> Book:
        """
        Extract a complete book from a ToC URL.
        
        Args:
            toc_url: URL of the Table of Contents page
            
        Returns:
            Book object with all chapters fetched
        """
        book = self.parse_toc(toc_url)
        
        for chapter in book.chapters:
            chapter.content = self.fetch_chapter_content(chapter, book.toc_urls)
            # Small delay to be polite to the server
            time.sleep(0.5)
        
        logger.info(f"Extracted complete book: {book.title}")
        return book


def create_scraper(scraper_config: Optional[ScraperConfig] = None) -> MiliteraScraper:
    """
    Factory function to create a scraper instance.
    
    Args:
        scraper_config: Optional configuration
        
    Returns:
        Configured MiliteraScraper instance
    """
    return MiliteraScraper(scraper_config)
