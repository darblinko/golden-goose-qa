"""Single source of configuration truth.

Every component receives an injected Settings instance. No module may hardcode a
value that exists here, and no literal default may shadow one, so there is one
configuration source rather than several that can diverge. Call
log_effective_settings() at every process start.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# Loaded by every settings model (not just AppSettings) so a single `.env`
# configures nested sections too: without this, GG_PG_* / GG_NEO4J_* / GG_S3_*
# in `.env` were silently ignored because each nested model was built from
# os.environ only. A missing `.env` is not an error.
_ENV_FILE = ".env"

# Development-only secret defaults, named once so both the field defaults and the
# production guard below reference the same literal. A process running outside
# local/CI that still carries any of these fails closed at startup.
_DEV_PG_PASSWORD = "gg_app_dev_password"
_DEV_PG_ADMIN_PASSWORD = "gg_admin_dev_password"
_DEV_NEO4J_PASSWORD = "gg_neo4j_dev_password"
_DEV_S3_SECRET = "gg_dev_secret"
_DEV_JWT_SECRET = "dev_only_jwt_secret_change_me_0123456789"


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GG_PG_", env_file=_ENV_FILE, extra="ignore")

    host: str = "localhost"
    port: int = 5432
    user: str = "gg_app"
    password: SecretStr = SecretStr(_DEV_PG_PASSWORD)
    database: str = "goldengoose"
    admin_user: str = "gg_admin"
    admin_password: SecretStr = SecretStr(_DEV_PG_ADMIN_PASSWORD)

    def _url(self, drivername: str, user: str, password: SecretStr) -> str:
        # URL.create quotes every component, so a password such as alpha@beta
        # is not split into a password and a host.
        return URL.create(
            drivername,
            username=user,
            password=password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.database,
        ).render_as_string(hide_password=False)

    @property
    def dsn(self) -> str:
        # libpq URI: every component fully percent-encoded (libpq rejects a raw
        # space, which SQLAlchemy's URL rendering leaves in place).
        password = self.password.get_secret_value()
        return (
            f"postgresql://{quote(self.user, safe='')}:{quote(password, safe='')}"
            f"@{self.host}:{self.port}/{quote(self.database, safe='')}"
        )

    @property
    def sqlalchemy_url(self) -> str:
        return self._url("postgresql+psycopg", self.user, self.password)

    @property
    def admin_sqlalchemy_url(self) -> str:
        return self._url("postgresql+psycopg", self.admin_user, self.admin_password)


class QdrantSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GG_QDRANT_", env_file=_ENV_FILE, extra="ignore")

    url: str = "http://localhost:6333"
    api_key: SecretStr | None = None
    collection: str = "gg_chunks"


class Neo4jSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GG_NEO4J_", env_file=_ENV_FILE, extra="ignore")

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: SecretStr = SecretStr(_DEV_NEO4J_PASSWORD)


class ObjectStoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GG_S3_", env_file=_ENV_FILE, extra="ignore")

    endpoint_url: str = "http://localhost:8333"
    access_key: str = "gg_dev_access"
    secret_key: SecretStr = SecretStr(_DEV_S3_SECRET)
    bucket_documents: str = "gg-documents"
    bucket_artifacts: str = "gg-artifacts"
    region: str = "us-east-1"


class ProviderSettings(BaseSettings):
    """Hosted model providers. Fakes are used when a key is absent and
    require_real_providers is False (tests, offline dev)."""

    model_config = SettingsConfigDict(env_prefix="GG_", env_file=_ENV_FILE, extra="ignore")

    anthropic_api_key: SecretStr | None = None
    voyage_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None

    llm_model: str = "claude-sonnet-5"
    llm_small_model: str = "claude-haiku-4-5-20251001"
    embedding_provider: Literal["voyage", "openai", "fake"] = "voyage"
    embedding_model: str = "voyage-4-large"
    embedding_dimensions: int = 1024
    rerank_provider: Literal["voyage", "fake"] = "voyage"
    rerank_model: str = "rerank-2.5"
    ocr_provider: Literal["gemini", "fake"] = "gemini"
    ocr_model: str = "gemini-3-flash"
    require_real_providers: bool = False
    # Hard character ceiling on any single embedding input. A token is at least
    # one character, so an accepted input stays under the model's token context
    # and is never silently truncated; anything larger is rejected, not sent.
    embedding_max_input_chars: int = 32000


class RetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GG_RETRIEVAL_", env_file=_ENV_FILE, extra="ignore"
    )

    prefetch_dense: int = 100
    prefetch_sparse: int = 100
    rerank_in: int = 100
    rerank_out: int = 12
    child_chunk_tokens: int = 350
    parent_chunk_tokens: int = 2000
    # Conservative character ceiling on a child's embed text (context header
    # included). Token counts approximate whitespace words, which understates the
    # embedding model's own tokenizer for dense identifiers and punctuation, so an
    # embedded child is additionally bounded by characters to keep it well under
    # the model's context and rule out silent provider-side truncation.
    max_embed_chars: int = 8000
    # Fixed number of child chunks embedded and upserted per batch at index time.
    # A large document can produce hundreds of children; batching keeps the embed
    # request and the Qdrant upsert bounded in size and peak memory instead of
    # scaling with document size.
    index_batch_size: int = 128
    default_status_filter: str = "effective"
    # Relevance floor applied after rerank: a candidate the reranker scores below
    # this is dropped before it can reach the generator. 0.0 disables the floor
    # (opt-in), so a run with a scoreless fake reranker is unaffected.
    rerank_min_score: float = 0.0
    # Most child chunks of one parent document that may enter the reranker; the
    # highest-fusion children are kept. Stops one large document from flooding
    # the window and starving other relevant documents. 0 disables the cap.
    max_children_per_parent: int = 3

    @model_validator(mode="after")
    def _check_bounds(self) -> "RetrievalSettings":
        """Reject a misconfigured retrieval limit at construction rather than
        mid-retrieval. Sizes that must move real work forward are positive; the
        two opt-out knobs (child cap, score floor) may be zero to disable but
        never negative; and the reranker cannot emit more than it took in."""
        positive = {
            "prefetch_dense": self.prefetch_dense,
            "prefetch_sparse": self.prefetch_sparse,
            "rerank_in": self.rerank_in,
            "rerank_out": self.rerank_out,
            "child_chunk_tokens": self.child_chunk_tokens,
            "parent_chunk_tokens": self.parent_chunk_tokens,
            "max_embed_chars": self.max_embed_chars,
            "index_batch_size": self.index_batch_size,
        }
        non_positive = sorted(name for name, value in positive.items() if value <= 0)
        if non_positive:
            raise ValueError(f"retrieval settings must be positive: {', '.join(non_positive)}")
        if self.max_children_per_parent < 0:
            raise ValueError("max_children_per_parent must be >= 0 (0 disables the cap)")
        if self.rerank_min_score < 0:
            raise ValueError("rerank_min_score must be >= 0 (0 disables the floor)")
        if self.rerank_out > self.rerank_in:
            raise ValueError(
                f"rerank_out ({self.rerank_out}) cannot exceed rerank_in ({self.rerank_in})"
            )
        return self


class ToolSettings(BaseSettings):
    """Limits for the agent-facing structured tools (SQL, graph, file)."""

    model_config = SettingsConfigDict(env_prefix="GG_TOOLS_", env_file=_ENV_FILE, extra="ignore")

    sql_row_limit: int = 200
    sql_timeout_ms: int = 5000
    graph_row_limit: int = 200
    graph_record_hops: int = 3
    file_row_limit: int = 200


class ExternalToolSettings(BaseSettings):
    """External regulatory data tools (openFDA, eCFR, ClinicalTrials.gov,
    PubMed, web search). Public APIs need no key; keys raise rate limits or
    unlock a provider. offline forces the deterministic fake fetcher."""

    model_config = SettingsConfigDict(env_prefix="GG_EXTERNAL_", env_file=_ENV_FILE, extra="ignore")

    offline: bool = False
    result_limit: int = 10
    timeout_seconds: float = 10.0
    cache_ttl_seconds: int = 3600
    min_interval_ms: int = 250
    max_response_bytes: int = 5_000_000
    openfda_api_key: SecretStr | None = None


class TracingSettings(BaseSettings):
    """OTel span export to Arize Phoenix (or any OTLP/HTTP collector).
    Disabled by default; the instrumentation is a no-op until enabled."""

    model_config = SettingsConfigDict(env_prefix="GG_TRACING_", env_file=_ENV_FILE, extra="ignore")

    enabled: bool = False
    endpoint: str = "http://localhost:6006/v1/traces"
    service_name: str = "golden-goose"


class InternalApiSettings(BaseSettings):
    """Read-only connectors to internal business systems (eQMS, ERP, LIMS).
    Connectors are registered purely through configuration — a JSON array of
    declarations, each naming the environment variable that holds its
    credential — so no deployment ever adds one in code."""

    model_config = SettingsConfigDict(env_prefix="GG_INTERNAL_", env_file=_ENV_FILE, extra="ignore")

    connectors_json: str = "[]"
    result_limit: int = 50
    timeout_seconds: float = 10.0
    max_response_bytes: int = 5_000_000


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GG_", env_file=_ENV_FILE, extra="ignore")

    environment: Literal["local", "ci", "dev", "prod"] = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Mount every API route under this prefix. Empty (the default) serves at
    # root, as local compose and the tests expect. Set to "/api" behind a
    # single-origin load balancer that routes /api/* to the API and everything
    # else to the web app, which removes the cross-origin/CORS split.
    api_root_path: str = ""
    auth_jwt_secret: SecretStr = SecretStr(_DEV_JWT_SECRET)
    auth_jwt_issuer: str = "golden-goose-local"
    auth_jwt_audience: str = "golden-goose-api"
    # Path to the FMEA Action Priority table JSON (see gg_common.actionpriority).
    # Unset selects the bundled synthetic example table, which is not the
    # copyrighted AIAG-VDA table; supply that from a licensed copy of the handbook.
    ap_table_path: str | None = None

    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    objectstore: ObjectStoreSettings = Field(default_factory=ObjectStoreSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    external: ExternalToolSettings = Field(default_factory=ExternalToolSettings)
    internal: InternalApiSettings = Field(default_factory=InternalApiSettings)
    tracing: TracingSettings = Field(default_factory=TracingSettings)

    @field_validator("api_root_path")
    @classmethod
    def _normalize_root_path(cls, value: str) -> str:
        """A router prefix must be empty or start with '/' and carry no trailing
        slash (FastAPI's include_router contract). Validate at the boundary so a
        malformed GG_API_ROOT_PATH fails at construction, not at first request."""
        if not value:
            return ""
        if not value.startswith("/"):
            raise ValueError("api_root_path must be empty or start with '/'")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _reject_dev_secrets_in_deployed_envs(self) -> "AppSettings":
        """Deployed environments must not run on the shipped dev secrets. Local
        and CI keep the defaults so tests and offline dev need no setup; dev and
        prod fail closed at construction if any secret still equals its baked-in
        development literal. The admin password is checked where it is used
        (require_admin_credentials), because the api and worker never connect
        as gg_admin and are deployed without that credential."""
        if self.environment not in ("dev", "prod"):
            return self
        offenders = [
            name
            for name, secret, dev_default in (
                ("auth_jwt_secret", self.auth_jwt_secret, _DEV_JWT_SECRET),
                ("postgres.password", self.postgres.password, _DEV_PG_PASSWORD),
                ("neo4j.password", self.neo4j.password, _DEV_NEO4J_PASSWORD),
                ("objectstore.secret_key", self.objectstore.secret_key, _DEV_S3_SECRET),
            )
            if secret.get_secret_value() == dev_default
        ]
        if offenders:
            raise ValueError(
                f"environment={self.environment!r} still uses development secret "
                f"defaults for: {', '.join(offenders)}. Set the corresponding "
                "GG_* environment variables to real secrets."
            )
        return self


def require_admin_credentials(settings: AppSettings) -> str:
    """The gg_admin SQLAlchemy URL for migrations and other admin tasks.

    In dev and prod, refuses the shipped development admin password."""
    if (
        settings.environment in ("dev", "prod")
        and settings.postgres.admin_password.get_secret_value() == _DEV_PG_ADMIN_PASSWORD
    ):
        raise ValueError(
            f"environment={settings.environment!r} still uses the development admin "
            "password. Set GG_PG_ADMIN_PASSWORD before running migrations."
        )
    return settings.postgres.admin_sqlalchemy_url


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()


def effective_settings_summary(settings: AppSettings) -> dict[str, object]:
    """Loggable snapshot of effective config with secrets masked."""
    dump = settings.model_dump()

    def mask(value: object) -> object:
        if isinstance(value, dict):
            return {k: mask(v) for k, v in value.items()}
        if isinstance(value, SecretStr):
            return "***"
        return value

    return {k: mask(v) for k, v in dump.items()}
