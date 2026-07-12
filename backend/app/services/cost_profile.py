"""Cost profile helpers for reversible API-cost optimizations."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.runtime_config import get_runtime_config

QUALITY_CURRENT = "quality_current"
BALANCED_COST = "balanced_cost"
AGGRESSIVE_COST = "aggressive_cost"
VALID_COST_PROFILES = {QUALITY_CURRENT, BALANCED_COST, AGGRESSIVE_COST}
RAG_CHUNK_FILTER_AUTO = "auto"
RAG_CHUNK_FILTER_ALWAYS = "always"
RAG_CHUNK_FILTER_OFF = "off"
VALID_RAG_CHUNK_FILTER_MODES = {
    RAG_CHUNK_FILTER_AUTO,
    RAG_CHUNK_FILTER_ALWAYS,
    RAG_CHUNK_FILTER_OFF,
}


def get_cost_profile(advanced_config: dict[str, Any] | None = None) -> str:
    """Return the active API cost profile, falling back to quality-current."""
    value = None
    if advanced_config and "API_COST_PROFILE" in advanced_config:
        value = advanced_config["API_COST_PROFILE"]
    if value is None:
        try:
            value = get_runtime_config("API_COST_PROFILE", required=False)
        except Exception:
            value = None
    profile = str(value or getattr(settings, "API_COST_PROFILE", QUALITY_CURRENT)).strip()
    return profile if profile in VALID_COST_PROFILES else QUALITY_CURRENT


def use_balanced_or_aggressive(advanced_config: dict[str, Any] | None = None) -> bool:
    return get_cost_profile(advanced_config) in {BALANCED_COST, AGGRESSIVE_COST}


def use_balanced_cost(advanced_config: dict[str, Any] | None = None) -> bool:
    return get_cost_profile(advanced_config) == BALANCED_COST


def auxiliary_chat_model(
    *,
    cheap_model: str,
    premium_model: str,
    advanced_config: dict[str, Any] | None = None,
) -> str:
    """Use cheap model for auxiliary tasks only outside quality-current."""
    return cheap_model if use_balanced_or_aggressive(advanced_config) else premium_model


def should_skip_context_evaluator_when_sufficient(
    advanced_config: dict[str, Any] | None = None,
) -> bool:
    return use_balanced_or_aggressive(advanced_config)


def should_reuse_ingestion_query_expansion(
    advanced_config: dict[str, Any] | None = None,
) -> bool:
    return use_balanced_or_aggressive(advanced_config)


def get_rag_chunk_llm_filter_mode(
    advanced_config: dict[str, Any] | None = None,
    explicit_mode: str | None = None,
) -> str:
    """
    Return the effective Retriever LLM chunk-filter mode.

    The registry default is "auto". For quality_current, auto preserves the old
    always-classify behavior; for balanced_cost it checks only borderline chunks;
    for aggressive_cost it maps to off.
    """
    raw = explicit_mode
    if raw is None and advanced_config and "RAG_CHUNK_LLM_FILTER_MODE" in advanced_config:
        raw = advanced_config["RAG_CHUNK_LLM_FILTER_MODE"]
    if raw is None:
        try:
            raw = get_runtime_config("RAG_CHUNK_LLM_FILTER_MODE", required=False)
        except Exception:
            raw = None

    mode = str(raw or getattr(settings, "RAG_CHUNK_LLM_FILTER_MODE", RAG_CHUNK_FILTER_AUTO)).strip()
    if mode not in VALID_RAG_CHUNK_FILTER_MODES:
        mode = RAG_CHUNK_FILTER_AUTO

    profile = get_cost_profile(advanced_config)
    if mode == RAG_CHUNK_FILTER_AUTO:
        if profile == QUALITY_CURRENT:
            return RAG_CHUNK_FILTER_ALWAYS
        if profile == AGGRESSIVE_COST:
            return RAG_CHUNK_FILTER_OFF
    return mode
