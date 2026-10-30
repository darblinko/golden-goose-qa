"""FastAPI application factory: wires settings, datastores, providers, the
hybrid retriever, and the LangGraph agent (Postgres-checkpointed), then mounts
the auth, thread, chat, and health routers."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from gg_agents.graph import build_agent_graph
from gg_agents.nodes import AgentDeps
from gg_common.db import create_engine, create_session_factory
from gg_common.graphstore import create_graph_driver
from gg_common.logging import configure_logging, log_effective_settings
from gg_common.objectstore import S3ObjectStore
from gg_common.providers.factory import build_providers
from gg_common.settings import AppSettings, get_settings
from gg_common.tracing import configure_tracing, reset_tracing
from gg_retrieval.audit import AuditReportRunner
from gg_retrieval.retriever import HybridRetriever
from gg_retrieval.tools.external.toolkit import build_external_toolkit
from gg_retrieval.tools.graph_walk import GraphWalker
from gg_retrieval.tools.warehouse import WarehouseTool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from qdrant_client import AsyncQdrantClient

from goldengoose_api.ratelimit import RateLimiter, rate_limit_middleware
from goldengoose_api.routers import (
    audit_routes,
    auth_routes,
    chat_routes,
    graph_routes,
    health_routes,
    source_routes,
    thread_routes,
)

_DEV_CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def _checkpointer_conninfo(settings: AppSettings) -> str:
    pg = settings.postgres
    return (
        f"host={pg.host} port={pg.port} dbname={pg.database} "
        f"user={pg.user} password={pg.password.get_secret_value()} "
        f"options='-c search_path=checkpoints'"
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: AppSettings = app.state.settings
    configure_logging(settings)
    log_effective_settings(settings)
    configure_tracing(settings.tracing)

    app.state.engine = create_engine(settings.postgres)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.providers = build_providers(settings.providers)
    app.state.object_store = S3ObjectStore(settings.objectstore)
    qdrant_key = settings.qdrant.api_key.get_secret_value() if settings.qdrant.api_key else None
    app.state.qdrant = AsyncQdrantClient(url=settings.qdrant.url, api_key=qdrant_key)
    app.state.retriever = HybridRetriever(
        settings=settings,
        qdrant=app.state.qdrant,
        session_factory=app.state.session_factory,
        embeddings=app.state.providers.embeddings,
        reranker=app.state.providers.rerank,
    )

    app.state.graph_driver = create_graph_driver(settings.neo4j)

    warehouse = WarehouseTool(session_factory=app.state.session_factory, settings=settings)
    graph_walker = GraphWalker(driver=app.state.graph_driver, settings=settings)
    app.state.audit_runner = AuditReportRunner(warehouse=warehouse, graph=graph_walker)

    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(_checkpointer_conninfo(settings))
        )
        await checkpointer.setup()
        deps = AgentDeps(
            settings=settings,
            retriever=app.state.retriever,
            llm=app.state.providers.llm,
            llm_is_fake="llm" in app.state.providers.using_fakes,
            warehouse=warehouse,
            graph=graph_walker,
            external=build_external_toolkit(
                settings.external,
                tavily_api_key=(
                    settings.providers.tavily_api_key.get_secret_value()
                    if settings.providers.tavily_api_key
                    else None
                ),
            ),
        )
        app.state.agent_graph = build_agent_graph(deps, checkpointer=checkpointer)
        try:
            yield
        finally:
            reset_tracing()
            await app.state.graph_driver.close()
            await app.state.qdrant.close()
            await app.state.engine.dispose()


def create_app(settings: AppSettings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    # Serve every route under the configured prefix (empty by default). A cloud
    # ALB that routes /api/* to this service and everything else to the web app
    # sets GG_API_ROOT_PATH=/api, giving the browser a single origin.
    # The ALB forwards /api/* without stripping the prefix, so the routes are
    # registered under it directly (not via FastAPI root_path, which assumes a
    # stripping proxy).
    prefix = resolved.api_root_path
    app = FastAPI(title="Golden Goose", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.rate_limiter = RateLimiter()

    app.middleware("http")(rate_limit_middleware)
    if resolved.environment in ("local", "ci"):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_DEV_CORS_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        app.include_router(auth_routes.router, prefix=prefix)

    app.include_router(health_routes.router, prefix=prefix)
    app.include_router(thread_routes.router, prefix=prefix)
    app.include_router(chat_routes.router, prefix=prefix)
    app.include_router(audit_routes.router, prefix=prefix)
    app.include_router(graph_routes.router, prefix=prefix)
    app.include_router(source_routes.router, prefix=prefix)
    return app


app = create_app()
