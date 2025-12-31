"""
Unit tests for book extraction strategies.

Tests:
- Auto-detection logic (multi-page vs single-page anchor)
- MultiPageStrategy extraction
- SinglePageAnchorStrategy extraction
- Edge cases and error handling
"""
import pytest
from bs4 import BeautifulSoup
from unittest.mock import Mock, MagicMock

from app.services.scraper import Chapter
from app.services.extraction_strategies import (
    BookExtractionStrategy,
    MultiPageStrategy,
    SinglePageAnchorStrategy,
    detect_book_structure
)


# ============================================================================
# Fixtures: Mock ToC HTML
# ============================================================================

@pytest.fixture
def multi_page_toc_html():
    """Mock ToC HTML for multi-page book (Grigorenko-style)."""
    return """
    <html>
    <head><title>ВОЕННАЯ ЛИТЕРАТУРА --[ Мемуары ]-- Григоренко П.Г. В подполье можно встретить только крыс</title></head>
    <body>
        <div class="b">
            <p><a href="01.html">От автора</a></p>
            <p><a href="02.html">1. Я не был ребенком</a></p>
            <p><a href="03.html">2. Я узнаю свою фамилию</a></p>
            <p><a href="04.html">3. Первые опыты самостоятельной жизни</a></p>
            <p><a href="05.html">4. Отец Владимир Донской [5]</a></p>
            <p><a href="index.html">Вернуться к оглавлению</a></p>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def single_page_anchor_toc_html():
    """Mock ToC HTML for single-page anchor book (Speer-style)."""
    return """
    <html>
    <head><title>ВОЕННАЯ ЛИТЕРАТУРА --[ Мемуары ]-- Шпеер А. Воспоминания</title></head>
    <body>
        <div class="b">
            <p><a href="text.html#01">Предисловие</a></p>
            <p><a href="text.html#02">Часть первая</a></p>
            <p><a href="text.html#03">Часть вторая</a></p>
            <p><a href="text.html#04">Часть третья</a></p>
            <p><a href="index.html">Назад к оглавлению</a></p>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def single_page_content_html():
    """Mock content HTML for single-page anchor book."""
    return """
    <html>
    <body>
        <div class="b">
            <a name="01"></a>
            <h2>Предисловие</h2>
            <p>Это текст предисловия.</p>
            <p>Еще один параграф предисловия.</p>
            
            <a name="02"></a>
            <h2>Часть первая</h2>
            <p>Первый параграф части первой.</p>
            <p>Второй параграф части первой.</p>
            
            <a name="03"></a>
            <h2>Часть вторая</h2>
            <p>Первый параграф части второй.</p>
            
            <a name="04"></a>
            <h2>Часть третья</h2>
            <p>Последний параграф.</p>
        </div>
    </body>
    </html>
    """


# ============================================================================
# Tests: Auto-detection
# ============================================================================

def test_detect_multi_page_structure(multi_page_toc_html):
    """Test that multi-page book structure is detected correctly."""
    soup = BeautifulSoup(multi_page_toc_html, "lxml")
    strategy = detect_book_structure(soup)
    
    assert isinstance(strategy, MultiPageStrategy)


def test_detect_single_page_anchor_structure(single_page_anchor_toc_html):
    """Test that single-page anchor structure is detected correctly."""
    soup = BeautifulSoup(single_page_anchor_toc_html, "lxml")
    strategy = detect_book_structure(soup)
    
    assert isinstance(strategy, SinglePageAnchorStrategy)


def test_detect_defaults_to_multi_page_on_empty():
    """Test that empty/malformed ToC defaults to multi-page strategy."""
    html = "<html><body></body></html>"
    soup = BeautifulSoup(html, "lxml")
    strategy = detect_book_structure(soup)
    
    assert isinstance(strategy, MultiPageStrategy)


# ============================================================================
# Tests: MultiPageStrategy
# ============================================================================

def test_multi_page_strategy_extracts_chapters(multi_page_toc_html):
    """Test that MultiPageStrategy correctly extracts chapter links."""
    soup = BeautifulSoup(multi_page_toc_html, "lxml")
    strategy = MultiPageStrategy()
    
    # Mock fetch function (not needed for multi-page ToC parsing)
    mock_fetch = Mock()
    
    chapters, seen_urls = strategy.extract_chapters(
        soup,
        "https://example.com/index.html",
        mock_fetch
    )
    
    # Verify correct number of chapters (exclude index.html link)
    assert len(chapters) == 5
    
    # Verify chapter details
    assert chapters[0].number == 1
    assert chapters[0].title == "От автора"
    assert chapters[0].url == "https://example.com/01.html"
    
    assert chapters[1].number == 2
    assert chapters[1].title == "1. Я не был ребенком"
    
    # Verify page number markers are removed from titles
    assert chapters[4].title == "4. Отец Владимир Донской"
    assert "[5]" not in chapters[4].title
    
    # Verify seen_urls contains all chapter URLs
    assert len(seen_urls) == 5


