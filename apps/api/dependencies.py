from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from apps.api.schemas import ModelOption
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.app.user_context import UserContext
from klara.infra.config.env import get_env_secret
from klara.infra.config.loader import load_models_config, load_runtime_config
from klara.infra.config.models import ModelsConfig, ProviderModel
from klara.infra.llm.routed_client import RoutedLlmClient
from klara.infra.llm.openai_compatible import OpenAICompatibleSettings
from klara.memory import MemoryScope, MemoryService, SQLiteMemoryRepository
from klara.permissions import PermissionScope, PermissionService, SQLitePermissionRepository
from klara.skills import SkillCatalog
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope
from klara.scheduler import SchedulerService, SQLiteScheduleRepository
from klara.mcp import McpService, SQLiteMcpRepository
from klara.teams import KlaraOneShotExecutor, SQLiteTeamRepository, TeamScope, TeamService
from klara.production import AuthConfig, AuthService, OidcConfig, OidcVerifier, PostgresProductionRepository, ProductionIdentityBoundary, ProductionRepository, ProductionRuntimeService, SafeRuntimeMetrics, TrajectoryExportService
from apps.api.services.scheduler_runner import SchedulerRunner


def _load_model_options(
    models: ModelsConfig,
    *,
    dotenv_path: str | Path | None = ".env",
) -> list[ModelOption]:
    """Build UI model options from Klara's TOML provider registry."""

    options: list[ModelOption] = []
    for provider_id, provider in models.providers.items():
        if provider.api_key_env and not get_env_secret(provider.api_key_env, dotenv_path=dotenv_path):
            continue
        for item in provider.models:
            model_ref = f"{provider_id}/{item.id}"
            options.append(
                ModelOption(
                    id=model_ref,
                    model=model_ref,
                    label=item.label or model_ref,
                    use_when=_model_use_when(provider_id, item.supports_vision),
                    capabilities=_model_capabilities(item),
                    supports_thinking=item.supports_thinking,
                    default_thinking=item.default_thinking,
                )
            )
    return options


def _default_model(models: ModelsConfig, options: list[ModelOption]) -> str:
    """Return the configured primary model when available, otherwise a visible model."""

    profile = models.profile("agent")
    visible_models = {item.model for item in options}
    if profile.primary in visible_models:
        return profile.primary
    if options:
        return options[0].model
    return profile.primary


def _model_use_when(provider_id: str, supports_vision: bool) -> str:
    """Return a compact UI hint for one configured model."""

    if supports_vision:
        return f"{provider_id} provider, vision-capable"
    return f"{provider_id} provider"


def _model_capabilities(item: ProviderModel) -> list[str]:
    """Return stable public capability badges for one configured model."""

    flags = {
        "Tools": item.supports_tools,
        "JSON": item.supports_json,
        "Vision": item.supports_vision,
        "Thinking": item.supports_thinking,
    }
    return [name for name, supported in flags.items() if supported]


def _local_user_context() -> UserContext:
    """Build the local app user context, including prompt timezone."""

    timezone = os.getenv("KLARA_TIMEZONE", "local").strip() or "local"
    return replace(UserContext.local_default(), timezone=timezone)


