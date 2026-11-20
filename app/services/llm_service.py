import json
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import Settings
from app.errors import AppError

PRICING_PER_MILLION = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6-sol": (2.00, 10.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    rates = PRICING_PER_MILLION.get(model)
    if rates is None:
        return None
    return round((input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000, 6)


def extract_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.I)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("The response did not contain a JSON object.")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("The response JSON was not an object.")
    return data


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_timeout_seconds))

    async def aclose(self) -> None:
        await self._client.aclose()

    def targets(self) -> list[tuple[str, str]]:
        candidates = [(self.settings.llm_provider, self.settings.llm_model)]
        if self.settings.fallback_provider and self.settings.fallback_model:
            candidates.append((self.settings.fallback_provider, self.settings.fallback_model))
        chosen: list[tuple[str, str]] = []
        for provider, model in candidates:
            if self.settings.api_key_for(provider) and (provider, model) not in chosen:
                chosen.append((provider, model))
        return chosen

    async def generate(self, provider: str, model: str, system: str, user: str) -> LLMResult:
        key = self.settings.api_key_for(provider)
        if not key:
            raise AppError("llm_not_configured", f"No API key is configured for provider '{provider}'.", 503)
        if provider == "anthropic":
            return await self._anthropic(model, key, system, user)
        if provider == "openai":
            return await self._openai(model, key, system, user)
        if provider == "gemini":
            return await self._gemini(model, key, system, user)
        raise AppError("llm_not_configured", f"Unsupported provider '{provider}'.", 503)

    async def _post(self, provider: str, url: str, headers: dict, payload: dict) -> dict:
        try:
            response = await self._client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise AppError("llm_timeout", f"The {provider} request timed out.", 504)
        except httpx.HTTPError:
            raise AppError("llm_unreachable", f"The {provider} API could not be reached.", 502)
        if response.status_code in (401, 403):
            raise AppError("llm_auth_error", f"{provider} rejected the configured credentials.", 502)
        if response.status_code == 429:
            raise AppError("llm_rate_limited", f"{provider} rate limit or quota reached.", 503)
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                error = body.get("error", body)
                detail = error.get("message", "") if isinstance(error, dict) else str(error)
            except ValueError:
                detail = response.text[:200]
            raise AppError("llm_error", f"{provider} returned HTTP {response.status_code}: {detail[:300]}", 502)
        try:
            return response.json()
        except ValueError:
            raise AppError("llm_error", f"{provider} returned a non-JSON response.", 502)

    @staticmethod
    def _require_text(text: str, provider: str) -> str:
        if not text.strip():
            raise AppError("llm_empty_response", f"{provider} returned an empty response.", 502)
        return text

    async def _anthropic(self, model: str, key: str, system: str, user: str) -> LLMResult:
        data = await self._post(
            "anthropic",
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            {
                "model": model,
                "max_tokens": self.settings.llm_max_output_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        usage = data.get("usage", {})
        return LLMResult(
            self._require_text(text, "anthropic"), "anthropic", model, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        )

    async def _openai(self, model: str, key: str, system: str, user: str) -> LLMResult:
        data = await self._post(
            "openai",
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
                "max_completion_tokens": self.settings.llm_max_output_tokens,
            },
        )
        choices = data.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
        usage = data.get("usage", {})
        return LLMResult(
            self._require_text(text, "openai"), "openai", model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        )

    async def _gemini(self, model: str, key: str, system: str, user: str) -> LLMResult:
        data = await self._post(
            "gemini",
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {"x-goog-api-key": key, "Content-Type": "application/json"},
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": self.settings.llm_max_output_tokens,
                },
            },
        )
        candidates = data.get("candidates") or [{}]
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        usage = data.get("usageMetadata", {})
        output_tokens = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        return LLMResult(
            self._require_text(text, "gemini"), "gemini", model, usage.get("promptTokenCount", 0), output_tokens
        )