def test_multi_page_strategy_skips_duplicates():
    """Test that MultiPageStrategy skips duplicate chapter URLs."""
    html = """
    <html><body><div class="b">
        <p><a href="01.html">Chapter 1</a></p>
        <p><a href="01.html">Chapter 1 (duplicate)</a></p>
        <p><a href="02.html">Chapter 2</a></p>
    </div></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    strategy = MultiPageStrategy()
    
    chapters, seen_urls = strategy.extract_chapters(
        soup,
        "https://example.com/index.html",
        Mock()
    )
    
    # Should only have 2 chapters, not 3
    assert len(chapters) == 2
    assert chapters[0].title == "Chapter 1"
    assert chapters[1].title == "Chapter 2"


def test_multi_page_strategy_filters_navigation_links():
    """Test that MultiPageStrategy filters out index.html and external links."""
    html = """
    <html><body><div class="b">
        <p><a href="01.html">Chapter 1</a></p>
        <p><a href="index.html">Back to index</a></p>
        <p><a href="http://external.com/page.html">External link</a></p>
        <p><a href="02.html">Chapter 2</a></p>
    </div></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    strategy = MultiPageStrategy()
    
    chapters, _ = strategy.extract_chapters(
        soup,
        "https://example.com/index.html",
        Mock()
    )
    
    # Should only have chapters 1 and 2
    assert len(chapters) == 2
    assert chapters[0].title == "Chapter 1"
    assert chapters[1].title == "Chapter 2"


# ============================================================================
# Tests: SinglePageAnchorStrategy
# ============================================================================

def test_single_page_anchor_strategy_extracts_chapters(
    single_page_anchor_toc_html,
    single_page_content_html
):
    """Test that SinglePageAnchorStrategy correctly extracts chapters."""
    soup = BeautifulSoup(single_page_anchor_toc_html, "lxml")
    strategy = SinglePageAnchorStrategy()
    
    # Mock fetch function to return single page content
    mock_fetch = Mock(return_value=(single_page_content_html, "utf-8"))
    
    chapters, seen_urls = strategy.extract_chapters(
        soup,
        "https://example.com/index.html",
        mock_fetch
    )
    
    # Verify fetch was called once for text.html
    mock_fetch.assert_called_once_with("https://example.com/text.html")
    
    # Verify correct number of chapters
    assert len(chapters) == 4
    
    # Verify chapter details
    assert chapters[0].number == 1
    assert chapters[0].title == "Предисловие"
    assert chapters[0].url == "https://example.com/text.html#01"
    assert chapters[0].content  # Content should be extracted
    
    assert chapters[1].number == 2
    assert chapters[1].title == "Часть первая"
    
    # Verify content extraction
    assert "Это текст предисловия" in chapters[0].content
    assert "Первый параграф части первой" in chapters[1].content
    assert "Первый параграф части второй" in chapters[2].content
    
    # Verify seen_urls contains only text.html
    assert len(seen_urls) == 1
    assert "text.html" in list(seen_urls)[0]


def test_single_page_anchor_strategy_handles_missing_anchors(
    single_page_anchor_toc_html
):
    """Test that SinglePageAnchorStrategy handles missing anchors gracefully."""
    soup = BeautifulSoup(single_page_anchor_toc_html, "lxml")
    strategy = SinglePageAnchorStrategy()
    
    # Mock content with missing anchor #03
    incomplete_html = """
    <html><body><div class="b">
        <a name="01"></a><p>Content 1</p>
        <a name="02"></a><p>Content 2</p>
        <a name="04"></a><p>Content 4</p>
    </div></body></html>
    """
    mock_fetch = Mock(return_value=(incomplete_html, "utf-8"))
    
    chapters, _ = strategy.extract_chapters(
        soup,
        "https://example.com/index.html",
        mock_fetch
    )
    
    # Should only extract chapters with found anchors
    assert len(chapters) == 3  # #01, #02, #04 (missing #03)


def test_single_page_anchor_strategy_extracts_between_anchors(
    single_page_content_html
):
    """Test content extraction between anchor tags."""
    strategy = SinglePageAnchorStrategy()
    soup = BeautifulSoup(single_page_content_html, "lxml")
    
    start_anchor = soup.find("a", {"name": "02"})
    end_anchor = soup.find("a", {"name": "03"})
    
    content = strategy._extract_between_anchors(start_anchor, end_anchor, soup)
    
    # Should contain content between anchors
    assert "Часть первая" in content
    assert "Первый параграф части первой" in content
    assert "Второй параграф части первой" in content
    
    # Should NOT contain content from next section
    assert "Первый параграф части второй" not in content


