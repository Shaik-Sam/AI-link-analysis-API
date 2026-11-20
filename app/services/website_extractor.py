import asyncio
import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.config import Settings
from app.errors import AppError
from app.utils.validators import validate_url

REDIRECT_CODES = {301, 302, 303, 307, 308}
ALLOWED_TYPES = ("text/html", "application/xhtml", "text/plain")
NOISE_TAGS = ("script", "style", "noscript", "svg", "iframe", "canvas", "template", "form", "button", "select", "video", "audio", "picture")
NOISE_ATTR = re.compile(r"cookie|consent|gdpr|popup|newsletter-modal", re.I)
NOISE_CONTAINERS = {"div", "section", "aside", "dialog", "ul"}
PAGE_HINT = re.compile(r"(about|service|product|solution|offering|what-we-do|capabilit|pricing|platform|industr)", re.I)
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|docx?|xlsx?)$", re.I)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LinkAnalysisBot/1.0)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "en;q=0.9",
}


@dataclass
class ExtractedSite:
    url: str
    final_url: str
    pages: list[str]
    title: str
    meta_description: str
    site_name: str
    language: str
    content: str
    truncated: bool


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def host_key(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def meta_content(soup: BeautifulSoup, key: str, attr: str = "name") -> str:
    tag = soup.find("meta", attrs={attr: key})
    return clean(str(tag.get("content", ""))) if tag else ""


def extract_json_ld(soup: BeautifulSoup) -> list[str]:
    items: list[str] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        if isinstance(data, dict):
            nodes = data.get("@graph", [data])
        elif isinstance(data, list):
            nodes = data
        else:
            continue
        for node in nodes:
            if isinstance(node, dict) and node.get("name"):
                label = clean(str(node.get("@type", "")))
                description = clean(str(node.get("description", "")))[:200]
                items.append(f"{label}: {clean(str(node['name']))} {description}".strip())
    return items[:5]


def candidate_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    base_host = host_key(base_url)
    base_path = urlsplit(base_url).path.rstrip("/")
    seen: set[str] = set()
    found: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href).split("#")[0]
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or host_key(absolute) != base_host:
            continue
        if SKIP_EXT.search(parts.path) or not PAGE_HINT.search(parts.path):
            continue
        path = parts.path.rstrip("/")
        if path in seen or path == base_path:
            continue
        seen.add(path)
        found.append(absolute)
    return found


def parse_page(content: bytes, base_url: str) -> dict:
    soup = BeautifulSoup(content, "html.parser")
    title = clean(soup.title.get_text()) if soup.title else ""
    description = meta_content(soup, "description") or meta_content(soup, "og:description", "property")
    site_name = meta_content(soup, "og:site_name", "property")
    language = str(soup.html.get("lang", "")) if soup.html else ""
    structured = extract_json_ld(soup)
    links = candidate_links(soup, base_url)

    nav_items: list[str] = []
    for nav in soup.find_all("nav"):
        for anchor in nav.find_all("a"):
            text = clean(anchor.get_text())
            if 2 <= len(text) <= 40 and text not in nav_items:
                nav_items.append(text)

    headings: list[str] = []
    for heading in soup.find_all(["h1", "h2", "h3"]):
        text = clean(heading.get_text())[:160]
        if text and text not in headings:
            headings.append(text)

    for tag in soup(NOISE_TAGS + ("nav",)):
        tag.decompose()
    for element in soup.find_all(["div", "section", "aside", "dialog", "ul"]):
        if getattr(element, "decomposed", False) or element.name not in NOISE_CONTAINERS:
            continue
        marker = " ".join(element.get("class", [])) + " " + str(element.get("id", ""))
        if NOISE_ATTR.search(marker):
            element.decompose()

    lines = []
    for raw_line in soup.get_text("\n").splitlines():
        text = clean(raw_line)
        if len(text) >= 3 and re.search(r"\w", text):
            lines.append(text)

    return {
        "title": title,
        "description": description,
        "site_name": site_name,
        "language": language,
        "structured": structured,
        "links": links,
        "nav": nav_items[:30],
        "headings": headings[:40],
        "lines": lines,
    }


