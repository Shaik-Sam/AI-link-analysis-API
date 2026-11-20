import re
from typing import Optional
from urllib.parse import urlsplit

import asyncio

from app.schemas import ComparisonRow, CompetitorAnalysis
from app.utils.validators import domain_resolves

NOTE = (
    "Competitors are AI-generated suggestions based on the website content and the model's general knowledge. "
    "They are not verified against live market data. domain_resolves only confirms that the domain exists in DNS."
)


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").casefold())


def host_from(website: Optional[str]) -> Optional[str]:
    if not website or not website.strip():
        return None
    value = website.strip()
    if "://" not in value:
        value = "https://" + value
    try:
        host = (urlsplit(value).hostname or "").lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


async def _unknown() -> None:
    return None


class CompetitorService:
    max_competitors = 6

    async def refine(self, brand_name: str, analysis: CompetitorAnalysis, own_host: str) -> CompetitorAnalysis:
        brand_key = normalize_name(brand_name)
        own = own_host[4:] if own_host.startswith("www.") else own_host
        seen: set[str] = set()
        kept = []
        hosts: list[Optional[str]] = []
        for competitor in analysis.competitors:
            key = normalize_name(competitor.name)
            host = host_from(competitor.website)
            if not key or key == brand_key or key in seen or (host and host == own):
                continue
            seen.add(key)
            kept.append(competitor)
            hosts.append(host)
            if len(kept) >= self.max_competitors:
                break

        checks = await asyncio.gather(*(domain_resolves(host) if host else _unknown() for host in hosts))
        refined = []
        for competitor, host, resolves in zip(kept, hosts, checks):
            refined.append(
                competitor.model_copy(
                    update={
                        "website": f"https://{host}" if host else None,
                        "source": "ai_generated_suggestion",
                        "domain_resolves": resolves,
                    }
                )
            )

        rows = [ComparisonRow(name=brand_name, is_your_brand=True, **analysis.your_brand.model_dump())]
        rows.extend(
            ComparisonRow(
                name=item.name,
                is_your_brand=False,
                main_service=item.main_service,
                target_market=item.target_market,
                key_strength=item.key_strength,
                opportunity=item.opportunity,
            )
            for item in refined
        )
        return analysis.model_copy(update={"competitors": refined, "comparison_table": rows, "note": NOTE})
