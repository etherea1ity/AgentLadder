"""Model-visible evidence guards for web search and fetch observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re

from klara.core.messages import KlaraMessage


WEB_SEARCH_TOOL_NAME = "web_search"
WEB_FETCH_TOOL_NAME = "web_fetch"

WEB_SEARCH_REQUIRED_GUARD_MESSAGE = (
    "<runtime_web_search_required_guard>\n"
    "The latest user request asks for current, time-sensitive, or web-backed "
    "facts. Do not ask the user whether to search. Before writing a final "
    "answer, call web_search with a focused query for the requested facts. "
    "If current evidence remains insufficient after searching, say that "
    "clearly in the final answer.\n"
    "</runtime_web_search_required_guard>"
)

WEB_SEARCH_FAILURE_GUARD_MESSAGE = (
    "<runtime_web_search_failure_guard>\n"
    "The web_search calls in this user turn failed before returning usable "
    "source candidates, and no web_fetch evidence is available. Do not answer "
    "current facts from memory, and do not claim the event or matches have not "
    "started unless fetched evidence says so. Either call web_search one final "
    "time with a simpler query and no freshness/language filters, or write a "
    "final answer that says current web evidence could not be retrieved and "
    "the requested facts cannot be verified in this run.\n"
    "</runtime_web_search_failure_guard>"
)

WEB_SEARCH_FETCH_GUARD_MESSAGE = (
    "<runtime_tool_guard>\n"
    "The last web_search observation contains candidate snippets only. Before "
    "writing a web-backed factual final answer, call web_fetch on one relevant "
    "reliable URL from those results. If no result is suitable, say that source "
    "evidence is insufficient instead of answering from snippets or memory.\n"
    "</runtime_tool_guard>"
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
    "Do not invent quotes, numeric ratings, awards, player statistics, or "
    "per-item commentary that the fetched text does not state. If the user "
    "asked for comprehensive coverage but fetched evidence only supports some "
    "items in detail, separate the complete factual list from source-limited "
    "commentary and say which parts are incomplete. "
    "Cite the exact URLs used and say when the fetched evidence is incomplete "
    "or mixed.\n"
    "</runtime_web_synthesis_guard>"
)

TEMPORAL_CONSISTENCY_GUARD_TEMPLATE = (
    "<runtime_temporal_consistency_guard>\n"
    "{date_context} "
    "Your draft says the event or matches have not started, but fetched or "
    "searched web evidence contains dates on or before the current date. Do "
    "not repeat a blanket 'not started' claim. Reconcile the dated evidence: "
    "if sources are incomplete or possibly unreliable, say the source quality "
    "is mixed; if result facts are available, provide those facts and label "
    "unsupported commentary as unavailable.\n"
    "</runtime_temporal_consistency_guard>"
)


@dataclass(frozen=True)
class WebEvidenceGuard:
    """Delay final answers until web evidence is searched, fetched, and checked."""

    current_date: date | None = None
    timezone_name: str = ""

    def apply(
        self,
        messages: tuple[KlaraMessage, ...],
    ) -> tuple[KlaraMessage, ...] | None:
        """Return a guarded transcript when web evidence is incomplete."""

        message_list = list(messages)
        if _needs_web_search_before_final(message_list):
            return (
                *message_list,
                KlaraMessage(role="user", content=WEB_SEARCH_REQUIRED_GUARD_MESSAGE),
            )

        if _needs_web_search_failure_guard_before_final(message_list):
            return (
                *message_list,
                KlaraMessage(role="user", content=WEB_SEARCH_FAILURE_GUARD_MESSAGE),
            )

        if _needs_web_fetch_before_final(message_list):
            return (
                *message_list,
                KlaraMessage(role="user", content=WEB_SEARCH_FETCH_GUARD_MESSAGE),
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

        if _needs_temporal_consistency_guard(message_list, self.current_date):
            return (
                *message_list,
                KlaraMessage(
                    role="user",
                    content=TEMPORAL_CONSISTENCY_GUARD_TEMPLATE.format(
                        date_context=self._date_context()
                    ),
                ),
            )

        return None

    def fallback_answer(self, messages: tuple[KlaraMessage, ...]) -> str | None:
        """Return a safe final answer after repeated ignored web guards."""

        message_list = list(messages)
        if not _needs_failed_web_search_safe_fallback(message_list):
            return None
        if _latest_real_user_looks_chinese(message_list):
            return (
                "我这轮已经尝试检索当前网页证据，但 web_search 没有返回可用的"
                "来源结果，因此不能可靠整理世界杯到目前为止的每场赛果、"
                "比赛总结、精彩评论或球员表现。也不能在没有网页证据时推断"
                "赛事是否已经开始。请稍后重试，或给我一个可访问的赛程/战报"
                "来源，我可以基于来源继续整理。"
            )
        return (
            "I tried to retrieve current web evidence, but web_search did not "
            "return usable source results in this run. I cannot reliably "
            "summarize match results, commentary, or player performances, and "
            "I should not infer whether the tournament has started without "
            "source evidence. Please try again later or provide an accessible "
            "source to summarize."
        )

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


def _needs_web_search_before_final(messages: list[KlaraMessage]) -> bool:
    """Return whether a current-facts request needs an initial web search."""

    latest_user_index, latest_user_content = _latest_real_user_message(messages)
    if latest_user_index < 0:
        return False
    if not _looks_time_sensitive_web_request(latest_user_content):
        return False

    for message in messages[latest_user_index + 1 :]:
        if (
            message.role == "user"
            and "<runtime_web_search_required_guard>" in message.content
        ):
            return False
        if message.role == "tool" and message.name in {
            WEB_SEARCH_TOOL_NAME,
            WEB_FETCH_TOOL_NAME,
        }:
            return False
    return True


def _latest_real_user_message(messages: list[KlaraMessage]) -> tuple[int, str]:
    """Return index and content for the latest non-runtime user message."""

    latest_user_index = -1
    latest_user_content = ""
    for index, message in enumerate(messages):
        if message.role != "user" or _is_runtime_guard_message(message.content):
            continue
        latest_user_index = index
        latest_user_content = message.content
    return latest_user_index, latest_user_content


def _is_runtime_guard_message(content: str) -> bool:
    """Return whether a user message was injected by runtime guard policy."""

    return content.lstrip().startswith("<runtime_")


def _looks_time_sensitive_web_request(content: str) -> bool:
    """Return whether the user is asking for facts that should be searched."""

    lowered = content.lower()
    recency_terms = (
        "latest",
        "current",
        "today",
        "so far",
        "to date",
        "as of",
        "right now",
        "live",
        "news",
        "recent",
    )
    factual_domains = (
        "score",
        "scores",
        "schedule",
        "fixture",
        "fixtures",
        "result",
        "results",
        "standings",
        "match",
        "matches",
        "world cup",
        "player performance",
        "match summary",
    )
    chinese_recency_terms = (
        "最新",
        "当前",
        "目前",
        "到目前",
        "截至",
        "今天",
        "实时",
        "刚刚",
        "现在",
    )
    chinese_factual_domains = (
        "赛果",
        "比分",
        "赛程",
        "战报",
        "比赛",
        "比赛总结",
        "球员表现",
        "世界杯",
        "精彩评论",
        "每一场",
    )

    has_recency = any(term in lowered for term in recency_terms) or any(
        term in content for term in chinese_recency_terms
    )
    has_fact_domain = any(term in lowered for term in factual_domains) or any(
        term in content for term in chinese_factual_domains
    )
    return has_recency and has_fact_domain


def _needs_web_search_failure_guard_before_final(
    messages: list[KlaraMessage],
) -> bool:
    """Return whether failed searches need an evidence-boundary guard."""

    latest_user_index, latest_user_content = _latest_real_user_message(messages)
    if latest_user_index < 0:
        return False
    if not _looks_time_sensitive_web_request(latest_user_content):
        return False

    guard_count = sum(
        1
        for message in messages[latest_user_index + 1 :]
        if (
            message.role == "user"
            and "<runtime_web_search_failure_guard>" in message.content
        )
    )
    if guard_count >= 2:
        return False

    saw_failed_search = False
    for message in messages[latest_user_index + 1 :]:
        if message.role != "tool":
            continue
        if message.name == WEB_FETCH_TOOL_NAME:
            return False
        if message.name != WEB_SEARCH_TOOL_NAME:
            continue
        if _web_search_observation_needs_fetch(message.content):
            return False
        saw_failed_search = True

    if not saw_failed_search:
        return False
    if guard_count == 0:
        return True
    return _assistant_claims_not_started(_last_assistant_content(messages))


def _needs_failed_web_search_safe_fallback(messages: list[KlaraMessage]) -> bool:
    """Return whether repeated failed-search guards should become final."""

    latest_user_index, latest_user_content = _latest_real_user_message(messages)
    if latest_user_index < 0:
        return False
    if not _looks_time_sensitive_web_request(latest_user_content):
        return False
    guard_count = sum(
        1
        for message in messages[latest_user_index + 1 :]
        if (
            message.role == "user"
            and "<runtime_web_search_failure_guard>" in message.content
        )
    )
    if guard_count < 2:
        return False
    if not _assistant_claims_not_started(_last_assistant_content(messages)):
        return False

    saw_failed_search = False
    for message in messages[latest_user_index + 1 :]:
        if message.role != "tool":
            continue
        if message.name == WEB_FETCH_TOOL_NAME:
            return False
        if message.name != WEB_SEARCH_TOOL_NAME:
            continue
        if _web_search_observation_needs_fetch(message.content):
            return False
        saw_failed_search = True
    return saw_failed_search


def _latest_real_user_looks_chinese(messages: list[KlaraMessage]) -> bool:
    """Return whether the latest real user message contains CJK text."""

    _, content = _latest_real_user_message(messages)
    return any("\u4e00" <= character <= "\u9fff" for character in content)


def _needs_web_fetch_before_final(messages: list[KlaraMessage]) -> bool:
    """Return whether candidate web-search snippets still need source text."""

    pending_search = False
    guard_after_pending_search = False
    for message in messages:
        if (
            message.role == "user"
            and "<runtime_tool_guard>" in message.content
            and pending_search
        ):
            guard_after_pending_search = True
            continue
        if message.role != "tool":
            continue
        if message.name == WEB_SEARCH_TOOL_NAME:
            pending_search = _web_search_observation_needs_fetch(message.content)
            guard_after_pending_search = False
            continue
        if message.name == WEB_FETCH_TOOL_NAME:
            pending_search = False
            guard_after_pending_search = False
    return pending_search and not guard_after_pending_search


def _needs_web_synthesis_guard_before_final(messages: list[KlaraMessage]) -> bool:
    """Return whether fetched web text needs a final synthesis guard."""

    needs_guard = False
    for message in messages:
        if message.role == "tool" and message.name == WEB_FETCH_TOOL_NAME:
            needs_guard = True
            continue
        if message.role != "user":
            continue
        if "<runtime_web_synthesis_guard>" in message.content:
            needs_guard = False
    return needs_guard


def _needs_temporal_consistency_guard(
    messages: list[KlaraMessage],
    current_date: date | None,
) -> bool:
    """Return whether a not-started draft conflicts with dated web evidence."""

    if current_date is None:
        return False
    if any(
        message.role == "user"
        and "<runtime_temporal_consistency_guard>" in message.content
        for message in messages
    ):
        return False

    draft = _last_assistant_content(messages)
    if not _assistant_claims_not_started(draft):
        return False
    return _web_observations_contain_date_on_or_before(messages, current_date)


def _last_assistant_content(messages: list[KlaraMessage]) -> str:
    """Return the latest assistant content in the transcript."""

    for message in reversed(messages):
        if message.role == "assistant":
            return message.content
    return ""


def _assistant_claims_not_started(content: str) -> bool:
    """Return whether assistant draft says the requested event has not started."""

    lowered = content.lower()
    return any(
        phrase in lowered
        for phrase in (
            "尚未开始",
            "尚未正式开赛",
            "未正式开赛",
            "没有实际进行过的比赛",
            "还没开始",
            "还未开始",
            "还没有任何比赛",
            "第一声哨响",
            "has not started",
            "not started yet",
            "no matches have been played",
        )
    )


def _web_observations_contain_date_on_or_before(
    messages: list[KlaraMessage],
    current_date: date,
) -> bool:
    """Return whether web observations contain a current-or-past date."""

    for message in messages:
        if message.role != "tool" or message.name not in {
            WEB_SEARCH_TOOL_NAME,
            WEB_FETCH_TOOL_NAME,
        }:
            continue
        for observed_date in _dates_in_text(message.content):
            if observed_date <= current_date:
                return True
    return False


def _dates_in_text(text: str) -> list[date]:
    """Return common web date formats parsed from text."""

    parsed: list[date] = []
    for match in re.finditer(r"(\d{4})[年./-]\s*(\d{1,2})[月./-]\s*(\d{1,2})", text):
        parsed_date = _safe_date(match.group(1), match.group(2), match.group(3))
        if parsed_date is not None:
            parsed.append(parsed_date)

    month_names = (
        "jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|"
        "aug|august|sep|sept|september|oct|october|nov|november|dec|december"
    )
    for match in re.finditer(
        rf"\b({month_names})\s+(\d{{1,2}}),\s*(\d{{4}})\b",
        text,
        flags=re.IGNORECASE,
    ):
        month = _month_number(match.group(1))
        parsed_date = _safe_date(match.group(3), str(month), match.group(2))
        if parsed_date is not None:
            parsed.append(parsed_date)

    for match in re.finditer(
        rf"\b(\d{{1,2}})\s+({month_names})\s+(\d{{4}})\b",
        text,
        flags=re.IGNORECASE,
    ):
        month = _month_number(match.group(2))
        parsed_date = _safe_date(match.group(3), str(month), match.group(1))
        if parsed_date is not None:
            parsed.append(parsed_date)
    return parsed


def _month_number(month_name: str) -> int:
    """Return a month number for an English month name or abbreviation."""

    key = month_name.lower()[:3]
    return {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }.get(key, 0)


def _safe_date(year: str, month: str, day: str) -> date | None:
    """Return a date object, ignoring invalid calendar dates."""

    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _web_search_observation_needs_fetch(content: str) -> bool:
    """Return whether a web-search observation is only candidate evidence."""

    payload = _json_object(content)
    return payload.get("evidence_status") == "candidate_snippets_only"


def _json_object(content: str) -> dict[str, object]:
    """Parse JSON tool content into an object, returning empty on mismatch."""

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
