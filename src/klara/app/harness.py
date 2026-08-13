"""Application-layer harness that freezes and assembles one Klara run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from klara.app.user_context import UserContext
from klara.context.runtime import build_system_prompt
from klara.context.controller import ContextController
from klara.context.policy import ContextPolicy
from klara.core.hooks import HookManager, JsonlTraceHook, KlaraHook
from klara.core.loop import KlaraLoop, KlaraRunResult, LlmClient, LoopController
from klara.core.messages import KlaraMessage
from klara.core.policies import LoopPolicy
from klara.infra.config.models import ModelsConfig
from klara.infra.config.runtime import CapabilityProfile, ProviderRecoveryPolicy
from klara.memory import (
    MemoryRuntimeController,
    MemoryScope,
    MemoryService,
    SQLiteMemoryRepository,
    memory_tools,
)
from klara.permissions import (
    PermissionActionResolver,
    PermissionEngineHook,
    PermissionScope,
    PermissionService,
    SQLitePermissionRepository,
)
from klara.services.web import WebResearchController
from klara.services.evidence import EvidenceRuntimeController
from klara.skills import SkillCatalog, SkillListTool, SkillRuntimeController, SkillViewTool
from klara.tools.executor import ToolExecutor
from klara.tools.registry import ToolRegistry


DEFAULT_LOOP_POLICY = LoopPolicy()
DEFAULT_PERSONA_PATH = Path(__file__).parents[1] / "prompts" / "persona.md"
INTERNAL_TOOL_NAMES = ("update_activity",)


@dataclass(frozen=True)
class KlaraHarnessConfig:
    """Immutable inputs needed to assemble one loop run."""

    model: str = "fake-model"
    thinking_enabled: bool | None = None
    capability_profile: CapabilityProfile = field(
        default_factory=lambda: CapabilityProfile(
            id="agent", hooks=(), trace_sink="none"
        )
    )
    trace_path: Path | None = None
    loop_policy: LoopPolicy = field(default_factory=LoopPolicy)
    user_context: UserContext = field(default_factory=UserContext.local_default)
    persona_path: Path = DEFAULT_PERSONA_PATH
    context_policy: ContextPolicy = field(default_factory=ContextPolicy)
    provider_recovery_policy: ProviderRecoveryPolicy = field(
        default_factory=ProviderRecoveryPolicy
    )
    workspace_root: Path = field(default_factory=Path.cwd)
    user_skills_root: Path | None = None
    project_skills_root: Path | None = None
    allowed_skill_permissions: tuple[str, ...] = ()
    memory_path: Path = Path("data/memory/klara.sqlite3")
    permission_path: Path = Path("data/permissions/klara.sqlite3")
    session_id: str | None = None
    agent_id: str = "klara"

    # Legacy property access stays stable for the Chapter 1 tutorial while the
    # canonical policy is now one immutable object.
    @property
    def max_turns(self) -> int:
        return self.loop_policy.max_turns

    @property
    def max_tool_calls(self) -> int:
        return self.loop_policy.max_tool_calls

    @property
    def max_repeated_tool_calls(self) -> int:
        return self.loop_policy.max_repeated_tool_calls

    @property
    def max_repeated_final_blocks(self) -> int:
        return self.loop_policy.max_repeated_final_blocks


@dataclass(frozen=True)
class KlaraRunProfile:
    """Secret-free immutable record of the exact runtime assembly."""

    schema_version: str
    model: str
    thinking_enabled: bool | None
    capability_profile: str
    required_model_capabilities: tuple[str, ...]
    visible_tools: tuple[str, ...]
    hooks: tuple[str, ...]
    trace_sink: str
    loop_policy: LoopPolicy
    user_partition: str
    locale: str
    timezone: str
    persona_sha256: str
    context_policy: ContextPolicy
    provider_recovery_policy: ProviderRecoveryPolicy
    skill_catalog_count: int
    skill_catalog_sha256: str
    profile_sha256: str

    def to_public_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible projection with no credential values."""

        return {
            "schema_version": self.schema_version,
            "model": self.model,
            "thinking_enabled": self.thinking_enabled,
            "capability_profile": self.capability_profile,
            "required_model_capabilities": list(self.required_model_capabilities),
            "visible_tools": list(self.visible_tools),
            "hooks": list(self.hooks),
            "trace_sink": self.trace_sink,
            "loop_policy": {
                "max_turns": self.loop_policy.max_turns,
                "max_tool_calls": self.loop_policy.max_tool_calls,
                "max_repeated_tool_calls": self.loop_policy.max_repeated_tool_calls,
                "max_repeated_final_blocks": self.loop_policy.max_repeated_final_blocks,
                "max_prompt_recovery_attempts": self.loop_policy.max_prompt_recovery_attempts,
            },
            "user_partition": self.user_partition,
            "locale": self.locale,
            "timezone": self.timezone,
            "persona_sha256": self.persona_sha256,
            "context_policy": self.context_policy.to_public_dict(),
            "provider_recovery_policy": self.provider_recovery_policy.to_public_dict(),
            "skill_catalog_count": self.skill_catalog_count,
            "skill_catalog_sha256": self.skill_catalog_sha256,
            "profile_sha256": self.profile_sha256,
        }


