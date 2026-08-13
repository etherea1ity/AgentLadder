from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, cast
from urllib.parse import urlparse

from apps.api.schemas import RunEventRecord, RunEventType
from klara.core.events import KlaraEvent


PUBLIC_RUNTIME_EVENT_MESSAGES = {
    "web_research.started": "Web research state started.",
    "web_research.state_updated": "Web research state updated.",
    "web_research.no_viable_action": "Web research has no viable next action.",
    "web_search.started": "Web search started.",
    "web_search.completed": "Web search completed.",
    "web_search.failed": "Web search failed.",
    "web_fetch.started": "Web fetch started.",
    "web_fetch.completed": "Web fetch completed.",
    "web_fetch.failed": "Web fetch failed.",
    "evidence.candidate_recorded": "Search candidate recorded.",
    "evidence.source_recorded": "Fetched source recorded.",
    "evidence.readiness_evaluated": "Evidence readiness evaluated.",
    "evidence.answer_submitted": "Claim-level answer submitted for verification.",
    "evidence.submission_rejected": "Evidence submission was rejected.",
    "evidence.verification_completed": "Claim-level evidence verification completed.",
    "evidence.verification_failed": "Claim-level evidence verification failed.",
    "final_answer.blocked": "Final answer blocked by runtime policy.",
    "final_answer.allowed": "Final answer allowed by runtime policy.",
    "final_answer.no_progress_stopped": "Final answer blocking stopped for no progress.",
    "context.compacted": "Model-visible context compacted.",
    "context.assembled": "Runtime context contract assembled.",
    "context.budget_evaluated": "Model-visible context budget evaluated.",
    "context.prompt_recovery_applied": "Context budget tightened after provider rejection.",
    "provider.attempt_started": "Provider attempt started.",
    "provider.attempt_completed": "Provider attempt completed.",
    "provider.attempt_failed": "Provider attempt failed.",
    "provider.retry_scheduled": "Provider retry scheduled.",
    "model_route.candidate_started": "Model route candidate started.",
    "model_route.candidate_failed": "Model route candidate failed.",
    "model_route.fallback_started": "Fallback model route started.",
    "model_route.candidate_completed": "Model route candidate completed.",
    "model_call.failed": "Model call failed.",
    "prompt_recovery.started": "Prompt recovery started.",
    "prompt_recovery.completed": "Prompt recovery completed.",
    "skills.catalog_ready": "Skills catalog ready.",
    "skills.selected": "Skill selected.",
    "skills.loaded": "Skill loaded.",
    "skills.load_rejected": "Skill load rejected.",
    "memory.review_completed": "Memory write review completed.",
    "memory.remembered": "Memory saved.",
    "memory.retrieved": "Memory retrieved.",
    "memory.updated": "Memory updated.",
    "memory.forgotten": "Memory forgotten.",
    "memory.deleted": "Memory deleted.",
}


@dataclass(frozen=True)
class ProjectedRunEvent:
    """Frontend-visible event produced from one public core lifecycle event."""

    event_type: RunEventType
    message: str
    payload: dict[str, Any]


class UsageTotals:
    """Accumulate provider token usage across projected LLM events."""

    def __init__(self) -> None:
        """Create an empty usage accumulator."""

        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.has_reported = False

    def add(self, usage: dict[str, Any], *, token_source: str | None = None) -> None:
        """Add one provider usage payload when token fields are present."""

        payload = _usage_payload(usage)
        if token_source == "reported" or any(value is not None for value in payload.values()):
            self.has_reported = True
        self.prompt_tokens += payload["prompt_tokens"] or 0
        self.completion_tokens += payload["completion_tokens"] or 0
        self.total_tokens += payload["total_tokens"] or 0


