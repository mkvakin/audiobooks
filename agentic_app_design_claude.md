# Agentic Book-to-Audio Application: Claude Analysis

*Analysis by Claude Opus | December 31, 2024*

## The Question

> "What tools do we need to turn [book extraction + audio conversion] into an agentic software that can be stored in git, deployed by others, work correctly, and allow processing other books by sending their TOC URL?"

---

## My Assessment: Three Possible Approaches

### Approach 1: "Workflow as Code" (Recommended for Your Case)

**What it means**: Build a traditional Python application with explicit control flow, containerized for portability.

**Why I recommend this**:
- Your problem is *deterministic*. Given a URL, the steps are always: fetch → decode → clean → synthesize → merge.
- "Agentic" AI (loops of LLM reasoning) adds latency and cost for a problem that doesn't require creativity.
- Legacy encoding (Windows-1251) and binary tools (ffmpeg) require precise control that LLMs struggle with.

**Stack**:
| Component | Tool | Rationale |
|-----------|------|-----------|
| Scraping | **Playwright** | Handles JS rendering, legacy encodings, cookies |
| Audio | **GCP TTS API** | Already working in your scripts |
| Merging | **FFmpeg** (CLI) | Industry standard, lossless concat |
| Container | **Docker** | Bundles ffmpeg + Python + Playwright |
| Deployment | **GCP Cloud Run Jobs** | Long timeout (60min), pay-per-use, scales to zero |
| IaC | **Terraform** | Your team already uses it |

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                        Cloud Run Job                        │
│  ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌────────────┐ │
│  │ Scraper │ → │ Cleaner  │ → │ TTS API │ → │ FFmpeg     │ │
│  │ (PW)    │   │ (regex)  │   │ (batch) │   │ (merge)    │ │
│  └─────────┘   └──────────┘   └─────────┘   └────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ↓
                      Cloud Storage Bucket
                       (final MP3 files)
```

---

### Approach 2: "LLM-Powered Agent" (For Generic Sites)

**What it means**: Use an LLM to *discover* site structure dynamically.

**When to use this**:
- You want the app to work on *any* book website, not just militera.lib.ru.
- Site structures vary wildly (some use JS navigation, some have nested frames).

**Stack additions**:
| Component | Tool | Rationale |
|-----------|------|-----------|
| Agent Framework | **LangGraph** or **CrewAI** | Stateful workflows with retry logic |
| LLM | **Gemini 1.5 Flash** | Cheap, 1M token context (can ingest entire HTML pages) |
| Prompt | "Extract the CSS selector for chapter links from this HTML" | Dynamic discovery |

**Trade-off**: Adds ~$0.01-0.05 per book in LLM costs, plus latency. Only worth it for true multi-site flexibility.

---

### Approach 3: "Managed Agents" (Lowest Effort, Highest Lock-in)

**GCP-specific options**:

1. **Vertex AI Agent Builder**: 
   - Drag-and-drop agent creation.
   - ❌ *Not suitable* for this use case. It's designed for conversational RAG, not batch processing pipelines with binary tools.

2. **Cloud Workflows + Cloud Functions**:
   - Orchestrate steps declaratively (YAML).
   - ✅ Could work: `[Trigger] → [Function: Scrape] → [Function: TTS] → [Function: Merge]`
   - ⚠️ Cold start latency; 9-minute timeout per function (merge could exceed this).

3. **Batch on GKE**:
   - Kubernetes Jobs with large resource allocations.
   - Overkill for this volume.

---

## My Recommendation

**For your specific situation**, I recommend **Approach 1** with one optional LLM enhancement:

```
Phase 1: Containerized Pipeline (Approach 1)
├── Dockerize existing scripts (1-2 hours)
├── Deploy to Cloud Run Jobs
├── Trigger via HTTP or Pub/Sub
└── Output to GCS bucket

Phase 2 (Optional): Add LLM Site Discovery
├── If you want to support other book sites
├── Add a "site analyzer" step using Gemini
└── Store discovered selectors in a JSON config cache
```

---

## Key Files to Create

1. **`Dockerfile`**
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg
RUN pip install playwright google-cloud-texttospeech
RUN playwright install chromium
COPY . /app
WORKDIR /app
ENTRYPOINT ["python", "main.py"]
```

2. **`main.py`** (Simplified)
```python
def process_book(toc_url: str, output_bucket: str):
    chapters = scrape_toc(toc_url)  # Returns list of chapter URLs
    for chapter in chapters:
        text = extract_text(chapter)  # Handles encoding
        text = clean_markdown(text)   # Strip ##, **, etc.
        audio = synthesize(text)      # GCP TTS
        upload(audio, output_bucket)
    merge_all(output_bucket)          # FFmpeg
```

3. **`infra/cloudrun.tf`**
```hcl
resource "google_cloud_run_v2_job" "book_processor" {
  name     = "book-to-audio"
  location = "us-central1"
  
  template {
    containers {
      image = "gcr.io/${var.project}/book-processor:latest"
      resources {
        limits = { memory = "2Gi", cpu = "2" }
      }
    }
    timeout = "3600s"  # 60 minutes
  }
}
```

---

## Comparison Table: Gemini vs Claude Recommendations

| Aspect | Gemini 3 Analysis | Claude Opus Analysis |
|--------|-------------------|---------------------|
| Core framework | LangGraph (agent-first) | Plain Python (script-first, optional agent) |
| Orchestration | LangGraph state machine | Simple procedural code or Cloud Workflows |
| LLM usage | Central (for site analysis) | Optional (only if multi-site support needed) |
| Complexity | Higher (learning curve) | Lower (uses patterns you already know) |
| Flexibility | Higher for unknown sites | Lower but sufficient for known sites |

---

## Bottom Line

If militera.lib.ru is the primary (or only) target, **keep it simple**: Dockerize → Cloud Run → Done.

If you want a "universal book extractor" that works on any site, then the LangGraph approach makes sense—but that's a larger investment.

Would you like me to scaffold the repository structure for Approach 1?
