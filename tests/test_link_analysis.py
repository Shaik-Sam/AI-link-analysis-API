import asyncio
import copy
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.errors import AppError
from app.main import app, get_analysis_service
from app.schemas import LLMAnalysis, SearchQuery
from app.services.analysis_service import AnalysisService
from app.services.competitor_service import CompetitorService
from app.services.llm_service import LLMResult, estimate_cost, extract_json
from app.services.website_extractor import ExtractedSite, parse_page
from app.utils.validators import is_public_ip, normalize_url, validate_url

SAMPLE_HTML = b"""
<html lang="en"><head>
<title>Acme Web Studio | Websites for small business</title>
<meta name="description" content="Acme builds fast websites for small businesses.">
<meta property="og:site_name" content="Acme Web Studio">
<script type="application/ld+json">{"@type": "Organization", "name": "Acme Web Studio", "description": "Web agency"}</script>
<script>var secret = "ignore me";</script>
</head><body>
<nav><a href="/services">Services</a><a href="/about">About</a></nav>
<h1>We build websites that win customers</h1>
<p>Custom web design and development for small businesses and startups.</p>
<p>Custom web design and development for small businesses and startups.</p>
<div class="cookie-banner">Accept all cookies</div>
<ul><li>E-commerce stores</li><li>SEO optimisation</li></ul>
<a href="/services/web-design">Web design</a>
<a href="https://other.com/services">External</a>
</body></html>
"""


def sample_payload():
    return {
        "brand": {"name": "Acme Web Studio", "category": "Web Development", "summary": "A web agency for small businesses."},
        "competitor_analysis": {
            "brand_overview": "Acme builds websites for small businesses.",
            "main_category": "Web Development",
            "main_products_services": ["Web design", "E-commerce"],
            "your_brand": {
                "main_service": "Web development",
                "target_market": "Small businesses",
                "key_strength": "Affordable solutions",
                "opportunity": "Improve online visibility",
            },
            "competitors": [
                {"name": "Wix", "website": None, "main_service": "Website builder", "target_market": "DIY users"},
                {"name": "Squarespace", "website": None, "main_service": "Website builder", "target_market": "Creators"},
                {"name": "Webflow", "website": None, "main_service": "No-code design", "target_market": "Designers"},
                {"name": "acme web studio", "website": None, "main_service": "Itself", "target_market": "Itself"},
                {"name": "Wix", "website": None, "main_service": "Duplicate", "target_market": "Duplicate"},
            ],
            "strengths": ["Personal service"],
            "opportunities": ["Publish case studies"],
        },
        "target_search_queries": [
            {"query": "web design for small business", "platforms": ["Google", "Twitter"], "intent": "Service Search"},
            {"query": "affordable website developer", "platforms": ["Facebook"], "intent": "Business Discovery"},
            {"query": "website design ideas", "platforms": ["Instagram"], "intent": "Inspiration"},
            {"query": "web development agency startups", "platforms": ["LinkedIn"], "intent": "B2B Search"},
            {"query": "ecommerce website cost", "platforms": ["Google", "X"], "intent": "Research"},
        ],
        "seo_improvements": {
            "primary_keyword": "web design for small business",
            "secondary_keywords": ["small business websites"],
            "long_tail_keywords": ["affordable web design for startups"],
            "business_keywords": ["web agency"],
            "recommended_title": "Web Design for Small Business | Acme Web Studio",
            "title_structure": "Primary keyword | Brand",
            "meta_description": "Acme builds fast, affordable websites for small businesses and startups.",
            "meta_description_keywords": ["web design", "small business"],
            "supporting_content": {"faqs": ["How much does a website cost?"], "blog_topics": ["Choosing a web agency"]},
        },
        "top_services": [
            {"name": f"Service {i}", "description": "d", "target_industry": "Retail", "target_customer": "SMBs", "main_benefit": "b", "source": "Website" if i < 3 else "guess"}
            for i in range(1, 6)
        ],
        "target_audience": {
            "primary_audience": ["Small business owners"],
            "secondary_audience": ["Startups"],
            "industries": ["Retail"],
            "customer_needs": ["An online presence"],
        },
    }


class FakeExtractor:
    async def extract(self, url):
        return ExtractedSite(
            url=url,
            final_url="https://acme.example/",
            pages=["https://acme.example/"],
            title="Acme Web Studio",
            meta_description="Acme builds websites.",
            site_name="Acme Web Studio",
            language="en",
            content="URL: https://acme.example/\nText:\nWe build websites.",
            truncated=False,
        )


class FakeLLM:
    def __init__(self, replies):
        self.replies = replies
        self.calls = 0

    def targets(self):
        return [("anthropic", "claude-haiku-5-5")]

    async def generate(self, provider, model, system, user):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return LLMResult(text=reply, provider=provider, model=model, input_tokens=4500, output_tokens=2200)


def make_service(replies):
    settings = Settings(_env_file=None, cache_ttl_seconds=60)
    llm = FakeLLM(replies)
    return AnalysisService(settings, FakeExtractor(), llm, CompetitorService()), llm


def test_health():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "url,code",
    [
        ("not a url", "invalid_url"),
        ("ftp://example.com", "invalid_scheme"),
        ("http://user:pass@example.com", "invalid_url"),
        ("http://127.0.0.1", "blocked_address"),
        ("http://localhost", "blocked_address"),
        ("http://169.254.169.254/latest/meta-data", "blocked_address"),
        ("http://10.0.0.5", "blocked_address"),
        ("http://[::1]", "blocked_address"),
        ("http://2130706433", "blocked_address"),
        ("https://example.com:22", "blocked_port"),
    ],
)
def test_bad_urls_return_structured_errors(url, code):
    with TestClient(app) as client:
        response = client.post("/link-analysis", json={"url": url})
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == code