class RunEventProjector:
    """Project public Klara lifecycle events into API/SSE run events."""

    def __init__(
        self,
        *,
        selected_model: str | None = None,
        usage_totals: UsageTotals | None = None,
    ) -> None:
        """Create a projector for one app run."""

        self.selected_model = selected_model
        self.usage_totals = usage_totals or UsageTotals()

    def project(self, event: KlaraEvent) -> tuple[ProjectedRunEvent, ...]:
        """Return API events derived from one public core event."""

        if event.type == "llm.started":
            input_profile = _dict_payload(event.payload.get("input_profile"))
            return (
                ProjectedRunEvent(
                    event_type="llm_call_started",
                    message="Klara is calling the model.",
                    payload={
                        "turn_index": event.payload.get("turn_index"),
                        "model": event.payload.get("model") or self.selected_model,
                        "finalization": bool(event.payload.get("finalization", False)),
                        **({"input_profile": input_profile} if input_profile else {}),
                    },
                ),
            )
        if event.type == "llm.completed":
            usage = (
                event.payload.get("usage")
                if isinstance(event.payload.get("usage"), dict)
                else {}
            )
            metrics = _dict_payload(event.payload.get("metrics"))
            reasoning = _dict_payload(event.payload.get("reasoning"))
            activity = _dict_payload(event.payload.get("activity_commentary"))
            response_profile = _dict_payload(event.payload.get("response_profile"))
            usage_fields = _usage_payload(usage)
            token_source = _token_source(metrics, usage_fields)
            duration_ms = _int_or_none(metrics.get("duration_ms"))
            self.usage_totals.add(usage, token_source=token_source)
            return (
                ProjectedRunEvent(
                    event_type="llm_call_completed",
                    message="Model call completed.",
                    payload={
                        "turn_index": event.payload.get("turn_index"),
                        "requested_model": event.payload.get("requested_model")
                        or self.selected_model,
                        "model": event.payload.get("model") or self.selected_model,
                        "tool_call_count": event.payload.get("tool_call_count"),
                        "usage": usage,
                        "finalization": bool(event.payload.get("finalization", False)),
                        **usage_fields,
                        "duration_ms": duration_ms,
                        "latency_ms": duration_ms,
                        "token_source": token_source,
                        "metrics": {
                            **usage_fields,
                            "duration_ms": duration_ms,
                            "token_source": token_source,
                        },
                        **({"reasoning": reasoning} if reasoning else {}),
                        **({"activity_commentary": activity} if activity else {}),
                        **(
                            {"response_profile": response_profile}
                            if response_profile
                            else {}
                        ),
                    },
                ),
            )
        if event.type == "tool.started":
            tool_call = _dict_payload(event.payload.get("tool_call"))
            name = str(tool_call.get("name") or "tool")
            started = ProjectedRunEvent(
                event_type="tool_call_started",
                message=f"Klara is using {name}.",
                payload={
                    "turn_index": event.payload.get("turn_index"),
                    "tool_call": tool_call,
                    "started_at": event.payload.get("started_at"),
                },
            )
            if name in {"web_search", "web_fetch"}:
                return (
                    started,
                    ProjectedRunEvent(
                        event_type=cast(RunEventType, f"{name}.started"),
                        message=PUBLIC_RUNTIME_EVENT_MESSAGES[f"{name}.started"],
                        payload={
                            "turn_index": event.payload.get("turn_index"),
                            "tool_call_id": tool_call.get("id"),
                            "started_at": event.payload.get("started_at"),
                        },
                    ),
                )
            return (started,)
        if event.type in {"tool.completed", "tool.failed"}:
            tool_result = _compact_tool_result(
                _dict_payload(event.payload.get("tool_result"))
            )
            metrics = _dict_payload(event.payload.get("metrics"))
            duration_ms = _int_or_none(metrics.get("duration_ms"))
            name = str(tool_result.get("name") or "tool")
            failed = event.type == "tool.failed" or tool_result.get("ok") is False
            return (
                ProjectedRunEvent(
                    event_type=(
                        "tool_call_failed" if failed else "tool_call_completed"
                    ),
                    message=(
                        f"{name} failed."
                        if failed
                        else f"{name} returned an observation."
                    ),
                    payload={
                        "turn_index": event.payload.get("turn_index"),
                        "tool_result": tool_result,
                        "blocked": bool(event.payload.get("blocked", False)),
                        "started_at": event.payload.get("started_at"),
                        "completed_at": event.payload.get("completed_at"),
                        "duration_ms": duration_ms,
                        "latency_ms": duration_ms,
                        "metrics": {"duration_ms": duration_ms},
                    },
                ),
            )
        if event.type == "tool_policy.stopped":
            return (
                ProjectedRunEvent(
                    event_type="policy_stop",
                    message="Tool policy stopped further tool calls.",
                    payload={
                        "core_event_type": event.type,
                        "turn_index": event.payload.get("turn_index"),
                        "stop_reason": event.payload.get("stop_reason"),
                        "reason": event.payload.get("reason"),
                    },
                ),
            )

        if str(event.type) in PUBLIC_RUNTIME_EVENT_MESSAGES:
            payload = dict(event.payload)
            if str(event.type).startswith("evidence."):
                payload = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"content", "final_text", "support_note", "support_notes"}
                }
                payload["private_evidence_content_exposed"] = False
            if str(event.type).startswith("memory."):
                payload = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"content", "query", "results", "provenance"}
                }
                payload["content_exposed"] = False
            return (
                ProjectedRunEvent(
                    event_type=cast(RunEventType, str(event.type)),
                    message=PUBLIC_RUNTIME_EVENT_MESSAGES[str(event.type)],
                    payload=payload,
                ),
            )

        hook_projection = _hook_projection(event)
        if hook_projection is not None:
            permission_projection = _permission_projection(event)
            if permission_projection is not None:
                return (hook_projection, permission_projection)
            return (hook_projection,)

        return ()


