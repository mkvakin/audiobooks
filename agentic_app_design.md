# Agentic Application Design: Book-to-Audio Pipeline

## objective
Transform ad-hoc scripts into a robust, "Agentic" software application that is:
1.  **Deployable**: Can be easily deployed by others (Docker/Terraform).
2.  **Autonomous**: Can handle different book formats, encodings, and errors without manual intervention.
3.  **Scalable**: hosted on GCP.
4.  **Interface**: triggered by a simple URL input.

## 1. Recommendation: The "Agentic" Stack

To build software that "thinks" (e.g., "Oh, this is Windows-1251 encoding" or "I need to find the Table of Contents"), we shouldn't just write a script; we should build a **Workflow**.

**Suggested Stack:**
*   **Language**: Python 3.11+
*   **Orchestration**: **LangGraph** (by LangChain).
    *   *Why?* It allows defining a "State Graph". If extraction fails, the agent can retry with a different encoding strategy. It separates the "Plan" from the "Execution".
*   **Browser/Scraping**: **Playwright** (Headless).
    *   *Why?* Essential for modern execution and handling complex encodings/JS better than `requests`.
*   **Containerization**: **Docker**.
    *   *Why?* Ensures `ffmpeg` and system dependencies are present everywhere.
*   **Infrastructure**: **GCP Cloud Run** (Job or Service).
    *   *Why?* Serverless. You only pay when processing a book. Zero cost when idle.

## 2. Architecture Overview

```mermaid
graph TD
    User[User / API Trigger] -->|POST /process {url}| API[FastAPI Entrypoint]
    API -->|Start Job| Worker[Cloud Run Job]
    
    subgraph Agent Workflow [LangGraph Application]
        Analysis[Node: Page Analysis]
        Extraction[Node: Content Extraction]
        Validation[Node: Quality Check]
        TTS[Node: Audio Gen & Merge]
        
        Analysis -->|Analyze Structure| Extraction
        Extraction -->|Text Content| Validation
        Validation -- "Garbage Detected?" --> Analysis
        Validation -- "Clean Text" --> TTS
    end
    
    Worker --> Agent Workflow
    TTS -->|Save MP3s| GCS[Google Cloud Storage]
```

## 3. Detailed Component Breakdown

### A. The Agent (Core Logic)
Instead of a linear script, we define nodes:
1.  **`analyzer_node`**: Visits the URL. Uses an LLM (Gemini/GPT) to identify:
    *   Is this a Table of Contents?
    *   What is the CSS selector for chapter links?
2.  **`extractor_node`**: Uses Playwright to download pages based on the Analyzer's plan.
    *   *Self-Correction*: If text looks like "", it retries with different decoding.
3.  **`cleaner_node`**: Uses an LLM or Regex to strip clean text (removing "Back to top", headers).
4.  **`producer_node`**: Batches text to GCP TTS and runs FFmpeg.

### B. Deployment & Infrastructure (Terraform)
We treat the infrastructure as code (IaC) so it's "stored in git and deployable by others".

*   **Artifact Registry**: Stores the Docker image.
*   **Cloud Run**: Runs the container.
*   **Cloud Storage**: Stores the final MP3 files.
*   **Service Account**: Identity with permission to use TTS and write to Storage.

### C. Repository Structure
```text
/
├── app/
│   ├── agent/          # LangGraph logic
│   ├── core/           # Config, Logging
│   ├── services/       # TTS, Scraping wrappers
│   └── main.py         # Entrypoint
├── infra/              # Terraform
│   ├── main.tf
│   └── variables.tf
├── Dockerfile          # Steps to install Python + FFmpeg + Playwright
├── pyproject.toml      # Dependencies
└── README.md           # "How to deploy"
```

## 4. Development Strategy

### Phase 1: Local Containerization (The Foundation)
1.  Create a `Dockerfile` that installs `python`, `ffmpeg`, and `playwright`.
2.  Port your current scripts into a clean Python package structure.
3.  Ensure it runs with `docker run --env-file .env my-agent "http://book-url"`.

### Phase 2: "Agentification" (The Brains)
1.  Integrate **LangGraph**.
2.  Add an **LLM Analysis Step**: Feed the HTML of the first page to an LLM and ask "Return the JSON selector for chapter links".
3.  This makes the tool generic for *any* book site, not just `militera.lib.ru`.

### Phase 3: Cloud Deployment (The Release)
1.  Write Terraform to spin up the GCP Project, Bucket, and Cloud Run Job.
2.  Add GitHub Actions to auto-deploy on push.

## 5. Tools Recommendation

| Category | Tool | Why? |
| :--- | :--- | :--- |
| **Framework** | **LangChain / LangGraph** | Standard for controlling loops and agent state. |
| **Scraping** | **Crawlee (Python)** or **Playwright** | Best-in-class for handling browser-like extraction. |
| **LLM** | **Gemini 1.5 Flash** | Extremely cheap, large context window (perfect for dumping whole HTML pages to analyze). |
| **Hosting** | **GCP Cloud Run** | 60-minute timeout support (audio processing takes time), scale-to-zero. |

## 6. Next Steps for You

1.  **Repo Setup**: Create a proper repository structure (I can generate the scaffold).
2.  **Dockerize**: Create the `Dockerfile` to ensure `ffmpeg` is always available.
3.  **Refactor**: Move logic from "script" to "classes" (e.g., `BookExtractor`, `AudioSynthesizer`).