def test_single_page_anchor_strategy_cleans_paragraphs():
    """Test that paragraph cleaning removes markers and normalizes whitespace."""
    strategy = SinglePageAnchorStrategy()
    
    # Test footnote marker removal
    text = "Some text with [5] page marker and {3} footnote"
    cleaned = strategy._clean_paragraph(text)
    assert "[5]" not in cleaned
    assert "{3}" not in cleaned
    
    # Test whitespace normalization
    text = "Multiple    spaces   and\n\nnewlines"
    cleaned = strategy._clean_paragraph(text)
    assert "  " not in cleaned  # No double spaces


def test_single_page_anchor_strategy_handles_no_anchors():
    """Test handling of ToC with no anchor links."""
    html = """
    <html><body><div class="b">
        <p><a href="page1.html">Page 1</a></p>
    </div></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    strategy = SinglePageAnchorStrategy()
    
    chapters, seen_urls = strategy.extract_chapters(
        soup,
        "https://example.com/index.html",
        Mock()
    )
    
    # Should return empty list
    assert len(chapters) == 0
    assert len(seen_urls) == 0


# ============================================================================
# Tests: Edge Cases
# ============================================================================

def test_multi_page_strategy_handles_empty_toc():
    """Test MultiPageStrategy with empty ToC."""
    html = "<html><body><div class='b'></div></body></html>"
    soup = BeautifulSoup(html, "lxml")
    strategy = MultiPageStrategy()
    
    chapters, seen_urls = strategy.extract_chapters(
        soup,
        "https://example.com/index.html",
        Mock()
    )
    
    assert len(chapters) == 0
    assert len(seen_urls) == 0


def test_multi_page_strategy_handles_no_content_div():
    """Test MultiPageStrategy when content div is missing."""
    html = "<html><body></body></html>"
    soup = BeautifulSoup(html, "lxml")
    strategy = MultiPageStrategy()
    
    chapters, seen_urls = strategy.extract_chapters(
        soup,
        "https://example.com/index.html",
        Mock()
    )
    
    assert len(chapters) == 0


def test_single_page_anchor_last_chapter_to_end():
    """Test that last chapter content extends to end of document."""
    html_content = """
    <html><body><div class="b">
        <a name="01"></a><p>Chapter 1</p>
        <a name="02"></a>
        <p>Chapter 2 paragraph 1</p>
        <p>Chapter 2 paragraph 2</p>
        <p>Chapter 2 final paragraph</p>
    </div></body></html>
    """
    
    toc = """<html><body><div class="b">
        <p><a href="text.html#01">Chapter 1</a></p>
        <p><a href="text.html#02">Chapter 2</a></p>
    </div></body></html>"""
    
    soup_toc = BeautifulSoup(toc, "lxml")
    strategy = SinglePageAnchorStrategy()
    
    mock_fetch = Mock(return_value=(html_content, "utf-8"))
    
    chapters, _ = strategy.extract_chapters(
        soup_toc,
        "https://example.com/index.html",
        mock_fetch
    )
    
    # Last chapter should include all remaining content
    assert "Chapter 2 final paragraph" in chapters[1].content


# ============================================================================
# Integration-style Tests
# ============================================================================

def test_full_workflow_multi_page(multi_page_toc_html):
    """Integration test: Detect multi-page and extract chapters."""
    soup = BeautifulSoup(multi_page_toc_html, "lxml")
    
    # Auto-detect
    strategy = detect_book_structure(soup)
    assert isinstance(strategy, MultiPageStrategy)
    
    # Extract
    chapters, urls = strategy.extract_chapters(
        soup,
        "https://militera.lib.ru/memo/russian/grigorenko/index.html",
        Mock()
    )
    
    assert len(chapters) == 5
    assert all(ch.url.endswith(".html") and "#" not in ch.url for ch in chapters)


def test_full_workflow_single_page_anchor(
    single_page_anchor_toc_html,
    single_page_content_html
):
    """Integration test: Detect single-page anchor and extract chapters."""
    soup = BeautifulSoup(single_page_anchor_toc_html, "lxml")
    
    # Auto-detect
    strategy = detect_book_structure(soup)
    assert isinstance(strategy, SinglePageAnchorStrategy)
    
    # Extract
    mock_fetch = Mock(return_value=(single_page_content_html, "utf-8"))
    chapters, urls = strategy.extract_chapters(
        soup,
        "https://militera.lib.ru/memo/german/speer_a/index.html",
        mock_fetch
    )
    
    assert len(chapters) == 4
    assert all("#" in ch.url for ch in chapters)
    assert all(ch.content for ch in chapters)  # All should have content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