def project_activity_fact(event: RunEventRecord) -> ProjectedRunEvent | None:
    """Return one structured public fact derived from a persisted run event."""

    if event.event_type == "activity_fact_recorded":
        return None
    fact = _activity_fact_for_event(event)
    if fact is None:
        return None
    return ProjectedRunEvent(
        event_type="activity_fact_recorded",
        message="Activity fact recorded.",
        payload={"fact": fact},
    )


def project_provider_reasoning(event: RunEventRecord) -> tuple[ProjectedRunEvent, ...]:
    """Return public provider reasoning events derived from one LLM completion."""

    if event.event_type != "llm_call_completed":
        return ()
    reasoning = event.payload.get("reasoning")
    if not isinstance(reasoning, dict):
        return ()
    summary = _safe_provider_reasoning(reasoning.get("summary"))
    if not summary:
        return ()
    source = _string_or_none(reasoning.get("source")) or "provider_reasoning"
    item = {
        "id": f"provider_{event.event_id}",
        "title": "Provider reasoning",
        "body": summary,
        "kind": "orientation",
        "source": "provider_reasoning",
        "status": "completed",
        "evidence_event_ids": [event.event_id],
        "confidence": 1.0,
    }
    return (
        ProjectedRunEvent(
            event_type="provider_reasoning_delta",
            message="Provider reasoning summary received.",
            payload={
                "items": [item],
                "source": source,
                "evidence_event_ids": [event.event_id],
            },
        ),
        ProjectedRunEvent(
            event_type="provider_reasoning_completed",
            message="Provider reasoning summary completed.",
            payload={
                "source": source,
                "evidence_event_ids": [event.event_id],
            },
        ),
    )


def project_assistant_activity(event: RunEventRecord) -> tuple[ProjectedRunEvent, ...]:
    """Return public main-model activity commentary from one LLM event."""

    if event.event_type != "llm_call_completed":
        return ()
    activity = event.payload.get("activity_commentary")
    if not isinstance(activity, dict):
        return ()
    text = _safe_public_activity(activity.get("text"))
    if not text:
        return ()
    source = _string_or_none(activity.get("source")) or "main_model_commentary"
    phase = _activity_phase(activity.get("phase"))
    activity_id = _string_or_none(activity.get("activity_id")) or f"activity_{event.event_id}"
    sequence = activity.get("sequence")
    status = _activity_status(activity.get("status"))
    payload = {
        "activity_id": activity_id,
        "sequence": sequence if isinstance(sequence, int) else None,
        "status": status,
        "text": text,
        "source": "main_model_commentary",
        "source_detail": source,
        "phase": phase,
        "evidence_event_ids": [event.event_id],
    }
    return (
        ProjectedRunEvent(
            event_type="assistant_activity_delta",
            message="Assistant public activity commentary received.",
            payload=payload,
        ),
        ProjectedRunEvent(
            event_type="assistant_activity_completed",
            message="Assistant public activity commentary completed.",
            payload={
                "activity_id": activity_id,
                "sequence": sequence if isinstance(sequence, int) else None,
                "status": status,
                "source": "main_model_commentary",
                "phase": phase,
                "evidence_event_ids": [event.event_id],
            },
        ),
    )


