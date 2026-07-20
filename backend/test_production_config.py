from __future__ import annotations

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from app.config import Settings


def _valid_production_settings(**overrides):
    values = {
        "ENVIRONMENT": "production",
        "FRONTEND_URL": "https://demo.test",
        "BACKEND_URL": "https://demo.test",
        "GOOGLE_REDIRECT_URI": "https://demo.test/api/v1/auth/google/callback",
        "CORS_ORIGINS": "https://demo.test",
        "SECRET_KEY": "a-production-secret-that-is-longer-than-32-characters",
        "MYSQL_PASSWORD": "db-password-with-special@characters",
        "OPENAI_API_KEY": "openai-test-key",
        "GOOGLE_CLIENT_ID": "google-client-id",
        "GOOGLE_CLIENT_SECRET": "google-client-secret",
        "SMTP_USER": "smtp-user",
        "SMTP_PASSWORD": "smtp-password",
        "EMAIL_FROM": "demo@demo.test",
        "SEPAY_ACCOUNT_NUMBER": "demo-account",
        "EMBEDDING_PROVIDER": "openai",
        "SERVER_TASK_MAX_WORKERS": 1,
        "DEFAULT_ADMIN_ENABLED": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_production_settings_keep_single_task_worker_and_domain_cors() -> None:
    settings = _valid_production_settings()

    assert settings.SERVER_TASK_MAX_WORKERS == 1
    assert settings.ALLOWED_CORS_ORIGINS == ["https://demo.test"]
    assert "db-password-with-special%40characters" in settings.DATABASE_URL


def test_railway_mysql_url_is_normalized_for_sqlalchemy() -> None:
    settings = _valid_production_settings(
        MYSQL_URL="mysql://user:secret@mysql.railway.internal:3306/railway",
        MYSQL_PASSWORD="",
        MYSQL_PORT="",
    )

    assert settings.MYSQL_PORT == 3306
    assert settings.DATABASE_URL == (
        "mysql+pymysql://user:secret@mysql.railway.internal:3306/railway"
    )


def test_railway_two_user_profile_allows_two_workers_with_per_job_chroma() -> None:
    settings = _valid_production_settings(
        SERVER_TASK_MAX_WORKERS=2,
        CHROMA_MODE="local_per_job",
        GENERATION_GLOBAL_CONCURRENCY=2,
        GENERATION_PER_USER_CONCURRENCY=1,
    )

    assert settings.SERVER_TASK_MAX_WORKERS == 2
    assert settings.CHROMA_MODE == "local_per_job"


def test_native_railway_mysql_variables_are_supported() -> None:
    settings = _valid_production_settings(
        MYSQL_PASSWORD="",
        MYSQLHOST="mysql.railway.internal",
        MYSQLPORT="3306",
        MYSQLUSER="root",
        MYSQLPASSWORD="secret@value",
        MYSQLDATABASE="railway",
    )

    assert settings.DATABASE_URL == (
        "mysql+pymysql://root:secret%40value@mysql.railway.internal:3306/railway"
    )


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"SECRET_KEY": "short"}, "SECRET_KEY"),
        ({"SERVER_TASK_MAX_WORKERS": 2, "CHROMA_MODE": "local_shared"}, "SERVER_TASK_MAX_WORKERS"),
        ({"FRONTEND_URL": "http://localhost:5173"}, "FRONTEND_URL"),
        ({"CORS_ORIGINS": "http://localhost:5173"}, "CORS_ORIGINS"),
        ({"EMBEDDING_PROVIDER": "local"}, "EMBEDDING_PROVIDER"),
        ({"SECRET_KEY": "REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS"}, "SECRET_KEY"),
        ({"MYSQL_PASSWORD": "REPLACE_WITH_DATABASE_PASSWORD"}, "MYSQL_PASSWORD"),
    ],
)
def test_invalid_production_settings_fail_fast(override, expected) -> None:
    with pytest.raises(ValidationError, match=expected):
        _valid_production_settings(**override)


def test_development_cors_defaults_remain_unchanged() -> None:
    settings = Settings(_env_file=None, ENVIRONMENT="development", CORS_ORIGINS="")
    assert "http://localhost:5173" in settings.ALLOWED_CORS_ORIGINS


def test_redis_url_supports_managed_service_credentials() -> None:
    managed_url = "redis://default:secret@redis.railway.internal:6379"
    settings = Settings(_env_file=None, REDIS_URL=managed_url)
    assert settings.REDIS_CONNECTION_URL == managed_url


def test_redis_url_falls_back_to_host_and_port() -> None:
    settings = Settings(
        _env_file=None,
        REDIS_URL="",
        REDIS_HOST="redis",
        REDIS_PORT=6380,
    )
    assert settings.REDIS_CONNECTION_URL == "redis://redis:6380/0"