_store = JsonlAppStore(os.getenv("KLARA_APP_DATA", "data/app"))
_bus = SSEBus()
_models = load_models_config(Path("config"))
_runtime = load_runtime_config(Path("config"))
_model_options = _load_model_options(_models)
_default_model_ref = _default_model(_models, _model_options)
_workspace_root = Path.cwd()
_skill_catalog = SkillCatalog.discover(
    built_in_root=Path(__file__).parents[2] / "src" / "klara" / "skills" / "builtin",
    user_root=Path.home() / ".klara" / "skills",
    project_root=_workspace_root / ".klara" / "skills",
    allowed_tools=set(_runtime.profile().visible_tools),
)
_memory_repository = SQLiteMemoryRepository(_store.root / "memory.sqlite3")
_memory_service = MemoryService(_memory_repository)
_memory_scope = MemoryScope(
    tenant_id="local-tenant",
    user_id="local-user",
    agent_id="klara",
)
_permission_repository = SQLitePermissionRepository(_store.root / "permissions.sqlite3")
_permission_service = PermissionService(_permission_repository)
_permission_scope = PermissionScope(
    tenant_id="local-tenant",
    actor_id="local-user",
    agent_id="klara",
)
_mcp_repository = SQLiteMcpRepository(_store.root / "mcp.sqlite3")
_mcp_service = McpService(_mcp_repository, _permission_service)
_task_repository = SQLiteTaskRepository(_store.root / "tasks.sqlite3")
_task_service = DurableTaskService(_task_repository)
_task_scope = TaskScope(
    tenant_id="local-tenant",
    owner_id="local-user",
    agent_id="klara",
)
_team_repository = SQLiteTeamRepository(_store.root / "teams.sqlite3")
_llm = RoutedLlmClient(
    models=_models,
    dotenv_path=".env",
    settings=OpenAICompatibleSettings(
        **_runtime.provider_recovery_policy.to_public_dict()
    ),
)
_team_scope = TeamScope(
    tenant_id="local-tenant",
    owner_id="local-user",
    team_id="default-team",
)
_team_service = TeamService(
    _team_repository,
    _task_service,
    _permission_service,
    project_root=_workspace_root,
    executor=KlaraOneShotExecutor(
        llm=_llm,
        model=_default_model_ref,
        models=_models,
        user_context=_local_user_context(),
        workspace_root=_workspace_root,
        data_root=_store.root,
        loop_policy=_runtime.loop_policy,
        provider_recovery_policy=_runtime.provider_recovery_policy,
    ),
)
_schedule_repository = SQLiteScheduleRepository(_store.root / "schedules.sqlite3")
_scheduler_service = SchedulerService(_schedule_repository, _task_service)
_run_service = RunService(
    store=_store,
    bus=_bus,
    llm_client=_llm,
    trace_path=os.getenv("KLARA_TRACE_PATH", "data/traces/runs.jsonl"),
    allowed_models={item.model for item in _model_options},
    thinking_support={item.model: item.supports_thinking for item in _model_options},
    default_thinking={item.model: item.default_thinking for item in _model_options},
    default_model=_default_model_ref,
    loop_policy=_runtime.loop_policy,
    context_policy=_runtime.context_policy,
    provider_recovery_policy=_runtime.provider_recovery_policy,
    user_context=_local_user_context(),
    models_config=_models,
    capability_profile=_runtime.profile(),
    task_service=_task_service,
    task_scope=_task_scope,
    mcp_service=_mcp_service,
    scheduler_service=_scheduler_service,
    team_service=_team_service,
    team_scope=_team_scope,
    permission_scope=_permission_scope,
)
_scheduler_runner = SchedulerRunner(
    service=_scheduler_service,
    scope=_task_scope,
    run_service=_run_service,
)
_database_url = os.getenv("KLARA_DATABASE_URL", "").strip()
_production_repository = (
    PostgresProductionRepository(_database_url)
    if _database_url.startswith(("postgresql://", "postgres://"))
    else ProductionRepository(
        os.getenv("KLARA_PRODUCTION_DB", str(_store.root / "production.sqlite3"))
    )
)
_production_auth_config = AuthConfig.from_env()
_production_auth = AuthService(_production_auth_config)
_oidc_issuer = os.getenv("KLARA_OIDC_ISSUER", "").strip()
_oidc_audience = os.getenv("KLARA_OIDC_AUDIENCE", "").strip()
_production_oidc = (
    OidcVerifier(OidcConfig(issuer=_oidc_issuer, audience=_oidc_audience))
    if _oidc_issuer and _oidc_audience
    else None
)
_production_identity = ProductionIdentityBoundary(
    local=_production_auth,
    oidc=_production_oidc,
    revocations=_production_repository,
    oidc_bearer=_production_auth_config.mode == "production" and _production_oidc is not None,
)
_production_metrics = SafeRuntimeMetrics()
_trajectory_exporter = TrajectoryExportService(
    _production_repository,
    os.getenv("KLARA_TRAJECTORY_EXPORT_ROOT", "data/exports/trajectories"),
    allowed_trace_roots=(Path(os.getenv("KLARA_TRACE_PATH", "data/traces/runs.jsonl")).parent,),
)
_production_runtime = ProductionRuntimeService(
    _production_repository,
    _trajectory_exporter,
)


def get_store() -> JsonlAppStore:
    return _store


def get_bus() -> SSEBus:
    return _bus


def get_run_service() -> RunService:
    return _run_service


def get_model_options() -> list[ModelOption]:
    return _model_options


def get_default_model() -> str:
    return _default_model_ref


def get_skill_catalog() -> SkillCatalog:
    """Return the same resolved local catalog contract used by product runs."""

    return _skill_catalog


def get_memory_service() -> MemoryService:
    """Return the local durable memory service."""

    return _memory_service


def get_memory_scope() -> MemoryScope:
    """Return the authenticated local owner partition for API requests."""

    return _memory_scope


def get_permission_service() -> PermissionService:
    """Return the durable permission service shared by runs and approvals."""

    return _permission_service


def get_permission_scope() -> PermissionScope:
    """Return the authenticated local owner partition for permission records."""

    return _permission_scope


def get_mcp_service() -> McpService:
    """Return the tenant-scoped MCP lifecycle service."""

    return _mcp_service


def get_task_service() -> DurableTaskService:
    """Return the task service shared by runs and the Task Board API."""

    return _task_service


def get_task_scope() -> TaskScope:
    """Return the authenticated local task owner partition."""

    return _task_scope


def get_team_service() -> TeamService:
    """Return the bounded local team runtime."""

    return _team_service


def get_team_scope() -> TeamScope:
    """Return the authenticated local team partition."""

    return _team_scope


def get_scheduler_service() -> SchedulerService:
    """Return the tenant-scoped schedule state machine."""

    return _scheduler_service


def get_scheduler_runner() -> SchedulerRunner:
    """Return the local background worker and its idempotent dispatch callbacks."""

    return _scheduler_runner


def get_production_auth() -> AuthService:
    """Return the signed bearer-token boundary."""

    return _production_auth


def get_production_identity() -> ProductionIdentityBoundary:
    """Return the local/OIDC identity and revocation boundary."""

    return _production_identity


def get_production_runtime() -> ProductionRuntimeService:
    """Return the authenticated persistence and queue coordinator."""

    return _production_runtime


def get_production_metrics() -> SafeRuntimeMetrics:
    """Return payload-free production request metrics."""

    return _production_metrics