def _activity_fact_for_event(event: RunEventRecord) -> dict[str, Any] | None:
    """Build a sanitized structured fact without user-visible prose."""

    if event.event_type == "thinking_summary_started":
        return _request_orientation_fact(event)
    if event.event_type == "llm_call_started":
        return _llm_activity_fact(event, status="started")
    if event.event_type == "llm_call_completed":
        return _llm_activity_fact(event, status="completed")
    if event.event_type == "tool_call_started":
        return _tool_activity_fact(event, status="started")
    if event.event_type == "tool_call_completed":
        return _tool_result_activity_fact(event, status="completed")
    if event.event_type == "tool_call_failed":
        return _tool_result_activity_fact(event, status="failed")
    if event.event_type == "answer_streaming_started":
        return _base_fact(event, kind="answer_phase", status="started")
    if event.event_type == "run_failed":
        return _base_fact(
            event,
            kind="error",
            status="failed",
            error_preview=_sanitize_preview(event.payload.get("error")),
        )
    if event.event_type == "policy_stop":
        return _base_fact(
            event,
            kind="policy_stop",
            status="completed",
            policy={
                "stop_reason": _string_or_none(event.payload.get("stop_reason")),
                "reason_preview": _sanitize_preview(event.payload.get("reason")),
            },
        )
    return None


def _request_orientation_fact(event: RunEventRecord) -> dict[str, Any] | None:
    """Return a fact describing the request boundary without full prompt text."""

    request = event.payload.get("request")
    if not isinstance(request, dict):
        return None
    preview = _sanitize_preview(request.get("preview"), max_chars=120)
    if not preview:
        return None
    return _base_fact(
        event,
        kind="request_orientation",
        status="completed",
        request={
            "preview": preview,
            "language": _string_or_none(request.get("language")) or "unknown",
        },
    )


def _llm_activity_fact(event: RunEventRecord, *, status: str) -> dict[str, Any]:
    """Return a structured fact for one LLM round."""

    return _base_fact(
        event,
        kind="llm_round",
        status=status,
        llm={
            "turn_index": event.payload.get("turn_index"),
            "model": _string_or_none(event.payload.get("model")),
            "finalization": bool(event.payload.get("finalization", False)),
            "tool_call_count": event.payload.get("tool_call_count"),
            "input_profile": _dict_payload(event.payload.get("input_profile")),
            "response_profile": _dict_payload(event.payload.get("response_profile")),
        },
        metrics=_fact_metrics(event),
    )


def _tool_activity_fact(event: RunEventRecord, *, status: str) -> dict[str, Any]:
    """Return a structured fact for a tool request without raw arguments."""

    name = _tool_call_name(event)
    return _base_fact(
        event,
        kind="tool_call",
        status=status,
        tool={"name": name},
    )


