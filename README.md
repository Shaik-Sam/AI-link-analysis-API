# AI Link Analysis API

A FastAPI service that fetches a website, extracts its content, and uses an LLM to produce five structured analysis sections: competitor comparison, top 5 search queries, SEO improvements, top 5 services and target audience.

## Features

- `POST /link-analysis` returns one validated JSON document with all five sections.
- Multi-provider LLM layer (Anthropic, OpenAI, Gemini) over plain HTTPX, with automatic retry on invalid JSON and cross-provider fallback.
- Content extraction with BeautifulSoup: title, meta tags, JSON-LD, navigation, headings and cleaned body text, plus up to two same-site pages such as About or Services.
- Token control: boilerplate removed, duplicate lines dropped across pages, content capped at `MAX_CONTENT_CHARS`, one LLM call per analysis.
- SSRF protection: scheme and port allow-list, DNS resolution with public-IP check, redirects followed manually and re-validated at every hop, response size cap, content-type check.
- Honest data labelling: competitors are marked `ai_generated_suggestion`, services are marked `website` or `inferred`, and `search_volume` is always `null` because no data source is integrated.
- In-memory TTL cache, structured error envelope, secrets read from environment variables only.

## Project structure

```
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
├── Dockerfile
├── render.yaml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md
```

## Setup

Requires Python 3.10 or newer.

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and set at least one API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GEMINI_API_KEY`). Never commit `.env`.

## Run

```
uvicorn app.main:app --host 0.0.0.0 --port 4000
```

- API: `http://localhost:4000/link-analysis`
- Interactive docs: `http://localhost:4000/docs`
- Health check: `http://localhost:4000/health`

Docker:

```
docker build -t ai-link-analysis .
docker run -p 4000:4000 --env-file .env ai-link-analysis
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | Primary provider: `anthropic`, `openai` or `gemini` |
| `LLM_MODEL` | `claude-haiku-5-5` | Primary model id |
| `FALLBACK_PROVIDER` / `FALLBACK_MODEL` | `openai` / `gpt-6-luna` | Used when the primary fails; skipped if its key is missing |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | empty | Provider credentials |
| `MAX_CONTENT_CHARS` | `12000` | Cap on extracted text sent to the LLM |
| `MAX_EXTRA_PAGES` | `2` | Extra same-site pages to read (About, Services, Products) |
| `CACHE_TTL_SECONDS` | `3600` | Result cache lifetime, `0` disables caching |
| `LLM_MAX_OUTPUT_TOKENS` | `4096` | Output ceiling per call |
| `FETCH_TIMEOUT_SECONDS` | `15` | Per-page fetch timeout |

## API

### Request

```
curl -X POST http://localhost:4000/link-analysis \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

Optional field: `"refresh": true` bypasses the cache.

### Response shape

