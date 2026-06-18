"""Model-visible evidence guards for web search and fetch observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json

from klara.core.messages import KlaraMessage


WEB_SEARCH_TOOL_NAME = "web_search"
WEB_FETCH_TOOL_NAME = "web_fetch"

WEB_SEARCH_FETCH_GUARD_MESSAGE = (
    "<runtime_tool_guard>\n"
    "The last web_search observation contains candidate snippets only. Before "
    "writing a web-backed factual final answer, call web_fetch on one relevant "
    "reliable URL from those results. If no result is suitable, say that source "
    "evidence is insufficient instead of answering from snippets or memory.\n"
    "</runtime_tool_guard>"
)

PREFERRED_SOURCE_FETCH_GUARD_TEMPLATE = (
    "<runtime_preferred_source_guard>\n"
    "The last web_search observation included preferred_source URLs, but no "
    "preferred_source page has been fetched yet. Before writing a web-backed "
    "factual final answer, call web_fetch on one relevant preferred_source URL. "
    "Available preferred_source URLs: {urls}\n"
    "</runtime_preferred_source_guard>"
)

SOURCE_QUALITY_GUARD_TEMPLATE = (
    "<runtime_source_guard>\n"
    "{date_context} "
    "You have fetched both preferred_source and candidate_source pages. Build "
    "the final answer primarily from fetched preferred_source observations. "
    "Use candidate_source pages only as secondary context; do not merge their "
    "claims into the answer when they conflict with or are absent from the "
    "preferred_source text. Do not present stale future-tense page copy as "
    "current fact. Cite the exact URLs used and mention unresolved conflicts "
    "or uncertainty.\n"
    "</runtime_source_guard>"
)

WEB_SYNTHESIS_GUARD_TEMPLATE = (
    "<runtime_web_synthesis_guard>\n"
    "{date_context} "
    "Fetched pages can mix current reports, navigation, ads, stale schedule "
    "previews, and older future-tense copy. Before writing the final answer, "
    "use only fetched text that directly answers the user's request. Compare "
    "dated claims against the current date; do not state an event as upcoming "
    "if that date has already passed. If this comparison changes a page's "
    "future-tense wording, trust the date comparison over the page wording. "
    "Cite the exact URLs used and say when the fetched evidence is incomplete "
    "or mixed.\n"
    "</runtime_web_synthesis_guard>"
)


@dataclass(frozen=True)
class WebEvidenceGuard:
    """Delay final answers until web evidence is fetched and source-ranked."""

    current_date: date | None = None
    timezone_name: str = ""

    def apply(
        self,
        messages: tuple[KlaraMessage, ...],
    ) -> tuple[KlaraMessage, ...] | None:
        """Return a guarded transcript when web evidence is incomplete."""

        message_list = list(messages)
        if _needs_web_fetch_before_final(message_list):
            return (
                *message_list,
                KlaraMessage(role="user", content=WEB_SEARCH_FETCH_GUARD_MESSAGE),
            )

        preferred_source_urls = _preferred_source_urls_requiring_fetch(message_list)
        if preferred_source_urls:
            return (
                *message_list,
                KlaraMessage(
                    role="user",
                    content=PREFERRED_SOURCE_FETCH_GUARD_TEMPLATE.format(
                        urls=", ".join(preferred_source_urls[:3])
                    ),
                ),
            )

        if _needs_source_quality_guard_before_final(message_list):
            masked_messages = _mask_candidate_web_fetch_observations(message_list)
            return (
                *masked_messages,
                KlaraMessage(
                    role="user",
                    content=SOURCE_QUALITY_GUARD_TEMPLATE.format(
                        date_context=self._date_context()
                    ),
                ),
            )

        if _needs_web_synthesis_guard_before_final(message_list):
            return (
                *message_list,
                KlaraMessage(
                    role="user",
                    content=WEB_SYNTHESIS_GUARD_TEMPLATE.format(
                        date_context=self._date_context()
                    ),
                ),
            )

        return None

    def _date_context(self) -> str:
        """Return explicit date guidance for web source synthesis."""

        if self.current_date is None:
            return (
                "Use the conversation date from runtime_context as the current "
                "date."
            )
        timezone_label = f" in {self.timezone_name}" if self.timezone_name else ""
        return (
            f"The current date for this run is {self.current_date.isoformat()}"
            f"{timezone_label}. Any event date before "
            f"{self.current_date.isoformat()} is already in the past."
        )


def _needs_web_fetch_before_final(messages: list[KlaraMessage]) -> bool:
    """Return whether candidate web-search snippets still need source text."""

    pending_search = False
    for message in messages:
        if message.role != "tool":
            continue
        if message.name == WEB_SEARCH_TOOL_NAME:
            pending_search = _web_search_observation_needs_fetch(message.content)
            continue
        if message.name == WEB_FETCH_TOOL_NAME:
            pending_search = False
    return pending_search


def _preferred_source_urls_requiring_fetch(messages: list[KlaraMessage]) -> list[str]:
    """Return preferred source URLs that should be fetched before final."""

    if any(
        message.role == "user"
        and "<runtime_preferred_source_guard>" in message.content
        for message in messages
    ):
        return []
    preferred_urls: list[str] = []
    fetched_preferred = False
    for message in messages:
        if message.role != "tool":
            continue
        if message.name == WEB_SEARCH_TOOL_NAME:
            preferred_urls = _web_search_preferred_source_urls(message.content)
            fetched_preferred = False
            continue
        if (
            message.name == WEB_FETCH_TOOL_NAME
            and _web_fetch_source_tier(message.content) == "preferred_source"
        ):
            fetched_preferred = True
    if preferred_urls and not fetched_preferred:
        return preferred_urls
    return []


def _needs_source_quality_guard_before_final(messages: list[KlaraMessage]) -> bool:
    """Return whether mixed-quality fetched sources need a final guard."""

    if any(
        message.role == "user" and "<runtime_source_guard>" in message.content
        for message in messages
    ):
        return False
    has_preferred = False
    has_candidate = False
    for message in messages:
        if message.role != "tool" or message.name != WEB_FETCH_TOOL_NAME:
            continue
        tier = _web_fetch_source_tier(message.content)
        if tier == "preferred_source":
            has_preferred = True
        elif tier == "candidate_source":
            has_candidate = True
    return has_preferred and has_candidate


def _needs_web_synthesis_guard_before_final(messages: list[KlaraMessage]) -> bool:
    """Return whether fetched web text needs a final synthesis guard."""

    if any(
        message.role == "user"
        and (
            "<runtime_web_synthesis_guard>" in message.content
            or "<runtime_source_guard>" in message.content
        )
        for message in messages
    ):
        return False
    return any(
        message.role == "tool" and message.name == WEB_FETCH_TOOL_NAME
        for message in messages
    )


def _web_search_observation_needs_fetch(content: str) -> bool:
    """Return whether a web-search observation is only candidate evidence."""

    payload = _json_object(content)
    return payload.get("evidence_status") == "candidate_snippets_only"


def _web_fetch_source_tier(content: str) -> str:
    """Return source_tier from a web-fetch observation when present."""

    tier = _json_object(content).get("source_tier")
    return tier if isinstance(tier, str) else ""


def _web_search_preferred_source_urls(content: str) -> list[str]:
    """Return preferred source URLs advertised by a web-search observation."""

    results = _json_object(content).get("results")
    if not isinstance(results, list):
        return []
    urls: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("source_tier") != "preferred_source":
            continue
        url = result.get("url")
        if isinstance(url, str) and url:
            urls.append(url)
    return urls


def _mask_candidate_web_fetch_observations(
    messages: list[KlaraMessage],
) -> list[KlaraMessage]:
    """Hide candidate-source page text before preferred-source final synthesis."""

    masked_messages: list[KlaraMessage] = []
    for message in messages:
        if (
            message.role == "tool"
            and message.name == WEB_FETCH_TOOL_NAME
            and _web_fetch_source_tier(message.content) == "candidate_source"
        ):
            masked_messages.append(
                KlaraMessage(
                    role=message.role,
                    content=_masked_candidate_web_fetch_content(message.content),
                    name=message.name,
                    tool_call_id=message.tool_call_id,
                    tool_calls=message.tool_calls,
                )
            )
            continue
        masked_messages.append(message)
    return masked_messages


def _masked_candidate_web_fetch_content(content: str) -> str:
    """Return a compact candidate-source placeholder without page facts."""

    payload = _json_object(content)
    return json.dumps(
        {
            "url": payload.get("url", ""),
            "final_url": payload.get("final_url", ""),
            "title": payload.get("title", ""),
            "source_tier": "candidate_source",
            "text": (
                "[hidden by runtime_source_guard because a preferred_source "
                "page is available]"
            ),
            "source_use_policy": (
                "Do not use candidate_source page facts for scores or results "
                "when preferred_source evidence is available."
            ),
        },
        ensure_ascii=False,
    )


def _json_object(content: str) -> dict[str, object]:
    """Parse JSON tool content into an object, returning empty on mismatch."""

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
