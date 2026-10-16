"""Configurable LLM provider adapter (server-side only).

Supported: Anthropic Messages API (tool use for structured output), OpenAI
Chat Completions (JSON schema response format), free local models through
Ollama, and any free OpenAI-compatible endpoint (LLM_BASE_URL). When no provider/key is
configured, `available()` is False and callers use deterministic fallbacks;
the UI reports this state explicitly.

Privacy: callers send schema-level metadata (column names, types, roles) by
default. Sample rows are only included when ALLOW_LLM_SAMPLE_ROWS=1.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from .config import llm_api_key, llm_base_url, settings

log = logging.getLogger("insightforge.llm")

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4.1", "ollama": "llama3.1", "openai_compatible": ""}


class LLMError(RuntimeError):
    pass


def status() -> dict[str, Any]:
    provider = settings.llm_provider
    if provider in ("anthropic", "openai"):
        configured = bool(llm_api_key())
    elif provider == "ollama":
        configured = True  # free local models; reachability is checked on first call
    elif provider == "openai_compatible":
        configured = bool(llm_base_url() and settings.llm_model)
    else:
        configured = False
    return {
        "provider": provider if provider in DEFAULT_MODELS else "none",
        "model": (settings.llm_model or DEFAULT_MODELS.get(provider, "")) if configured else None,
        "configured": configured,
        "message": "LLM provider configured; used for planning and narrative only, never for computing results."
        if configured else "No LLM provider configured. InsightForge uses its deterministic planner and report writer.",
        "sends_sample_rows": settings.allow_external_llm_sample_rows,
    }


def available() -> bool:
    return status()["configured"]


def structured(system: str, prompt: str, schema: dict[str, Any], tool_name: str = "submit", max_tokens: int = 1500) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (parsed_json, usage). Raises LLMError on any failure."""
    if not available():
        raise LLMError("LLM provider not configured")
    provider = settings.llm_provider
    model = settings.llm_model or DEFAULT_MODELS[provider]
    key = llm_api_key()
    t0 = time.perf_counter()
    try:
        if provider == "anthropic":
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": max_tokens, "system": system,
                      "messages": [{"role": "user", "content": prompt}],
                      "tools": [{"name": tool_name, "description": "Submit the structured answer.", "input_schema": schema}],
                      "tool_choice": {"type": "tool", "name": tool_name}},
                timeout=60,
            )
            r.raise_for_status()
            body = r.json()
            block = next((b for b in body.get("content", []) if b.get("type") == "tool_use"), None)
            if not block:
                raise LLMError("model did not return a tool call")
            usage = body.get("usage", {})
            return block["input"], {"provider": provider, "model": model, "input_tokens": usage.get("input_tokens"),
                                    "output_tokens": usage.get("output_tokens"), "latency_ms": int((time.perf_counter() - t0) * 1000)}
        headers = {"content-type": "application/json"}
        if key:
            headers["authorization"] = f"Bearer {key}"
        r = httpx.post(
            f"{llm_base_url()}/chat/completions",
            headers=headers,
            json={"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                  "response_format": {"type": "json_schema", "json_schema": {"name": tool_name, "schema": schema}}},
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        usage = body.get("usage", {})
        return json.loads(body["choices"][0]["message"]["content"]), {
            "provider": provider, "model": model, "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
            "latency_ms": int((time.perf_counter() - t0) * 1000)}
    except LLMError:
        raise
    except httpx.HTTPStatusError as exc:
        # Never log request headers (they contain the key) or dataset content.
        log.warning("LLM call failed with HTTP %s", exc.response.status_code)
        raise LLMError(f"LLM provider returned HTTP {exc.response.status_code}") from None
    except Exception as exc:
        log.warning("LLM call failed: %s", type(exc).__name__)
        raise LLMError(f"LLM call failed ({type(exc).__name__})") from None