def build_block(url: str, data: dict, seen: set[str], budget: int) -> tuple[str, bool]:
    parts = [f"URL: {url}"]
    if data["title"]:
        parts.append(f"Title: {data['title']}")
    if data["description"]:
        parts.append(f"Meta description: {data['description']}")
    if data["site_name"]:
        parts.append(f"Site name: {data['site_name']}")
    if data["structured"]:
        parts.append("Structured data: " + " | ".join(data["structured"]))
    if data["nav"]:
        parts.append("Navigation: " + ", ".join(data["nav"]))
    if data["headings"]:
        parts.append("Headings: " + " | ".join(data["headings"]))
    used = sum(len(part) + 1 for part in parts)
    truncated = False
    body: list[str] = []
    for line in data["lines"]:
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        if used + len(line) + 1 > budget:
            truncated = True
            break
        body.append(line)
        used += len(line) + 1
    if body:
        parts.append("Text:\n" + "\n".join(body))
    return "\n".join(parts), truncated


class WebsiteExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def extract(self, url: str) -> ExtractedSite:
        timeout = httpx.Timeout(self.settings.fetch_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, headers=HEADERS, follow_redirects=False) as client:
            final_url, content = await self._fetch(client, url)
            main = parse_page(content, final_url)
            extra_urls = main["links"][: self.settings.max_extra_pages]
            results = await asyncio.gather(*(self._fetch(client, item) for item in extra_urls), return_exceptions=True)

        extras = []
        for item, result in zip(extra_urls, results):
            if isinstance(result, BaseException):
                continue
            extras.append((result[0], parse_page(result[1], result[0])))

        main_chars = sum(len(line) for line in main["lines"])
        if main_chars < 80 and not extras:
            raise AppError(
                "insufficient_content",
                "The page has too little readable text. It may be rendered with JavaScript or blocked for bots.",
                422,
            )

        total = self.settings.max_content_chars
        main_budget = int(total * 0.6) if extras else total
        extra_budget = int(total * 0.4 / len(extras)) if extras else 0
        seen: set[str] = set()
        blocks: list[str] = []
        block, truncated = build_block(final_url, main, seen, main_budget)
        blocks.append(block)
        for page_url, data in extras:
            block, cut = build_block(page_url, data, seen, extra_budget)
            blocks.append(block)
            truncated = truncated or cut

        return ExtractedSite(
            url=url,
            final_url=final_url,
            pages=[final_url] + [page_url for page_url, _ in extras],
            title=main["title"],
            meta_description=main["description"],
            site_name=main["site_name"],
            language=main["language"],
            content="\n\n".join(blocks),
            truncated=truncated,
        )

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> tuple[str, bytes]:
        current = url
        for _ in range(self.settings.max_redirects + 1):
            current = await validate_url(current)
            try:
                async with client.stream("GET", current) as response:
                    if response.status_code in REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise AppError("website_fetch_failed", "The website sent a redirect without a location.", 502)
                        current = urljoin(current, location)
                        continue
                    self._check_status(response.status_code)
                    self._check_type(response.headers.get("content-type", ""))
                    return current, await self._read(response)
            except httpx.TimeoutException:
                raise AppError("website_timeout", "The website took too long to respond.", 504)
            except httpx.HTTPError:
                raise AppError("website_unreachable", "The website could not be reached.", 502)
        raise AppError("too_many_redirects", "The website redirected too many times.", 502)

    @staticmethod
    def _check_status(status: int) -> None:
        if 200 <= status < 300:
            return
        if status in (401, 403):
            raise AppError("website_access_restricted", f"The website refused automated access (HTTP {status}).", 502)
        if status == 404:
            raise AppError("website_not_found", "The URL returned HTTP 404 (not found).", 502)
        if status == 429:
            raise AppError("website_rate_limited", "The website is rate limiting requests (HTTP 429).", 502)
        if status >= 500:
            raise AppError("website_server_error", f"The website returned a server error (HTTP {status}).", 502)
        raise AppError("website_fetch_failed", f"The website returned HTTP {status}.", 502)

    @staticmethod
    def _check_type(content_type: str) -> None:
        value = content_type.lower()
        if value and not any(kind in value for kind in ALLOWED_TYPES):
            raise AppError("unsupported_content_type", f"Content type '{value.split(';')[0]}' is not supported.", 422)

    async def _read(self, response: httpx.Response) -> bytes:
        limit = self.settings.max_response_bytes
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            remaining = limit - size
            if remaining <= 0:
                break
            chunks.append(chunk[:remaining])
            size += len(chunk[:remaining])
        return b"".join(chunks)