def test_openai_rate_limit_settings_are_admin_configurable() -> None:
    from app.config_registry import PARAMETER_GROUPS, get_admin_registry

    registry = get_admin_registry()

    assert "rate_limits" in PARAMETER_GROUPS
    assert "deployment" in PARAMETER_GROUPS
    assert "CHROMA_MODE" in registry
    assert registry["CHROMA_MODE"]["group"] == "deployment"
    assert "GENERATION_GLOBAL_CONCURRENCY" in registry
    assert registry["GENERATION_GLOBAL_CONCURRENCY"]["group"] == "deployment"
    assert "OPENAI_API_KEYS" in registry
    assert registry["OPENAI_API_KEYS"]["group"] == "api_keys"
    assert registry["OPENAI_API_KEYS"]["sensitive"] is True
    assert registry["OPENAI_API_KEYS"]["multiline"] is True
    assert "SERPER_API_KEYS" in registry
    assert registry["SERPER_API_KEYS"]["multiline"] is True
    assert "OPENAI_RATE_LIMIT_ENABLED" in registry
    assert registry["OPENAI_RATE_LIMIT_ENABLED"]["group"] == "rate_limits"
    assert "OPENAI_CHAT_MIN_INTERVAL_SECONDS" in registry
    assert "OPENAI_IMAGE_MIN_INTERVAL_SECONDS" in registry
    assert "WIKIMEDIA_RATE_LIMIT_ENABLED" in registry
    assert registry["WIKIMEDIA_RATE_LIMIT_ENABLED"]["group"] == "rate_limits"
    assert "WIKIMEDIA_SEARCH_MIN_INTERVAL_SECONDS" in registry
    assert "WIKIMEDIA_DOWNLOAD_MIN_INTERVAL_SECONDS" in registry


def test_deployment_profile_detector_classifies_common_profiles(monkeypatch) -> None:
    from app.services import deployment_profile

    monkeypatch.setattr(deployment_profile.settings, "SERVER_TASK_MAX_WORKERS", 1)
    monkeypatch.setattr(deployment_profile.settings, "GENERATION_GLOBAL_CONCURRENCY", 1)
    monkeypatch.setattr(deployment_profile.settings, "GENERATION_PER_USER_CONCURRENCY", 1)
    monkeypatch.setattr(deployment_profile.settings, "CHROMA_MODE", "local_shared")
    assert deployment_profile.detect_deployment_profile()["key"] == "small_safe"

    monkeypatch.setattr(deployment_profile.settings, "SERVER_TASK_MAX_WORKERS", 2)
    monkeypatch.setattr(deployment_profile.settings, "GENERATION_GLOBAL_CONCURRENCY", 2)
    monkeypatch.setattr(deployment_profile.settings, "CHROMA_MODE", "local_per_job")
    assert deployment_profile.detect_deployment_profile()["key"] == "railway_test_2"

    monkeypatch.setattr(deployment_profile.settings, "CHROMA_MODE", "local_shared")
    assert deployment_profile.detect_deployment_profile()["key"] == "misconfigured"

    monkeypatch.setattr(deployment_profile.settings, "SERVER_TASK_MAX_WORKERS", 5)
    monkeypatch.setattr(deployment_profile.settings, "GENERATION_GLOBAL_CONCURRENCY", 5)
    monkeypatch.setattr(deployment_profile.settings, "CHROMA_MODE", "http")
    assert deployment_profile.detect_deployment_profile()["key"] == "medium_ready"


def test_runtime_api_key_override_helper_prefers_explicit_override(monkeypatch) -> None:
    from app.services import runtime_config

    monkeypatch.setattr(
        runtime_config,
        "get_runtime_config",
        lambda key, required=False: "admin-openai-key",
    )

    assert (
        runtime_config.get_api_key_with_overrides(
            "OPENAI_API_KEY",
            {"OPENAI_API_KEY": "user-openai-key"},
        )
        == "user-openai-key"
    )
    assert (
        runtime_config.get_api_key_with_overrides(
            "OPENAI_API_KEY",
            {"OPENAI_API_KEY": runtime_config.MASKED_VALUE},
        )
        == "admin-openai-key"
    )


def test_runtime_api_key_pool_is_used_when_single_key_is_missing(monkeypatch) -> None:
    from app.services import runtime_config

    values = {
        "OPENAI_API_KEYS": "openai-a\nopenai-b",
        "OPENAI_API_KEY": "",
    }

    monkeypatch.setattr(
        runtime_config,
        "get_runtime_config",
        lambda key, required=False: values.get(key, ""),
    )
    monkeypatch.setattr(runtime_config, "_get_pool_redis_client", lambda: None)
    runtime_config._local_pool_indexes.clear()

    assert runtime_config.get_api_key("OPENAI_API_KEY") == "openai-a"
    assert runtime_config.get_api_key("OPENAI_API_KEY") == "openai-b"


