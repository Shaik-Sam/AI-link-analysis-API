# AI Link Analysis API

A FastAPI service that fetches a website, extracts its content, and uses an LLM to produce five structured analysis sections: competitor comparison, top 5 search queries, SEO improvements, top 5 services and target audience.

- **Live Demo (Interactive Docs):** https://ai-link-analysis-g1vs.onrender.com/docs
- **API Endpoint:** https://ai-link-analysis-g1vs.onrender.com/link-analysis
- **Health Check:** https://ai-link-analysis-g1vs.onrender.com/health

## Features

- `POST /link-analysis` returns one validated JSON document with all five sections.
- Multi-provider LLM layer (Gemini, Anthropic, OpenAI) over plain HTTPX, with automatic retry on invalid JSON and optional cross-provider fallback.
- Content extraction with BeautifulSoup: title, meta tags, JSON-LD, navigation, headings and cleaned body text, plus up to two same-site pages such as About or Services.
- Token control: boilerplate removed, duplicate lines dropped across pages, content capped at `MAX_CONTENT_CHARS`, one LLM call per analysis.
- SSRF protection: scheme and port allow-list, DNS resolution with public-IP check, redirects followed manually and re-validated at every hop, response size cap, content-type check.
- Honest data labelling: competitors are marked `ai_generated_suggestion`, services are marked `website` or `inferred`, and `search_volume` is always `null` because no data source is integrated.
- In-memory TTL cache, structured error envelope, secrets read from environment variables only.

## Project structure

```text
ai-link-analysis/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── errors.py
│   ├── schemas.py
│   ├── services/
│   │   ├── website_extractor.py
│   │   ├── llm_service.py
│   │   ├── analysis_service.py
│   │   └── competitor_service.py
│   └── utils/
│       ├── validators.py
│       └── cache.py
├── tests/test_link_analysis.py
├── scripts/benchmark.py
├── docs/
│   ├── sample-live-response.json
│   ├── swagger-live-response.png
│   └── server-logs.png
├── Dockerfile
├── render.yaml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md
```

## Setup

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and set your API key (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY`). Never commit `.env`.

## Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 4000
```

- API: `http://localhost:4000/link-analysis`
- Interactive docs: `http://localhost:4000/docs`
- Health check: `http://localhost:4000/health`

Docker:

```bash
docker build -t ai-link-analysis .
docker run -p 4000:4000 --env-file .env ai-link-analysis
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | Primary provider: `gemini`, `anthropic` or `openai` |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | Primary model id |
| `FALLBACK_PROVIDER` / `FALLBACK_MODEL` | empty | Optional secondary provider/model used when primary fails; skipped if empty or key is missing |
| `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | empty | Provider credentials |
| `MAX_CONTENT_CHARS` | `12000` | Cap on extracted text sent to the LLM |
| `MAX_EXTRA_PAGES` | `2` | Extra same-site pages to read (About, Services, Products) |
| `CACHE_TTL_SECONDS` | `3600` | Result cache lifetime, `0` disables caching |
| `LLM_MAX_OUTPUT_TOKENS` | `4096` | Output ceiling per call |
| `FETCH_TIMEOUT_SECONDS` | `15` | Per-page fetch timeout |

## API

### Request

```bash
curl -X POST http://localhost:4000/link-analysis \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

Optional field: `"refresh": true` bypasses the cache.

### Response shape

A full captured live response for `[https://www.python.org](https://www.python.org)` is stored in `docs/sample-live-response.json`. The abbreviated sample below shows the JSON structure:

```json
{
  "success": true,
  "website": "https://acme.example/",
  "brand": {
    "name": "Acme Web Studio",
    "category": "Web Development",
    "summary": "A web agency building websites for small businesses."
  },
  "analysis": {
    "competitor_analysis": {
      "brand_overview": "Acme builds websites for small businesses.",
      "main_category": "Web Development",
      "main_products_services": ["Web design", "E-commerce"],
      "your_brand": {
        "main_service": "Web development",
        "target_market": "Small businesses",
        "key_strength": "Affordable solutions",
        "opportunity": "Improve online visibility"
      },
      "competitors": [
        {
          "name": "Webflow",
          "website": "https://webflow.com",
          "main_service": "No-code web design",
          "target_market": "Designers and agencies",
          "key_strength": "Visual builder",
          "strengths": ["Strong brand"],
          "weaknesses": ["Learning curve"],
          "opportunity": "Offer done-for-you service",
          "source": "ai_generated_suggestion",
          "domain_resolves": true
        }
      ],
      "strengths": ["Personal service"],
      "opportunities": ["Publish case studies"],
      "comparison_table": [
        {"name": "Acme Web Studio", "is_your_brand": true, "main_service": "Web development", "target_market": "Small businesses", "key_strength": "Affordable solutions", "opportunity": "Improve online visibility"},
        {"name": "Webflow", "is_your_brand": false, "main_service": "No-