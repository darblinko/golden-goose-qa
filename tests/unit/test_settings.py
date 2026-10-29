import math

import pytest
from gg_common.settings import (
    AppSettings,
    PostgresSettings,
    ProviderSettings,
    effective_settings_summary,
)


def test_postgres_defaults_and_urls():
    pg = PostgresSettings()
    assert pg.dsn == "postgresql://gg_app:gg_app_dev_password@localhost:5432/goldengoose"
    assert pg.sqlalchemy_url.startswith("postgresql+psycopg://gg_app:")
    assert pg.admin_sqlalchemy_url.startswith("postgresql+psycopg://gg_admin:")


def test_env_override(monkeypatch):
    monkeypatch.setenv("GG_PG_HOST", "db.internal")
    monkeypatch.setenv("GG_PG_PORT", "6543")
    pg = PostgresSettings()
    assert pg.host == "db.internal"
    assert pg.port == 6543


def test_provider_settings_defaults():
    providers = ProviderSettings()
    assert providers.llm_model == "claude-sonnet-5"
    assert providers.embedding_dimensions == 1024
    assert providers.require_real_providers is False
    assert providers.anthropic_api_key is None


def test_summary_masks_secrets(monkeypatch):
    monkeypatch.setenv("GG_ANTHROPIC_API_KEY", "sk-super-secret")
    settings = AppSettings()
    summary = effective_settings_summary(settings)
    flat = str(summary)
    assert "sk-super-secret" not in flat
    assert "gg_app_dev_password" not in flat
    assert math.isfinite(summary["api_port"])  # sanity: plain values survive


def test_nested_settings_load_dotenv(monkeypatch, tmp_path):
    # A nested section (postgres) reads `.env` from the working directory, not
    # just os.environ — the regression this guards is that GG_PG_* in `.env`
    # used to be silently ignored because each nested model was env-only.
    (tmp_path / ".env").write_text("GG_PG_HOST=dotenv.internal\nGG_PG_PORT=6001\n")
    monkeypatch.chdir(tmp_path)
    pg = PostgresSettings()
    assert pg.host == "dotenv.internal"
    assert pg.port == 6001


def test_prod_rejects_default_dev_secrets(monkeypatch, tmp_path):
    # Deployed environments must not run on the shipped dev secrets; with none
    # overridden, construction fails closed and names the offenders.
    monkeypatch.chdir(tmp_path)  # isolate from any real repo-root `.env`
    with pytest.raises(ValueError) as exc:
        AppSettings(environment="prod")
    message = str(exc.value)
    assert "auth_jwt_secret" in message
    assert "postgres.password" in message
    assert "neo4j.password" in message
    assert "objectstore.secret_key" in message


def test_prod_accepts_overridden_secrets(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in (
        "GG_AUTH_JWT_SECRET",
        "GG_PG_PASSWORD",
        "GG_PG_ADMIN_PASSWORD",
        "GG_NEO4J_PASSWORD",
        "GG_S3_SECRET_KEY",
    ):
        monkeypatch.setenv(name, f"real-{name.lower()}")
    settings = AppSettings(environment="prod")  # must not raise
    assert settings.environment == "prod"


def test_local_keeps_dev_secret_defaults(monkeypatch, tmp_path):
    # Local and CI keep the baked-in defaults so offline dev and tests need no
    # setup — the guard only fires for dev/prod.
    monkeypatch.chdir(tmp_path)
    settings = AppSettings(environment="local")
    assert settings.auth_jwt_secret.get_secret_value() == "dev_only_jwt_secret_change_me_0123456789"
