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
        "GROQ_API_KEY": "groq-test-key",
        "GOOGLE_CLIENT_ID": "google-client-id",
        "GOOGLE_CLIENT_SECRET": "google-client-secret",
        "SMTP_USER": "smtp-user",
        "SMTP_PASSWORD": "smtp-password",
        "EMAIL_FROM": "demo@demo.test",
        "SEPAY_ACCOUNT_NUMBER": "demo-account",
        "EMBEDDING_PROVIDER": "openai",
        "CELERY_CONCURRENCY": 1,
        "DEFAULT_ADMIN_ENABLED": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_production_settings_keep_single_worker_and_domain_cors() -> None:
    settings = _valid_production_settings()

    assert settings.CELERY_CONCURRENCY == 1
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
        ({"CELERY_CONCURRENCY": 2}, "CELERY_CONCURRENCY"),
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