class KlaraHarness:
    """Single product assembly boundary for CLI, API, and direct local runs."""

    def __init__(
        self,
        *,
        llm: LlmClient,
        registry: ToolRegistry | None = None,
        config: KlaraHarnessConfig | None = None,
        models: ModelsConfig | None = None,
        hooks: Iterable[KlaraHook] = (),
        controllers: tuple[LoopController, ...] | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry or ToolRegistry.with_default_tools()
        self.config = config or KlaraHarnessConfig()
        self.models = models
        self.extra_hooks = tuple(hooks)
        self.controllers = controllers
        self.memory_repository = SQLiteMemoryRepository(self.config.memory_path)
        self.memory_service = MemoryService(self.memory_repository)
        self.memory_scope = MemoryScope(
            tenant_id=self.config.user_context.tenant_id,
            user_id=self.config.user_context.user_id,
            agent_id=self.config.agent_id,
            session_id=self.config.session_id,
        )
        for tool in memory_tools(self.memory_service, self.memory_scope):
            self.registry.register_tool(tool)
        self.skill_catalog = self._build_skill_catalog()
        self.registry.register_tool(SkillListTool(self.skill_catalog))
        self.registry.register_tool(SkillViewTool(self.skill_catalog))
        self._selected_tools = self._select_tools()
        self.permission_repository = SQLitePermissionRepository(
            self.config.permission_path
        )
        self.permission_service = PermissionService(self.permission_repository)
        self.permission_scope = PermissionScope(
            tenant_id=self.config.user_context.tenant_id,
            actor_id=self.config.user_context.user_id,
            agent_id=self.config.agent_id,
            task_id=self.config.session_id,
        )
        self.permission_resolver = PermissionActionResolver(
            {
                tool.spec.name: tool.metadata
                for tool in self._selected_tools
            },
            self.config.workspace_root,
        )
        self._validate_model_capabilities()
        if (
            self.config.capability_profile.trace_sink == "jsonl"
            and self.config.trace_path is None
        ):
            raise ValueError("jsonl_trace_path_required")
        self.run_profile = self._build_run_profile()

    def build_loop(self, *, now: datetime | None = None) -> KlaraLoop:
        """Build, but do not execute, the exact loop described by `run_profile`."""

        hooks = HookManager(
            [
                PermissionEngineHook(
                    service=self.permission_service,
                    resolver=self.permission_resolver,
                    scope=self.permission_scope,
                ),
                *self.extra_hooks,
            ]
        )
        if self.config.trace_path is not None:
            hooks.register(JsonlTraceHook(self.config.trace_path))
        controllers = self.controllers
        if controllers is None:
            web_research = WebResearchController(
                user_timezone=self.config.user_context.timezone
            )
            controllers = (
                ContextController(
                    policy=self.config.context_policy,
                    user_context=self.config.user_context,
                    capabilities=self._visible_tool_names(),
                    workspace_root=self.config.workspace_root,
                ),
                MemoryRuntimeController(),
                web_research,
                EvidenceRuntimeController(web_research),
                SkillRuntimeController(self.skill_catalog),
            )
        return KlaraLoop(
            llm=self.llm,
            tool_executor=ToolExecutor(list(self._selected_tools)),
            hooks=hooks,
            policy=self.config.loop_policy,
            controllers=controllers,
            model=self.config.model,
            thinking_enabled=self.config.thinking_enabled,
            system_prompt=self.system_prompt(now=now),
        )

    def run(
        self,
        user_input: str,
        *,
        run_id: str | None = None,
        prior_messages: tuple[KlaraMessage, ...] = (),
        now: datetime | None = None,
    ) -> KlaraRunResult:
        """Execute one run through the frozen assembly profile."""

        return self.build_loop(now=now).run(
            user_input,
            run_id=run_id,
            prior_messages=prior_messages,
        )

    def system_prompt(self, *, now: datetime | None = None) -> str:
        """Build persona plus runtime context outside core."""

        return build_system_prompt(
            persona=self.config.persona_path.read_text(encoding="utf-8"),
            timezone_name=self.config.user_context.timezone,
            now=now,
        )

    def _select_tools(self) -> tuple[Any, ...]:
        available = {tool.spec.name: tool for tool in self.registry.visible_tools()}
        requested = self.config.capability_profile.visible_tools
        if not requested:
            return tuple(available.values())
        missing = [
            name
            for name in requested
            if name not in available and name not in INTERNAL_TOOL_NAMES
        ]
        if missing:
            raise ValueError(f"capability_profile_missing_tools:{','.join(missing)}")
        return tuple(available[name] for name in requested if name in available)

    def _build_skill_catalog(self) -> SkillCatalog:
        """Discover the three Skill scopes under frozen run authority."""

        user_root = self.config.user_skills_root
        if user_root is None:
            user_root = Path.home() / ".klara" / "skills"
        project_root = self.config.project_skills_root
        if project_root is None:
            project_root = self.config.workspace_root / ".klara" / "skills"
        built_in_root = Path(__file__).parents[1] / "skills" / "builtin"
        allowed_tools = {
            tool.spec.name for tool in self.registry.visible_tools()
        } | set(INTERNAL_TOOL_NAMES) | {"skills_list", "skill_view"}
        return SkillCatalog.discover(
            built_in_root=built_in_root,
            user_root=user_root,
            project_root=project_root,
            allowed_tools=allowed_tools,
            allowed_permissions=self.config.allowed_skill_permissions,
        )

    def _validate_model_capabilities(self) -> None:
        if self.models is None or self.config.model == "fake-model":
            return
        provider_id, separator, model_id = self.config.model.partition("/")
        if not separator or provider_id not in self.models.providers:
            raise ValueError("model_not_configured")
        model = self.models.providers[provider_id].model_entry(model_id)
        if model is None:
            raise ValueError("model_not_configured")
        supported = {
            "tools": model.supports_tools,
            "json": model.supports_json,
            "vision": model.supports_vision,
            "thinking": model.supports_thinking,
        }
        missing = [
            capability
            for capability in self.config.capability_profile.required_model_capabilities
            if not supported[capability]
        ]
        if missing:
            raise ValueError(f"model_capability_mismatch:{','.join(missing)}")
        if self.config.thinking_enabled and not model.supports_thinking:
            raise ValueError("thinking_not_supported")

    def _build_run_profile(self) -> KlaraRunProfile:
        persona_hash = hashlib.sha256(self.config.persona_path.read_bytes()).hexdigest()
        payload = {
            "schema_version": "klara.run-profile.v1",
            "model": self.config.model,
            "thinking_enabled": self.config.thinking_enabled,
            "capability_profile": self.config.capability_profile.id,
            "required_model_capabilities": list(
                self.config.capability_profile.required_model_capabilities
            ),
            "visible_tools": list(self._visible_tool_names()),
            "hooks": list(self._hook_names()),
            "trace_sink": self._trace_sink(),
            "loop_policy": {
                "max_turns": self.config.loop_policy.max_turns,
                "max_tool_calls": self.config.loop_policy.max_tool_calls,
                "max_repeated_tool_calls": self.config.loop_policy.max_repeated_tool_calls,
                "max_repeated_final_blocks": self.config.loop_policy.max_repeated_final_blocks,
                "max_prompt_recovery_attempts": self.config.loop_policy.max_prompt_recovery_attempts,
            },
            "user_partition": self.config.user_context.storage_key,
            "locale": self.config.user_context.locale,
            "timezone": self.config.user_context.timezone,
            "persona_sha256": persona_hash,
            "context_policy": self.config.context_policy.to_public_dict(),
            "provider_recovery_policy": self.config.provider_recovery_policy.to_public_dict(),
            "skill_catalog_count": len(self.skill_catalog.list()),
            "skill_catalog_sha256": self.skill_catalog.catalog_sha256,
        }
        profile_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return KlaraRunProfile(
            schema_version=str(payload["schema_version"]),
            model=self.config.model,
            thinking_enabled=self.config.thinking_enabled,
            capability_profile=self.config.capability_profile.id,
            required_model_capabilities=self.config.capability_profile.required_model_capabilities,
            visible_tools=tuple(payload["visible_tools"]),
            hooks=self._hook_names(),
            trace_sink=self._trace_sink(),
            loop_policy=self.config.loop_policy,
            user_partition=self.config.user_context.storage_key,
            locale=self.config.user_context.locale,
            timezone=self.config.user_context.timezone,
            persona_sha256=persona_hash,
            context_policy=self.config.context_policy,
            provider_recovery_policy=self.config.provider_recovery_policy,
            skill_catalog_count=len(self.skill_catalog.list()),
            skill_catalog_sha256=self.skill_catalog.catalog_sha256,
            profile_sha256=profile_hash,
        )

    def _trace_sink(self) -> str:
        if self.config.capability_profile.trace_sink == "jsonl" and self.config.trace_path is None:
            return "unavailable"
        return "jsonl" if self.config.trace_path is not None else "none"

    def _hook_names(self) -> tuple[str, ...]:
        names = ["permission_engine", *self.config.capability_profile.hooks]
        if self.config.trace_path is not None and "jsonl_trace" not in names:
            names.append("jsonl_trace")
        return tuple(names)

    def _visible_tool_names(self) -> tuple[str, ...]:
        selected = tuple(tool.spec.name for tool in self._selected_tools)
        requested_internal = tuple(
            name
            for name in self.config.capability_profile.visible_tools
            if name in INTERNAL_TOOL_NAMES
        )
        if not self.config.capability_profile.visible_tools:
            requested_internal = INTERNAL_TOOL_NAMES
        return (*selected, *requested_internal)