def _tool_result_activity_fact(event: RunEventRecord, *, status: str) -> dict[str, Any]:
    """Return a structured fact for a tool result without raw observations."""

    name = _tool_result_name(event)
    tool_result = event.payload.get("tool_result")
    result = tool_result if isinstance(tool_result, dict) else {}
    summary = result.get("structured_summary")
    structured_summary = summary if isinstance(summary, dict) else {}
    fact_kind = _tool_result_fact_kind(name, status)
    extra: dict[str, Any] = {
        "tool": {
            "name": name,
            "ok": bool(result.get("ok", status != "failed")),
        },
        "metrics": _fact_metrics(event),
        "content_length": _int_or_none(result.get("content_length")),
    }
    if structured_summary:
        extra["tool"]["structured_summary"] = structured_summary
    if name == "web_search":
        extra["web"] = {
            "result_count": _int_or_none(structured_summary.get("result_count")),
            "provider": _string_or_none(structured_summary.get("provider")),
            "top_domains": structured_summary.get("top_domains"),
            "top_titles": structured_summary.get("top_titles"),
            "truncated": structured_summary.get("truncated"),
        }
    elif name == "web_fetch":
        extra["web"] = {
            "status": _int_or_none(structured_summary.get("status")),
            "title_preview": _sanitize_preview(structured_summary.get("title")),
            "source_domain": _string_or_none(structured_summary.get("source_domain")),
            "text_length": _int_or_none(structured_summary.get("text_length")),
        }
    elif name == "image_generate":
        extra["image"] = {
            "image_count": _int_or_none(structured_summary.get("image_count")),
            "provider": _string_or_none(structured_summary.get("provider")),
            "model": _string_or_none(structured_summary.get("model")),
        }
    else:
        extra["observation_preview"] = _sanitize_preview(
            result.get("content_preview") or result.get("error")
        )
    if status == "failed":
        extra["error_preview"] = _sanitize_preview(result.get("error"))
    return _base_fact(event, kind=fact_kind, status=status, **extra)


def _tool_result_fact_kind(name: str, status: str) -> str:
    """Return the structured fact kind for a tool result."""

    if status == "failed":
        return "error"
    if name == "web_search":
        return "web_search_result"
    if name == "web_fetch":
        return "web_fetch_result"
    if name == "image_generate":
        return "image_generation"
    return "tool_result"


def _base_fact(
    event: RunEventRecord,
    *,
    kind: str,
    status: str,
    **extra: Any,
) -> dict[str, Any]:
    """Return the shared structured fact shape."""

    fact = {
        "id": f"fact_{event.event_id}",
        "kind": kind,
        "status": status,
        "source_event_type": event.event_type,
        "evidence_event_ids": [event.event_id],
    }
    fact.update({key: value for key, value in extra.items() if value not in (None, "", {})})
    return fact


def _tool_call_name(event: RunEventRecord) -> str:
    """Return a public tool name from a tool-call-started event."""

    tool_call = event.payload.get("tool_call")
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "tool")
    return "tool"


def _tool_result_name(event: RunEventRecord) -> str:
    """Return a public tool name from a tool terminal event."""

    tool_result = event.payload.get("tool_result")
    if isinstance(tool_result, dict):
        return str(tool_result.get("name") or "tool")
    return "tool"


def _hook_projection(event: KlaraEvent) -> ProjectedRunEvent | None:
    """Return compact hook placement projection when the event is a hook event."""

    placement_by_prefix = {
        "user_prompt_submit": "UserPromptSubmit",
        "pre_tool_use": "PreToolUse",
        "post_tool_use": "PostToolUse",
        "pre_compact": "PreCompact",
        "stop": "Stop",
    }
    prefix, _, suffix = event.type.partition(".")
    placement = placement_by_prefix.get(prefix)
    if placement is None or suffix not in {"started", "completed"}:
        return None
    payload: dict[str, Any] = {
        "placement": placement,
        "core_event_type": event.type,
        "turn_index": event.payload.get("turn_index"),
    }
    if "allowed" in event.payload:
        payload["allowed"] = event.payload.get("allowed")
    if "reason" in event.payload:
        payload["reason"] = event.payload.get("reason")
    return ProjectedRunEvent(
        event_type=(
            "hook_placement_started"
            if suffix == "started"
            else "hook_placement_completed"
        ),
        message=f"{placement} hook {suffix}.",
        payload=payload,
    )


