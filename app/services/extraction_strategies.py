"""
Book extraction strategies for different militera.lib.ru book structures.

This module provides:
- Abstract base class for extraction strategies
- MultiPageStrategy: Books with separate HTML files per chapter (e.g., Grigorenko)
- SinglePageAnchorStrategy: Books with anchors in single file (e.g., Speer)
"""
from abc import ABC, abstractmethod
from typing import List, Set, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

from app.services.scraper import Chapter
from app.core.logging import logger


class BookExtractionStrategy(ABC):
    """Abstract base class for book extraction strategies."""
    
    @abstractmethod
    def extract_chapters(
        self,
        soup: BeautifulSoup,
        toc_url: str,
        fetch_content_fn
    ) -> Tuple[List[Chapter], Set[str]]:
        """
        Extract chapters from a Table of Contents page.
        
        Args:
            soup: BeautifulSoup object of the ToC page
            toc_url: URL of the ToC page
            fetch_content_fn: Function to fetch chapter content
            
        Returns:
            Tuple of (chapters list, set of chapter URLs)
        """
        pass


class MultiPageStrategy(BookExtractionStrategy):
    """
    Strategy for books with separate HTML files per chapter.
    
    Examples: Grigorenko, Slaschov
    ToC pattern: Links to 01.html, 02.html, 03.html, etc.
    """
    
    def extract_chapters(
        self,
        soup: BeautifulSoup,
        toc_url: str,
        fetch_content_fn
    ) -> Tuple[List[Chapter], Set[str]]:
        """Extract chapters from multi-page book structure."""
        
        chapters = []
        chapter_num = 0
        seen_urls = set()
        
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
        
        return chapters, seen_urls


class SinglePageAnchorStrategy(BookExtractionStrategy):
    """
    Strategy for books with HTML anchors in a single text file.
    
    Examples: Speer
    ToC pattern: Links to text.html#01, text.html#02, text.html#03, etc.
    """
    
    def extract_chapters(
        self,
        soup: BeautifulSoup,
        toc_url: str,
        fetch_content_fn
    ) -> Tuple[List[Chapter], Set[str]]:
        """Extract chapters from single-page anchor-based book structure."""
        
        chapters = []
        chapter_num = 0
        seen_anchors = set()
        
        # Build text.html URL
        text_url = toc_url.replace('index.html', 'text.html')
        
        # Collect all anchor links from ToC
        anchor_links = []
        content_div = soup.find("div", class_="b") or soup.body
        
        if content_div:
            for link in content_div.find_all("a", href=True):
                href = link.get("href")
                
                # Look for anchor pattern: text.html#01, #02, etc.
                if '#' in href:
                    anchor = href.split('#')[-1]
                    title = link.get_text(strip=True)
                    
                    # Skip duplicates and empty
                    if anchor and anchor not in seen_anchors and title:
                        seen_anchors.add(anchor)
                        anchor_links.append((anchor, title))
        
        # If no anchors found, return empty
        if not anchor_links:
            logger.warning("No anchor links found in ToC")
            return chapters, set()
        
        # Fetch the single text.html page once
        logger.info(f"Fetching single-page content from: {text_url}")
        page_content, _ = fetch_content_fn(text_url)
        page_soup = BeautifulSoup(page_content, "lxml")
        
        # Extract content for each chapter between anchors
        for i, (anchor, title) in enumerate(anchor_links):
            chapter_num = i + 1
            
            # Find this anchor and the next anchor
            current_anchor_tag = page_soup.find("a", {"name": anchor})
            
            if not current_anchor_tag:
                logger.warning(f"Anchor {anchor} not found in text.html")
                continue
            
            # Find next anchor (or end of content)
            next_anchor = None
            if i + 1 < len(anchor_links):
                next_anchor_id = anchor_links[i + 1][0]
                next_anchor = page_soup.find("a", {"name": next_anchor_id})
            
            # Extract content between current and next anchor
            content = self._extract_between_anchors(
                current_anchor_tag,
                next_anchor,
                page_soup
            )
            
            chapters.append(Chapter(
                number=chapter_num,
                title=title,
                url=f"{text_url}#{anchor}",
                content=content
            ))
            
            logger.debug(f"Extracted chapter {chapter_num}: {title} ({len(content)} chars)")
        
        return chapters, {text_url}
    
    def _extract_between_anchors(
        self,
        start_anchor,
        end_anchor,
        soup: BeautifulSoup
    ) -> str:
        """
        Extract text content between two anchor tags.
        
        Args:
            start_anchor: Starting anchor tag
            end_anchor: Ending anchor tag (or None for end of document)
            soup: BeautifulSoup object
            
        Returns:
            Extracted text content
        """
        text_parts = []
        
        # Start from the anchor and collect siblings until we hit the next anchor
        current = start_anchor.next_sibling
        
        while current:
            # Stop if we hit the next anchor
            if end_anchor and current == end_anchor:
                break
            
            # Extract text from paragraphs
            if hasattr(current, 'name'):
                if current.name == 'p':
                    para_text = current.get_text(strip=True)
                    if para_text:
                        # Clean the text
                        para_text = self._clean_paragraph(para_text)
                        if para_text:
                            text_parts.append(para_text)
                
                # Also check for headings
                elif current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    heading = current.get_text(strip=True)
                    if heading:
                        text_parts.append(heading)
            
            current = current.next_sibling
        
        return "\n\n".join(text_parts)
    
    def _clean_paragraph(self, text: str) -> str:
        """Clean a paragraph of text."""
        # Remove page number markers like [5]
        text = re.sub(r'\s*\[\d+\]\s*', ' ', text)
        # Remove footnote markers like {1}
        text = re.sub(r'\s*\{\d+\}\s*', ' ', text)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove leading/trailing whitespace
        text = text.strip()
        return text


def detect_book_structure(soup: BeautifulSoup) -> BookExtractionStrategy:
    """
    Auto-detect which extraction strategy to use based on ToC structure.
    
    Args:
        soup: BeautifulSoup object of the ToC page
        
    Returns:
        Appropriate extraction strategy instance
    """
    content_div = soup.find("div", class_="b") or soup.body
    
    if not content_div:
        # Default to multi-page
        return MultiPageStrategy()
    
    # Count different link types
    html_file_links = 0
    anchor_links = 0
    
    for link in content_div.find_all("a", href=True):
        href = link.get("href")
        
        # Check for .html file links (excluding index.html)
        if href.endswith(".html") and href != "index.html" and '#' not in href:
            html_file_links += 1
        
        # Check for anchor links (#01, #02, etc.)
        elif '#' in href:
            anchor_links += 1
    
    logger.info(f"ToC analysis: {html_file_links} HTML file links, {anchor_links} anchor links")
    
    # Decision logic
    if anchor_links > html_file_links and anchor_links >= 3:
        logger.info("Detected single-page anchor-based book structure")
        return SinglePageAnchorStrategy()
    else:
        logger.info("Detected multi-page book structure")
        return MultiPageStrategy()
