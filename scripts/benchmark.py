import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.errors import AppError
from app.services.analysis_service import AnalysisService
from app.services.competitor_service import CompetitorService
from app.services.llm_service import LLMService
from app.services.website_extractor import WebsiteExtractor


async def run_one(provider: str, model: str, url: str) -> dict:
    settings = Settings(llm_provider=provider, llm_model=model, fallback_provider=None, fallback_model=None, cache_ttl_seconds=0)
    llm = LLMService(settings)
    service = AnalysisService(settings, WebsiteExtractor(settings), llm, CompetitorService())
    started = time.perf_counter()
    try:
        result = await service.analyze(url, refresh=True)
        row = {
            "provider": provider,
            "model": model,
            "url": url,
            "ok": True,
            "seconds": round(time.perf_counter() - started, 2),
            "input_tokens": result.meta.input_tokens,
            "output_tokens": result.meta.output_tokens,
            "cost_usd": result.meta.estimated_cost_usd,
            "competitors": len(result.analysis.competitor_analysis.competitors),
        }
    except AppError as exc:
        row = {"provider": provider, "model": model, "url": url, "ok": False, "seconds": round(time.perf_counter() - started, 2), "error": exc.code}
    finally:
        await llm.aclose()
    return row


async def main() -> None:
    parser = argparse.ArgumentParser(description="Measure latency, tokens and cost per model.")
    parser.add_argument("--urls", nargs="+", required=True)
    parser.add_argument("--models", nargs="+", required=True, help="provider:model pairs, for example anthropic:claude-haiku-5-5")
    args = parser.parse_args()

    rows = []
    for pair in args.models:
        provider, model = pair.split(":", 1)
        for url in args.urls:
            rows.append(await run_one(provider, model, url))

    print("| provider | model | url | ok | seconds | in tokens | out tokens | cost USD | competitors |")
    print("|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        print(
            f"| {row['provider']} | {row['model']} | {row['url']} | {row['ok']} | {row['seconds']} | "
            f"{row.get('input_tokens', '-')} | {row.get('output_tokens', '-')} | {row.get('cost_usd', '-')} | {row.get('competitors', row.get('error', '-'))} |"
        )


if __name__ == "__main__":
    asyncio.run(main())