def _permission_projection(event: KlaraEvent) -> ProjectedRunEvent | None:
    """Project a sanitized permission decision carried by PreToolUse metadata."""

    if event.type != "pre_tool_use.completed":
        return None
    metadata = _dict_payload(event.payload.get("metadata"))
    permission = _dict_payload(metadata.get("permission"))
    if not permission:
        return None
    action = _dict_payload(permission.get("action"))
    safe_action = {
        key: action.get(key)
        for key in (
            "tool_name",
            "capability",
            "side_effect",
            "resource_type",
            "resource",
            "risk",
            "destructive",
            "externally_consequential",
        )
        if key in action
    }
    allowed = bool(permission.get("allowed", False))
    reason = str(permission.get("reason") or "permission_denied")
    requested = bool(permission.get("request_id")) and not allowed
    if requested:
        event_type: RunEventType = "permission.requested"
        message = "Approval is required before this action can run."
    elif allowed:
        event_type = "permission.allowed"
        message = "Permission policy allowed this action."
    else:
        event_type = "permission.denied"
        message = "Permission policy denied this action."
    return ProjectedRunEvent(
        event_type=event_type,
        message=message,
        payload={
            "schema_version": "klara.permission-event.v1",
            "allowed": allowed,
            "reason": reason,
            "request_id": permission.get("request_id"),
            "grant_id": permission.get("grant_id"),
            "effect": permission.get("effect"),
            "action": safe_action,
            "raw_arguments_exposed": False,
        },
    )


def _compact_tool_result(tool_result: dict[str, Any]) -> dict[str, Any]:
    """Remove full content from frontend-facing tool result projection."""

    compact = {
        key: value
        for key, value in tool_result.items()
        if key != "content"
    }
    structured_summary = _structured_tool_summary(
        str(tool_result.get("name") or "tool"),
        tool_result.get("content"),
    )
    if structured_summary:
        compact["structured_summary"] = structured_summary
    return compact


def _structured_tool_summary(name: str, content: object) -> dict[str, Any]:
    """Return a safe structured summary from a JSON tool observation."""

    if not isinstance(content, str) or not content.strip().startswith("{"):
        return {}
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    if name == "web_search":
        results = value.get("results")
        result_items = results if isinstance(results, list) else []
        return {
            "provider": _string_or_none(value.get("provider")),
            "result_count": _int_or_none(value.get("result_count")),
            "truncated": bool(value.get("truncated", False)),
            "evidence_status": _string_or_none(value.get("evidence_status")),
            "search_id": _string_or_none(value.get("search_id")),
            "freshness_enforced": bool(value.get("freshness_enforced", False)),
            "candidate_count": len(result_items),
            "top_domains": _top_domains(result_items),
            "top_titles": _top_titles(result_items),
        }
    if name == "web_fetch":
        text = value.get("text")
        quality = value.get("extraction_quality")
        quality_score = (
            quality.get("score")
            if isinstance(quality, dict) and not isinstance(quality.get("score"), dict)
            else None
        )
        return {
            "source_id": _string_or_none(value.get("source_id")),
            "candidate_id": _string_or_none(value.get("candidate_id")),
            "status": _int_or_none(value.get("status")),
            "content_type": _string_or_none(value.get("content_type")),
            "title": _sanitize_preview(value.get("title")),
            "source_domain": _domain_from_url(
                _string_or_none(value.get("final_url"))
                or _string_or_none(value.get("url"))
            ),
            "text_length": len(text) if isinstance(text, str) else None,
            "truncated": bool(value.get("truncated", False)),
            "quality": quality_score,
            "no_relevant_terms_found": bool(value.get("no_relevant_terms_found", False)),
        }
    if name == "image_generate":
        images = value.get("images")
        return {
            "provider": _string_or_none(value.get("provider")),
            "model": _string_or_none(value.get("model")),
            "image_count": len(images) if isinstance(images, list) else _int_or_none(value.get("image_count")),
        }
    return {}


def _dict_payload(value: object) -> dict[str, Any]:
    """Return a dict payload when the event field is dictionary-shaped."""

    if isinstance(value, dict):
        return dict(value)
    return {}


def _top_domains(results: list[Any], *, limit: int = 3) -> list[str]:
    """Return unique source domains from search result cards."""

    domains: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        domain = _domain_from_url(
            _string_or_none(item.get("canonical_url"))
            or _string_or_none(item.get("url"))
        )
        if domain and domain not in domains:
            domains.append(domain)
        if len(domains) >= limit:
            break
    return domains


