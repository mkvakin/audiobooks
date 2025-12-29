# AI Agent Instruction: Automated Book to Audiobook Pipeline

**Objective**: Extract a book from `militera.lib.ru` (or similar), clean the text of markdown artifacts, convert to audio using Google Cloud TTS, and merge into single chapter files.

**Target Directory**: `operations/`

## Prerequisites
1. **GCP Account**: `pogodin@gmail.com` (User Personal Account)
2. **Tools**: `ffmpeg`, `gcloud`, `python3`
3. **Libraries**: `google-cloud-texttospeech`

---

## Phase 1: Robust Content Extraction (Encoding & Text)

**Problem**: Sites like `militera.lib.ru` use `Windows-1251` encoding which often breaks with standard Python `requests`.
**Solution**: Use a Browser-based extraction approach or strict encoding handling.

**Instruction for Agent**:
1. Navigate to the book's index page.
2. Execute a JavaScript snippet to fetch all chapter links.
3. For each chapter:
   - Fetch content as `Windows-1251` (if identifying Russian legacy site).
   - Extract the *main text body* only (exclude navigation headers/footers).
   - **CRITICAL**: Do NOT save as Markdown for the TTS input. Save as plain text or clean it immediately.
   - If saving as Markdown for readability, create a separate *clean text* version for TTS.

## Phase 2: Content Cleaning (No Markdown for TTS)

**Problem**: TTS engines will pronounce "Hashtag Hashtag Chapter One" if `## Chapter One` is sent.
**Solution**: Sanitize text before sending to GCP API.

**Regex Cleaning Rules**:
- Remove Header Markers: `^#+\s*` -> ``
- Remove Horizontal Rules: `^---` -> ``
- Remove Bold/Italic: `\*\*` or `__` or `\*` -> ``
- Remove Links: `\[([^\]]+)\]\([^\)]+\)` -> `$1` (Keep link text, remove URL)
- Remove Images: `!\[.*\]\(.*\)` -> ``

## Phase 3: Google Cloud TTS Conversion

**Configuration**:
- **Voice**: `ru-RU-Wavenet-B` (Male) or `ru-RU-Wavenet-A` (Female)
- **Format**: MP3
- **Chunking**: Split text on sentence boundaries (`.`, `?`, `!`) to keep chunks under 5000 bytes.

**Script Logic**:
```python
# Pseudo-code for Agent implementation
def clean_text(text):
    # Apply regex rules here to strip markdown
    return plain_text

def synthesize(text_chunk):
    # Call GCP TextToSpeechClient
    # Check for authentication: google.auth.exceptions.DefaultCredentialsError
    # If error -> Stop and ask user to run `gcloud auth application-default login`
```

## Phase 4: Audio Merging

**Problem**: GCP TTS produces many small chunks.
**Solution**: Merge chunks into one file per chapter.

**Instruction**:
1. Check if `ffmpeg` is installed.
2. Group partial files by chapter: `chapter_01_part_01.mp3`, `chapter_01_part_02.mp3`...
3. Generate a concat list text file.
4. Run `ffmpeg -f concat ... -c copy` to merge without re-encoding.
5. Move partial files to a `parts/` subfolder.

## Example Mega-Prompt to Copy/Paste

> "I need to convert the book at [URL] to an audiobook. 
> 1. Use the Browser to extract the content ensuring `Windows-1251` encoding is handled correctly.
> 2. Create a Python script that:
>    - Cleans all Markdown symbols (##, **, etc) so they aren't spoken.
>    - Uses Google Cloud TTS (`ru-RU-Wavenet-B`).
>    - Handles the 5000 byte limit by chunking.
>    - Saves files to `audiobook/parts`.
> 3. Create a merge function using `ffmpeg` to combine parts into single chapter files in `audiobook/`.
> 4. Use my personal GCP account (`pogodin@gmail.com`) for auth."