def test_missing_body_is_validation_error():
    with TestClient(app) as client:
        response = client.post("/link-analysis", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_no_api_key_returns_503():
    settings = Settings(_env_file=None)
    from app.services.llm_service import LLMService

    service = AnalysisService(settings, FakeExtractor(), LLMService(settings), CompetitorService())
    app.dependency_overrides[get_analysis_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post("/link-analysis", json={"url": "https://acme.example"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_not_configured"


def test_successful_analysis_over_http():
    service, _ = make_service([json.dumps(sample_payload())])
    app.dependency_overrides[get_analysis_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post("/link-analysis", json={"url": "acme.example"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["brand"]["name"] == "Acme Web Studio"
    analysis = body["analysis"]
    assert set(analysis) == {"competitor_analysis", "target_search_queries", "seo_improvements", "top_services", "target_audience"}
    assert len(analysis["target_search_queries"]) == 5
    assert len(analysis["top_services"]) == 5
    assert body["meta"]["estimated_cost_usd"] == pytest.approx(0.00155, abs=1e-6)


def test_competitors_are_deduplicated_and_labelled():
    service, _ = make_service([json.dumps(sample_payload())])
    result = asyncio.run(service.analyze("https://acme.example"))
    competitors = result.analysis.competitor_analysis.competitors
    assert [c.name for c in competitors] == ["Wix", "Squarespace", "Webflow"]
    assert all(c.source == "ai_generated_suggestion" for c in competitors)
    table = result.analysis.competitor_analysis.comparison_table
    assert table[0].is_your_brand and len(table) == 4


def test_platforms_and_sources_are_normalised():
    result = asyncio.run(make_service([json.dumps(sample_payload())])[0].analyze("https://acme.example"))
    assert result.analysis.target_search_queries[0].platforms == ["Google", "X"]
    assert [s.source for s in result.analysis.top_services] == ["website", "website", "inferred", "inferred", "inferred"]
    assert all(q.search_volume is None for q in result.analysis.target_search_queries)
    assert result.analysis.seo_improvements.title_length == len("Web Design for Small Business | Acme Web Studio")


def test_invalid_json_is_retried_then_succeeds():
    service, llm = make_service(["this is not json", json.dumps(sample_payload())])
    result = asyncio.run(service.analyze("https://acme.example"))
    assert llm.calls == 2
    assert result.meta.input_tokens == 9000


def test_persistent_invalid_output_fails_gracefully():
    service, _ = make_service(["nope"])
    with pytest.raises(AppError) as info:
        asyncio.run(service.analyze("https://acme.example"))
    assert info.value.code == "llm_invalid_output"
    assert info.value.status_code == 502


def test_results_are_cached():
    service, llm = make_service([json.dumps(sample_payload())])

    async def run():
        first = await service.analyze("https://acme.example")
        second = await service.analyze("https://acme.example")
        third = await service.analyze("https://acme.example", refresh=True)
        return first, second, third

    first, second, third = asyncio.run(run())
    assert first.meta.cached is False
    assert second.meta.cached is True
    assert third.meta.cached is False
    assert llm.calls == 2


def test_parse_page_extracts_and_cleans_content():
    data = parse_page(SAMPLE_HTML, "https://acme.example/")
    assert data["title"].startswith("Acme Web Studio")
    assert data["description"] == "Acme builds fast websites for small businesses."
    assert data["site_name"] == "Acme Web Studio"
    assert data["language"] == "en"
    assert data["nav"] == ["Services", "About"]
    assert "We build websites that win customers" in data["headings"]
    text = "\n".join(data["lines"])
    assert "ignore me" not in text
    assert "Accept all cookies" not in text
    assert "E-commerce stores" in text
    assert data["links"] == [
        "https://acme.example/services",
        "https://acme.example/about",
        "https://acme.example/services/web-design",
    ]
    assert data["structured"]


def test_schema_requires_five_queries():
    payload = sample_payload()
    payload["target_search_queries"] = payload["target_search_queries"][:3]
    with pytest.raises(ValidationError):
        LLMAnalysis.model_validate(payload)


def test_unknown_platform_is_rejected():
    with pytest.raises(ValidationError):
        SearchQuery(query="q", platforms=["TikTok"], intent="i")


def test_extract_json_handles_code_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_cost_estimate():
    assert estimate_cost("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.60)
    assert estimate_cost("unknown-model", 10, 10) is None


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_ips_allowed(ip):
    assert is_public_ip(ip)


@pytest.mark.parametrize(
    "ip", ["10.0.0.1", "127.0.0.1", "169.254.169.254", "192.168.1.1", "172.16.0.1", "100.64.0.1", "0.0.0.0", "::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1"]
)
def test_non_public_ips_blocked(ip):
    assert not is_public_ip(ip)


def test_normalize_url_adds_scheme_and_strips_fragment():
    assert normalize_url("Example.com/path#frag") == "https://example.com/path"


def test_validate_url_blocks_loopback():
    with pytest.raises(AppError) as info:
        asyncio.run(validate_url("http://127.0.0.1:8080/admin"))
    assert info.value.code == "blocked_address"
