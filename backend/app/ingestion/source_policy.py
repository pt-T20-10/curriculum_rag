"""Source policy helpers for textbook ingestion.

Centralizes trusted academic source catalogs, user source preferences, and
lightweight URL/domain validation shared by API schemas and ingestion.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlparse


SourceMode = Literal["system_default", "custom_hybrid", "custom_only"]

DEFAULT_SOURCE_MODE: SourceMode = "system_default"
SOURCE_MODES = {"system_default", "custom_hybrid", "custom_only"}
MAX_CUSTOM_URLS = 30
MAX_CUSTOM_DOMAINS = 20

DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)


SOURCE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "en_academic_open_textbooks",
        "label": "English academic open textbooks",
        "group": "english_academic",
        "content_types": ("scholarly", "technical"),
        "domains": (
            "openstax.org",
            "libretexts.org",
            "ocw.mit.edu",
            "mit.edu",
            "stanford.edu",
            "berkeley.edu",
            "cmu.edu",
            "harvard.edu",
            "yale.edu",
            "princeton.edu",
            "cornell.edu",
        ),
    },
    {
        "id": "en_academic_universities",
        "label": "English university and research sources",
        "group": "english_academic",
        "content_types": ("scholarly", "technical"),
        "domains": (
            "washington.edu",
            "uiuc.edu",
            "gatech.edu",
            "utexas.edu",
            "umich.edu",
            "cambridge.org",
            "arxiv.org",
            "nasa.gov",
            "nist.gov",
            "ncbi.nlm.nih.gov",
            "pmc.ncbi.nlm.nih.gov",
        ),
    },
    {
        "id": "en_technical_official_docs",
        "label": "English official technical docs",
        "group": "english_technical",
        "content_types": ("technical",),
        "domains": (
            "docs.python.org",
            "developer.mozilla.org",
            "learn.microsoft.com",
            "kubernetes.io",
            "tensorflow.org",
            "pytorch.org",
            "postgresql.org",
            "mysql.com",
            "w3.org",
        ),
    },
    {
        "id": "vi_academic_universities",
        "label": "Vietnamese academic sources",
        "group": "vietnamese_academic",
        "content_types": ("scholarly", "technical"),
        "domains": (
            ".edu.vn",
            "moet.gov.vn",
            "vnu.edu.vn",
            "hust.edu.vn",
            "hcmut.edu.vn",
            "uit.edu.vn",
            "ptit.edu.vn",
            "ctu.edu.vn",
            "hueuni.edu.vn",
            "udn.vn",
        ),
    },
)


def source_catalog() -> list[dict[str, Any]]:
    """Return a JSON-serializable source catalog for UI/API use."""
    return [
        {
            "id": item["id"],
            "label": item["label"],
            "group": item["group"],
            "content_types": list(item["content_types"]),
            "domains": list(item["domains"]),
        }
        for item in SOURCE_CATALOG
    ]


def normalize_domain(value: str) -> str:
    """Normalize and validate a bare hostname or wildcard-ish academic suffix."""
    domain = str(value or "").strip().lower()
    if not domain:
        raise ValueError("Domain is required")
    if "://" in domain or "/" in domain or "?" in domain or "#" in domain:
        raise ValueError("Domain must be a hostname only")
    domain = domain.removeprefix("www.")
    if domain.startswith("."):
        suffix = domain[1:]
        if not DOMAIN_RE.match(f"example.{suffix}"):
            raise ValueError("Domain suffix is invalid")
        return domain
    if not DOMAIN_RE.match(domain):
        raise ValueError("Domain is invalid")
    return domain


def normalize_url(value: str) -> str:
    """Normalize and validate a direct http(s) URL."""
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must start with http:// or https://")
    return url


def default_source_preferences() -> dict[str, Any]:
    return {
        "source_mode": DEFAULT_SOURCE_MODE,
        "selected_source_ids": [],
        "custom_urls": [],
        "custom_domains": [],
        "reference_style": "none",
        "fallback_policy": "none",
    }


def normalize_source_preferences(value: Any) -> dict[str, Any]:
    """Return a validated source preference dict with stable keys."""
    if value is None:
        return default_source_preferences()
    if not isinstance(value, dict):
        raise ValueError("source_preferences must be an object")

    source_mode = str(value.get("source_mode") or DEFAULT_SOURCE_MODE).strip()
    if source_mode not in SOURCE_MODES:
        raise ValueError("Invalid source_mode")

    valid_source_ids = {item["id"] for item in SOURCE_CATALOG}
    selected_source_ids = []
    for raw_id in value.get("selected_source_ids") or []:
        source_id = str(raw_id or "").strip()
        if not source_id:
            continue
        if source_id not in valid_source_ids:
            raise ValueError(f"Unknown source id: {source_id}")
        if source_id not in selected_source_ids:
            selected_source_ids.append(source_id)

    custom_urls = []
    for raw_url in value.get("custom_urls") or []:
        url = normalize_url(raw_url)
        if url not in custom_urls:
            custom_urls.append(url)
        if len(custom_urls) > MAX_CUSTOM_URLS:
            raise ValueError(f"custom_urls may contain at most {MAX_CUSTOM_URLS} URLs")

    custom_domains = []
    for raw_domain in value.get("custom_domains") or []:
        domain = normalize_domain(raw_domain)
        if domain not in custom_domains:
            custom_domains.append(domain)
        if len(custom_domains) > MAX_CUSTOM_DOMAINS:
            raise ValueError(
                f"custom_domains may contain at most {MAX_CUSTOM_DOMAINS} domains"
            )

    return {
        "source_mode": source_mode,
        "selected_source_ids": selected_source_ids,
        "custom_urls": custom_urls,
        "custom_domains": custom_domains,
        "reference_style": str(value.get("reference_style") or "none").strip()
        if str(value.get("reference_style") or "none").strip() in {"none", "apa_numbered"}
        else "none",
        "fallback_policy": str(value.get("fallback_policy") or "none").strip()
        if str(value.get("fallback_policy") or "none").strip() in {"none", "ask_then_system"}
        else "none",
    }


def _catalog_items_for_content_type(content_type: str) -> list[dict[str, Any]]:
    normalized = str(content_type or "technical").strip().lower()
    return [
        item
        for item in SOURCE_CATALOG
        if normalized in item["content_types"]
    ]


def default_domains_for_content_type(content_type: str) -> tuple[str, ...]:
    """Trusted domains used by default for a content type."""
    domains: list[str] = []
    for item in _catalog_items_for_content_type(content_type):
        for domain in item["domains"]:
            if domain not in domains:
                domains.append(domain)
    return tuple(domains)


def domains_for_source_ids(source_ids: list[str]) -> tuple[str, ...]:
    selected = set(source_ids or [])
    domains: list[str] = []
    for item in SOURCE_CATALOG:
        if item["id"] not in selected:
            continue
        for domain in item["domains"]:
            if domain not in domains:
                domains.append(domain)
    return tuple(domains)


def domains_for_preferences(
    source_preferences: dict[str, Any] | None,
    content_type: str,
    *,
    include_defaults: bool = True,
) -> tuple[str, ...]:
    prefs = normalize_source_preferences(source_preferences)
    domains: list[str] = []
    if include_defaults:
        domains.extend(default_domains_for_content_type(content_type))
    domains.extend(domains_for_source_ids(prefs["selected_source_ids"]))
    domains.extend(prefs["custom_domains"])
    return tuple(dict.fromkeys(domains))


def source_preference_counts(source_preferences: dict[str, Any] | None) -> dict[str, int]:
    prefs = normalize_source_preferences(source_preferences)
    return {
        "selected_source_ids": len(prefs["selected_source_ids"]),
        "custom_urls": len(prefs["custom_urls"]),
        "custom_domains": len(prefs["custom_domains"]),
    }


def domain_matches(domain: str, trusted_domain: str) -> bool:
    """Return True if a hostname matches a configured domain or suffix."""
    host = domain.lower().removeprefix("www.")
    trusted = trusted_domain.lower().removeprefix("www.")
    if trusted.startswith("."):
        return host.endswith(trusted)
    return host == trusted or host.endswith(f".{trusted}")