def _top_titles(results: list[Any], *, limit: int = 2) -> list[str]:
    """Return short public titles from search result cards."""

    titles: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = _sanitize_preview(item.get("title"), max_chars=90)
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def _domain_from_url(url: str | None) -> str | None:
    """Return only the public hostname from a URL."""

    if not url:
        return None
    hostname = urlparse(url).hostname
    if not hostname:
        return None
    return hostname.lower().removeprefix("www.")


def _fact_metrics(event: RunEventRecord) -> dict[str, Any]:
    """Return compact metrics for an activity fact."""

    raw_metrics = event.payload.get("metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
    public: dict[str, Any] = {}
    for key in (
        "duration_ms",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "token_source",
    ):
        value = metrics.get(key, event.payload.get(key))
        if value is not None:
            public[key] = value
    return public


def _sanitize_preview(value: object, *, max_chars: int = 180) -> str:
    """Return compact text with URLs removed for public activity facts."""

    if value is None:
        return ""
    text = " ".join(str(value).split())
    text = _redact_public_text(text)
    return text[:max_chars]


def _safe_provider_reasoning(value: object) -> str:
    """Return displayable provider reasoning summary text."""

    if not isinstance(value, str):
        return ""
    text = _redact_public_text(" ".join(value.split()))
    if not text:
        return ""
    lowered = text.lower()
    if any(term in lowered for term in ("raw payload", "api key", "secret", "sk-")):
        return ""
    return text


def _safe_public_activity(value: object) -> str:
    """Return displayable main-model public activity commentary."""

    if not isinstance(value, str):
        return ""
    text = _strip_internal_activity_labels(_redact_public_text(" ".join(value.split())))
    if not text:
        return ""
    lowered = text.lower()
    if any(
        term in lowered
        for term in (
            "chain-of-thought",
            "chain of thought",
            "hidden reasoning",
            "raw reasoning",
            "scratchpad",
            "raw payload",
            "api key",
            "secret",
            "password",
        )
    ):
        return ""
    return text


def _strip_internal_activity_labels(text: str) -> str:
    """Remove accidental public echoes of internal activity field labels."""

    pattern = (
        "(?i)\\b(?:update_activity(?:\\.text)?|activity_commentary|public_activity|"
        "assistant_activity(?:_delta)?)\\s*[:\\uff1a]\\s*"
    )
    return re.sub(pattern, "", text).strip()


def _activity_phase(value: object) -> str:
    """Return a known public activity phase."""

    if value in {"before_tool", "between_tools", "finalizing"}:
        return str(value)
    return "before_tool"


def _activity_status(value: object) -> str:
    """Return a known public activity update status."""

    if value in {"running", "completed", "failed"}:
        return str(value)
    return "completed"


def _redact_public_text(text: str) -> str:
    """Redact URLs and common secret-shaped values from public summaries."""

    redacted = re.sub(r"https?://\S+", "[url]", text)
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        redacted,
    )
    redacted = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "sk-[redacted]", redacted)
    return redacted


def _string_or_none(value: object) -> str | None:
    """Return a string value when present."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _usage_payload(usage: dict[str, Any]) -> dict[str, int | None]:
    """Normalize common OpenAI-compatible usage field names."""

    prompt = _int_or_none(_first_present(usage, "prompt_tokens", "input_tokens"))
    completion = _int_or_none(
        _first_present(usage, "completion_tokens", "output_tokens")
    )
    total = _int_or_none(_first_present(usage, "total_tokens"))
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _token_source(
    metrics: dict[str, Any],
    usage_fields: dict[str, int | None],
) -> str:
    """Return a stable token-source label for one projected LLM call."""

    source = metrics.get("token_source")
    if source in {"reported", "estimated", "unknown"}:
        return str(source)
    if any(value is not None for value in usage_fields.values()):
        return "reported"
    return "unknown"


def _first_present(usage: dict[str, Any], *keys: str) -> Any:
    """Return the first present value from a usage dictionary."""

    for key in keys:
        if key in usage:
            return usage[key]
    return None


def _int_or_none(value: Any) -> int | None:
    """Return an integer token count when the value is numeric."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