def test_system_credit_mode_accepts_openai_key_pool_without_single_key() -> None:
    settings = _valid_production_settings(
        TEXTBOOK_GENERATION_MODE="system_credit_billing",
        OPENAI_API_KEY="",
        OPENAI_API_KEYS="openai-a,openai-b",
    )

    assert settings.OPENAI_API_KEY == ""
    assert settings.OPENAI_API_KEYS == "openai-a,openai-b"


def test_chroma_per_job_cleanup_stays_inside_runs_dir(tmp_path, monkeypatch) -> None:
    from app.services import chroma_runtime

    runs_dir = tmp_path / "runs"
    inside = runs_dir / "textbook_1_1"
    outside = tmp_path / "outside"
    inside.mkdir(parents=True)
    outside.mkdir()

    values = {
        "CHROMA_MODE": "local_per_job",
        "CHROMA_RUNS_DIR": str(runs_dir),
    }
    monkeypatch.setattr(
        chroma_runtime,
        "get_runtime_config",
        lambda key, required=False: values.get(key, ""),
    )

    assert chroma_runtime.cleanup_rag_persist_dir(str(outside)) is False
    assert outside.exists()
    assert chroma_runtime.cleanup_rag_persist_dir(str(inside)) is True
    assert not inside.exists()


def test_content_level_word_targets_are_configurable() -> None:
    from app.config_registry import get_admin_registry

    registry = get_admin_registry()

    for key in (
        "CONTENT_LEVEL_SHORT_MIN_WORDS",
        "CONTENT_LEVEL_SHORT_MAX_WORDS",
        "CONTENT_LEVEL_MEDIUM_MIN_WORDS",
        "CONTENT_LEVEL_MEDIUM_MAX_WORDS",
        "CONTENT_LEVEL_LONG_MIN_WORDS",
        "CONTENT_LEVEL_LONG_MAX_WORDS",
        "CONTENT_LEVEL_VERY_LONG_MIN_WORDS",
        "CONTENT_LEVEL_VERY_LONG_MAX_WORDS",
    ):
        assert key in registry
        assert registry[key]["group"] == "generation"
        assert registry[key]["type"] == "int"

    for key in (
        "CONTENT_WORD_TO_CHAR_RATIO_VI",
        "CONTENT_WORD_TO_CHAR_RATIO_EN",
    ):
        assert key in registry
        assert registry[key]["group"] == "generation"
        assert registry[key]["type"] == "float"


def test_production_rejects_sample_default_admin() -> None:
    with pytest.raises(ValidationError, match="DEFAULT_ADMIN_EMAIL"):
        _valid_production_settings(
            DEFAULT_ADMIN_ENABLED=True,
            DEFAULT_ADMIN_EMAIL="demo-admin@example.com",
            DEFAULT_ADMIN_PASSWORD_HASH="$2b$12$abcdefghijklmnopqrstuu12345678901234567890123456789",
        )


def test_existing_public_routes_are_preserved() -> None:
    from app.main import app

    routes = {
        (method, getattr(route, "path", ""))
        for route in app.routes
        for method in (getattr(route, "methods", set()) or {"MOUNT"})
    }
    expected_routes = {
        ("POST", "/api/v1/auth/register"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/textbooks/"),
        ("GET", "/api/v1/textbooks/{textbook_id}"),
        ("POST", "/api/v1/textbooks/{textbook_id}/confirm-curriculum"),
        ("GET", "/api/v1/textbooks/{textbook_id}/progress"),
        ("POST", "/api/v1/textbooks/{textbook_id}/stop"),
        ("GET", "/api/v1/admin/stats/overview"),
        ("GET", "/api/v1/admin/textbooks"),
        ("MOUNT", "/outputs"),
    }

    assert expected_routes <= routes


def test_publisher_font_falls_back_for_a_worker_with_stale_settings(monkeypatch) -> None:
    from types import SimpleNamespace
    from app.services.textbook import publisher

    monkeypatch.setattr(publisher, "settings", SimpleNamespace())
    assert publisher._document_font() == "Times New Roman"


def test_alembic_history_has_a_fresh_database_baseline() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))

    baseline = scripts.get_revision("initial_schema")
    first_incremental = scripts.get_revision("1353ebcf0cd0")
    assert baseline is not None and baseline.down_revision is None
    assert first_incremental is not None and first_incremental.down_revision == "initial_schema"