The sample below is an abbreviated, illustrative response for a fictional site. It shows the structure, not a captured live result.

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
        {"name": "Webflow", "is_your_brand": false, "main_service": "No-code web design", "target_market": "Designers and agencies", "key_strength": "Visual builder", "opportunity": "Offer done-for-you service"}
      ],
      "note": "Competitors are AI-generated suggestions..."
    },
    "target_search_queries": [
      {
        "query": "web design for small business",
        "platforms": ["Google", "LinkedIn"],
        "intent": "Service Search",
        "business_relevance": "Matches the core offer",
        "target_audience": "Small business owners",
        "search_volume": null
      }
    ],
    "seo_improvements": {
      "primary_keyword": "web design for small business",
      "secondary_keywords": ["small business websites"],
      "long_tail_keywords": ["affordable web design for startups"],
      "business_keywords": ["web agency"],
      "recommended_title": "Web Design for Small Business | Acme Web Studio",
      "title_structure": "Primary keyword | Brand",
      "title_length": 47,
      "meta_description": "Acme builds fast, affordable websites for small businesses and startups.",
      "meta_description_keywords": ["web design", "small business"],
      "meta_description_length": 72,
      "supporting_content": {
        "service_landing_pages": [],
        "industry_pages": [],
        "faqs": ["How much does a website cost?"],
        "blog_topics": [],
        "location_pages": [],
        "supporting_articles": []
      },
      "current_title": "Acme Web Studio",
      "current_meta_description": ""
    },
    "top_services": [
      {
        "name": "Web design",
        "description": "Custom websites for small businesses.",
        "target_industry": "Retail",
        "target_customer": "Small business owners",
        "main_benefit": "Win more online customers",
        "source": "website"
      }
    ],
    "target_audience": {
      "primary_audience": ["Small business owners"],
      "secondary_audience": ["Startups"],
      "industries": ["Retail"],
      "business_types": ["Local services"],
      "customer_profiles": [{"profile": "Owner-operator", "description": "Needs a site without hiring staff"}],
      "geographic_focus": "Not stated on the website",
      "customer_needs": ["An online presence"],
      "challenges": ["Limited budget"],
      "interests": ["Local SEO"],
      "recommended_segments": [{"segment": "Startups", "business_type": "SaaS", "requirement": "Marketing website"}]
    }
  },
  "meta": {
    "provider": "anthropic",
    "model": "claude-haiku-5-5",
    "cached": false,
    "pages_analyzed": ["https://acme.example/"],
    "content_chars": 9200,
    "content_truncated": false,
    "input_tokens": 4500,
    "output_tokens": 2200,
    "estimated_cost_usd": 0.00155,
    "elapsed_ms": 14000,
    "notes": ["Competitors are AI-generated suggestions and are not verified against live market data."]
  }
}
```

The arrays above are shortened; a real response contains exactly 5 search queries and exactly 5 services.

### Errors

Every error uses the same envelope: `{"success": false, "error": {"code": "...", "message": "..."}}`.

| HTTP | Codes | Meaning |
|---|---|---|
| 400 | `invalid_url`, `invalid_scheme`, `blocked_port`, `blocked_address`, `unresolvable_host` | Bad input or SSRF protection triggered |
| 422 | `validation_error`, `insufficient_content`, `unsupported_content_type` | Bad body, JavaScript-only page, or non-HTML target |
| 502 | `website_access_restricted`, `website_not_found`, `website_server_error`, `website_unreachable`, `llm_error`, `llm_auth_error`, `llm_invalid_output` | Upstream website or LLM failure |
| 503 | `llm_not_configured`, `llm_rate_limited` | No API key or provider quota reached |
| 504 | `website_timeout`, `llm_timeout` | Upstream timeout |

Captured output from the running server is in `docs/api-error-handling-log.txt`. The test run is in `docs/test-run.log`.

## Tests

```
pip install -r requirements-dev.txt
pytest
```

40 tests cover URL validation, SSRF blocking, HTML extraction, schema validation, retry on invalid JSON, caching, competitor de-duplication and the HTTP contract. The LLM and the website fetcher are replaced with fakes, so no API key or network is needed.

## Security notes

- API keys are read from environment variables and are never logged or returned.
- Only `http` and `https` on ports 80, 443, 8080 and 8443 are accepted. Credentials in URLs are rejected.
- Every hostname is resolved and all returned addresses must be globally routable. Loopback, private, link-local, carrier-grade NAT, multicast and reserved ranges are blocked, including IPv4-mapped IPv6 and numeric host forms such as `2130706433`.
- Redirects are followed manually and each hop is validated again.
- Residual risk: validation and connection use separate DNS lookups, so a DNS-rebinding attack is theoretically possible. Production deployments should add an egress firewall that blocks internal ranges.
- Page content is treated as untrusted data in the prompt to reduce prompt injection.

## LLM platform research

### Methodology and limits

Prices were collected on 20 November 2026 from provider pricing pages as mirrored by pricing trackers and launch coverage. Re-check the official pages before relying on them: Anthropic (`platform.claude.com/docs/en/about-claude/pricing`), OpenAI (`developers.openai.com/api/docs/pricing`), Google (`ai.google.dev/gemini-api/docs/pricing`). Gemini figures differed between sources, and Google lists introductory prices that change on 1 December 2026, so confirm the model id and rate before deploying.

No accuracy or latency benchmark was run for this task. Every speed and accuracy statement below is an estimate or a vendor-level claim, and is labelled as such. `scripts/benchmark.py` measures real latency, token use and cost per model; run it with your own keys and paste the results into the table at the end of this section.

### A. Comparison

| Provider | Model | Input / output per 1M tokens | Context | JSON support | Speed | Accuracy for this task |
|---|---|---|---|---|---|---|
| Anthropic | Claude Haiku 5.5 | $0.10 / $0.50 (prompts up to 100K; $0.50 / $2.50 above) | 1M | Prompted JSON plus validation and retry (implemented here) | Estimate: fast tier | Not measured |
| OpenAI | GPT-6 Luna | $0.10 / $0.50 | about 1.05M | Native `json_object` mode | Estimate: fast tier | Not measured |
| Google | Gemini 3.5 Flash-Lite | $0.30 / $2.50 | 1M | Native `responseMimeType` JSON | Estimate: fast tier | Not measured |
| Anthropic | Claude Sonnet 5.5 | $2.00 / $10.00 | 1M | Prompted JSON plus validation and retry | Estimate: slower, mid tier | Not measured, expected higher on nuanced competitor reasoning |
| OpenAI | GPT-6 Sol | $2.00 / $10.00 | about 1.05M | Native `json_object` mode | Estimate: slower, mid tier | Not measured |

Published vendor benchmarks for these models focus on coding and computer-use tasks. They do not measure website understanding, competitor naming or SEO quality, so they are not used to rank the models here.

### B. Selection criteria

| Requirement | How it is handled |
|---|---|
| Accuracy | Grounding rules in the prompt, validation of the five sections, retry with the validation error, optional escalation to a larger model |
| Speed | One call per analysis, small input, small-tier model, cache for repeats |
| Cost | Cheapest tier of each vendor, trimmed content, no duplicate calls |
| Reliable JSON | Pydantic validation, single retry with feedback, cross-provider fallback |
| Large pages | 1M context is far more than the 12,000 character cap, so large sites never hit limits |

### C. Cost optimisation

- Strip scripts, styles, navigation, cookie banners and forms before the LLM sees the page.
- Remove duplicate lines across pages so repeated headers and footers are sent once.
- Cap content at 12,000 characters and read at most two extra pages, weighted 60 / 40 towards the main page.
- Keep the prompt schema compact and make a single call for all five sections instead of five calls.
- Use a small tier model for the default path. Escalate to a larger model only if validation fails twice or quality demands it.
- Cache results per normalised URL for one hour. A cache hit costs nothing.
- Use provider batch endpoints (half price at the time of research) for bulk, non-interactive runs. Prompt caching has little effect here because the shared system prompt is only about 1,300 tokens.
- Watch the Haiku 5.5 long-prompt price step above 100K tokens. This application stays near 5K, so it never applies.

### D. Final recommendation

| Item | Value |
|---|---|
| Recommended provider | Anthropic |
| Recommended model | `claude-haiku-5-5` |
| Estimated input tokens | about 4,500 (about 1,300 prompt and schema, about 3,000 content, remainder framing) |
| Estimated output tokens | about 2,200 |
| Estimated cost per analysis | about $0.0016 (4,500 x $0.10 + 2,200 x $0.50, per million) |
| Expected response time | Estimate, not measured: 1 to 4 s fetching plus roughly 8 to 25 s generating, so about 10 to 30 s. Cache hits take milliseconds |
| Fallback model | `gpt-6-luna`, same price, different vendor, so it survives a Claude outage or rate limit |
| Premium option | `claude-sonnet-5-5` at about $0.031 per analysis for hard cases |

Estimated cost per analysis at the same token volume:

| Model | Cost per analysis |
|---|---|
| Claude Haiku 5.5 | $0.00155 |
| GPT-6 Luna | $0.00155 |
| Gemini 3.5 Flash-Lite | $0.00685 |
| Claude Sonnet 5.5 | $0.031 |

Reasoning: the two cheapest small-tier models tie on price, and both are 4 to 20 times cheaper than the alternatives. Haiku 5.5 is the default because it keeps the main path and the fallback on different vendors, and the validation and retry layer compensates for the lack of a native JSON mode. This is a provisional choice. Because the provider is an environment variable, switching to Luna or Gemini needs no code change if the benchmark below favours them.

Balancing approach: run the small model by default, validate strictly, retry once with the validation error, fall back to the second vendor, and reserve Sonnet 5.5 for premium or failed requests.

### Measured results

Fill this table by running:

| provider | model | url | ok | seconds | in tokens | out tokens | cost USD | competitors |
|---|---|---|---|---|---|---|---|---|
| gemini | gemini-3.5-flash-lite | https://www.python.org | True | 8.18 | 3423 | 2528 | 0.007347 | 3 |
| gemini | gemini-3.5-flash-lite | https://example.com | True | 9.31 | 1934 | 3044 | 0.00819 | 2 |

Measured on 20 November 2026 with gemini-3.5-flash-lite on [https://www.python.org](https://www.python.org) (8.18s end to end, 3,423 input tokens, 2,528 output tokens, ~$0.0073) and [https://example.com](https://example.com) (9.31s end to end, 1,934 input tokens, 3,044 output tokens, ~$0.0082). Claude Haiku 5.5 and GPT-6 Luna were not benchmarked because no API credit was available, so their speed and accuracy remain estimates.

## Deployment

The repository includes a `Dockerfile` and a `render.yaml` blueprint.

1. Push the repository to GitHub (public, no `.env`).
2. In Render, choose New, then Blueprint, and select the repository.
3. Set `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` in the dashboard.
4. After deployment verify `https://YOUR-APP.onrender.com/health` and `https://YOUR-APP.onrender.com/docs`.

Railway and Fly.io work with the same Dockerfile. The container honours the platform `PORT` variable and defaults to 4000.
#   A I - l i n k - a n a l y s i s - A P I  
 