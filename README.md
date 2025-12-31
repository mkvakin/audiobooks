# Audiobook Pipeline

Convert books from militera.lib.ru to audiobooks using Google Cloud Text-to-Speech.

## Features

- **Automated Book Extraction**: Scrapes book content from militera.lib.ru handling Windows-1251 encoding
- **Text Cleaning**: Removes markdown, HTML artifacts, and page markers for clean TTS input
- **Google Cloud TTS**: High-quality Russian voice synthesis (Wavenet voices)
- **Sequential Processing**: Processes chapters one at a time for reliability
- **Resumable Operations**: Automatically resumes from where it left off if interrupted
- **Atomic File Operations**: Uses temporary files to prevent corruption during crashes
- **Audio Merging**: Uses FFmpeg to merge chapter parts into single files

## Prerequisites

1. **Python 3.10+**
2. **FFmpeg**: Required for audio merging
   ```bash
   # macOS
   brew install ffmpeg
   
   # Ubuntu/Debian
   sudo apt-get install ffmpeg
   ```
3. **Google Cloud Account**: With Text-to-Speech API enabled
4. **GCP Authentication**:
   ```bash
   gcloud auth application-default login
   ```

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/audiobooks.git
cd audiobooks

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Convert a Book to Audiobook

```bash
python -m app.main "http://militera.lib.ru/memo/russian/slaschov_ya/index.html"
```

**Resume Capability**: If the process is interrupted (Ctrl+C, crash, network issue), simply run the same command again. The pipeline will:
- Skip chapters that are already completed (final MP3 exists)
- Resume synthesis from the next incomplete chapter
- Clean up any partial/corrupted files from the interruption

### Force Reprocess All Chapters

```bash
python -m app.main --force "http://militera.lib.ru/memo/russian/slaschov_ya/index.html"
```

Use `--force` to reprocess the entire book even if chapter MP3 files already exist.

### Extract Text Only (No Audio)

```bash
python -m app.main --extract-only "http://militera.lib.ru/memo/russian/slaschov_ya/index.html"
```

### Merge Existing Part Files

```bash
python -m app.main --merge-only
```

### Options

```
--extract-only    Only extract text, skip audio synthesis
--force           Force reprocess even if chapter MP3 already exists
--output-dir, -o  Output directory (default: audiobook)
--voice           Google TTS voice (default: ru-RU-Wavenet-B)
--verbose, -v     Enable verbose logging
```

**Note**: `--merge-only` flag is deprecated. The new pipeline processes chapters sequentially (TTS + merge together).

## Output Structure

```
audiobook/
├── Author_BookTitle/                 # Book-specific directory
│   ├── chapter_01_Title.mp3          # Final merged chapter files
│   ├── chapter_02_Title.mp3
│   ├── ...
│   ├── parts/                         # TTS chunks (cleaned up after merge)
│   │   └── (empty after successful processing)
│   └── text/                          # Extracted text for reference
│       ├── chapter_01_raw.txt
│       ├── chapter_01_clean.txt
│       └── ...
```

**Sequential Processing**: Each chapter is fully completed (TTS + merge + cleanup) before moving to the next. Part files are automatically cleaned up after successful merge.

## Configuration

Edit `app/core/config.py` to customize:

- TTS voice settings (voice name, speaking rate, pitch)
- Scraper settings (encoding, retries, timeouts)
- Output directory structure

## Available Russian Voices

- `ru-RU-Wavenet-A` - Female
- `ru-RU-Wavenet-B` - Male (default)
- `ru-RU-Wavenet-C` - Female
- `ru-RU-Wavenet-D` - Male
- `ru-RU-Wavenet-E` - Female

## Troubleshooting

### Resuming After Interruption

If the process is interrupted:

1. **Just re-run the same command** - the pipeline will automatically resume
2. Completed chapters (with valid final MP3) are skipped
3. Any partial/corrupted files are cleaned up automatically

```bash
# If interrupted during chapter 5, just run again:
python -m app.main "http://militera.lib.ru/memo/russian/slaschov_ya/index.html"
# Output: "Chapter 1-4: Already completed, skipping" → continues from chapter 5
```

### Authentication Errors

```bash
gcloud auth application-default login
```

### Encoding Issues

The scraper automatically handles Windows-1251 encoding used by militera.lib.ru. If you see garbled text, check the `text/` output directory for diagnostic files.

### FFmpeg Not Found

Ensure FFmpeg is installed and in your PATH:
```bash
ffmpeg -version
```

## License

MIT License
