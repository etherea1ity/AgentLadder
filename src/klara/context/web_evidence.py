"""Model-visible evidence guards for web search and fetch observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re

from klara.core.messages import KlaraMessage
from klara.services.web.source_quality import (
    PREFERRED_CURRENT_SPORTS_QUALITIES,
    classify_source,
)


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

CURRENT_SPORTS_EVIDENCE_GUARD_TEMPLATE = (
    "<runtime_current_sports_evidence_guard>\n"
    "{date_context} "
    "The latest user request asks for current sports results or fixtures. "
    "Search candidates and snippets are not facts. Fixtures are not results. "
    "A scheduled match with no fetched verified score is not 0:0. Before "
    "writing concrete scores, standings, match summaries, or player "
    "performance claims, fetch at least two relevant sources unless an "
    "official FIFA page directly contains the needed facts. At least one "
    "source should be official, wire, or established sports media. Aggregator-"
    "only evidence is not enough for concrete scores. If live status is not "
    "verified, say scheduled, in progress, or unverified instead of inventing "
    "a score.\n"
    "</runtime_current_sports_evidence_guard>"
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

        if _needs_current_sports_evidence_guard_before_final(message_list):
            return (
                *message_list,
                KlaraMessage(
                    role="user",
                    content=CURRENT_SPORTS_EVIDENCE_GUARD_TEMPLATE.format(
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
                "\u6211\u8fd9\u8f6e\u5df2\u7ecf\u5c1d\u8bd5\u68c0\u7d22"
                "\u5f53\u524d\u7f51\u9875\u8bc1\u636e\uff0c\u4f46 web_search "
                "\u6ca1\u6709\u8fd4\u56de\u53ef\u7528\u7684\u6765\u6e90"
                "\u7ed3\u679c\uff0c\u56e0\u6b64\u4e0d\u80fd\u53ef\u9760"
                "\u6574\u7406\u4e16\u754c\u676f\u5230\u76ee\u524d\u4e3a"
                "\u6b62\u7684\u6bcf\u573a\u8d5b\u679c\u3001\u6bd4\u8d5b"
                "\u603b\u7ed3\u3001\u7cbe\u5f69\u8bc4\u8bba\u6216"
                "\u7403\u5458\u8868\u73b0\u3002\u4e5f\u4e0d\u80fd\u5728"
                "\u6ca1\u6709\u7f51\u9875\u8bc1\u636e\u65f6\u63a8\u65ad"
                "\u8d5b\u4e8b\u662f\u5426\u5df2\u7ecf\u5f00\u59cb\u3002"
                "\u8bf7\u7a0d\u540e\u91cd\u8bd5\uff0c\u6216\u7ed9\u6211"
                "\u4e00\u4e2a\u53ef\u8bbf\u95ee\u7684\u8d5b\u7a0b/"
                "\u6218\u62a5\u6765\u6e90\uff0c\u6211\u53ef\u4ee5\u57fa"
                "\u4e8e\u6765\u6e90\u7ee7\u7eed\u6574\u7406\u3002"
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
        "\u6700\u65b0",
        "\u5f53\u524d",
        "\u76ee\u524d",
        "\u5230\u76ee\u524d",
        "\u622a\u81f3",
        "\u4eca\u5929",
        "\u5b9e\u65f6",
        "\u521a\u521a",
        "\u73b0\u5728",
    )
    chinese_factual_domains = (
        "\u8d5b\u679c",
        "\u6bd4\u5206",
        "\u8d5b\u7a0b",
        "\u6218\u62a5",
        "\u6bd4\u8d5b",
        "\u6bd4\u8d5b\u603b\u7ed3",
        "\u7403\u5458\u8868\u73b0",
        "\u4e16\u754c\u676f",
        "\u7cbe\u5f69\u8bc4\u8bba",
        "\u6bcf\u4e00\u573a",
    )

    has_recency = any(term in lowered for term in recency_terms) or any(
        term in content for term in chinese_recency_terms
    )
    has_fact_domain = any(term in lowered for term in factual_domains) or any(
        term in content for term in chinese_factual_domains
    )
    return has_recency and has_fact_domain


def _needs_current_sports_evidence_guard_before_final(
    messages: list[KlaraMessage],
) -> bool:
    """Return whether current sports claims need stronger fetched evidence."""

    latest_user_index, latest_user_content = _latest_real_user_message(messages)
    if latest_user_index < 0:
        return False
    if not _looks_current_sports_request(latest_user_content):
        return False
    if _current_sports_guard_is_current(messages, latest_user_index):
        return False

    draft = _last_assistant_content(messages)
    if not draft or _draft_is_source_limited(draft):
        return False

    evidence = _current_sports_evidence(messages, latest_user_index)
    if _draft_has_start_date_conflict(draft, evidence["combined_text"]):
        return True
    if _draft_claims_unverified_zero_zero(draft, evidence["combined_text"]):
        return True

    draft_scores = _score_patterns(draft)
    concrete_claim = bool(draft_scores) or _draft_has_result_language(draft)
    if not concrete_claim:
        return False
    if evidence["fetch_count"] == 0 and evidence["search_count"] > 0:
        return True

    if not evidence["has_preferred_source"]:
        return True
    if draft_scores and not _all_scores_supported(draft_scores, evidence["combined_text"]):
        return True
    if (
        _looks_comprehensive_current_sports_request(latest_user_content)
        and not evidence["has_official_direct_result"]
        and evidence["fetch_count"] < 2
    ):
        return True
    return False


def _looks_current_sports_request(content: str) -> bool:
    """Return whether the user asks for current sports facts."""

    if not _looks_time_sensitive_web_request(content):
        return False
    lowered = content.lower()
    sports_terms = (
        "world cup",
        "fifa",
        "football",
        "soccer",
        "match",
        "matches",
        "fixture",
        "fixtures",
        "score",
        "scores",
        "standing",
        "standings",
    )
    chinese_sports_terms = (
        "\u4e16\u754c\u676f",
        "\u8db3\u7403",
        "\u6bd4\u8d5b",
        "\u8d5b\u7a0b",
        "\u8d5b\u679c",
        "\u6bd4\u5206",
    )
    return any(term in lowered for term in sports_terms) or any(
        term in content for term in chinese_sports_terms
    )


def _looks_comprehensive_current_sports_request(content: str) -> bool:
    """Return whether the request asks for broad per-match coverage."""

    lowered = content.lower()
    terms = ("each", "every", "all", "so far", "to date", "complete")
    chinese_terms = (
        "\u6bcf\u4e00\u573a",
        "\u6240\u6709",
        "\u5168\u90e8",
        "\u5230\u76ee\u524d",
        "\u603b\u7ed3",
    )
    return any(term in lowered for term in terms) or any(
        term in content for term in chinese_terms
    )


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
            "\u5c1a\u672a\u5f00\u59cb",
            "\u5c1a\u672a\u6b63\u5f0f\u5f00\u8d5b",
            "\u672a\u6b63\u5f0f\u5f00\u8d5b",
            "\u6ca1\u6709\u5b9e\u9645\u8fdb\u884c\u8fc7\u7684\u6bd4\u8d5b",
            "\u8fd8\u6ca1\u5f00\u59cb",
            "\u8fd8\u672a\u5f00\u59cb",
            "\u8fd8\u6ca1\u6709\u4efb\u4f55\u6bd4\u8d5b",
            "\u7b2c\u4e00\u58f0\u54e8\u54cd",
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
    for match in re.finditer(
        r"(\d{4})[\u5e74./-]\s*(\d{1,2})[\u6708./-]\s*(\d{1,2})",
        text,
    ):
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


def _current_sports_guard_is_current(
    messages: list[KlaraMessage],
    latest_user_index: int,
) -> bool:
    """Return whether a current-sports guard already follows the latest web tool."""

    latest_tool_index = -1
    latest_guard_index = -1
    for index, message in enumerate(messages[latest_user_index + 1 :], start=latest_user_index + 1):
        if message.role == "tool" and message.name in {
            WEB_SEARCH_TOOL_NAME,
            WEB_FETCH_TOOL_NAME,
        }:
            latest_tool_index = index
        if (
            message.role == "user"
            and "<runtime_current_sports_evidence_guard>" in message.content
        ):
            latest_guard_index = index
    return latest_guard_index > latest_tool_index


def _current_sports_evidence(
    messages: list[KlaraMessage],
    latest_user_index: int,
) -> dict[str, object]:
    """Summarize fetched evidence quality for current sports requests."""

    fetch_count = 0
    search_count = 0
    has_preferred_source = False
    has_official_direct_result = False
    fetched_texts: list[str] = []
    for message in messages[latest_user_index + 1 :]:
        if message.role == "tool" and message.name == WEB_SEARCH_TOOL_NAME:
            search_count += 1
            continue
        if message.role != "tool" or message.name != WEB_FETCH_TOOL_NAME:
            continue
        payload = _json_object(message.content)
        fetch_count += 1
        url = str(payload.get("final_url") or payload.get("url") or "")
        title = str(payload.get("title") or "")
        text = str(payload.get("text") or "")
        fetched_texts.append(text)
        source_quality = str(payload.get("source_quality") or classify_source(url, title))
        if source_quality in PREFERRED_CURRENT_SPORTS_QUALITIES:
            has_preferred_source = True
        if source_quality == "official" and _text_contains_result_evidence(text):
            has_official_direct_result = True
    return {
        "fetch_count": fetch_count,
        "search_count": search_count,
        "has_preferred_source": has_preferred_source,
        "has_official_direct_result": has_official_direct_result,
        "combined_text": "\n".join(fetched_texts),
    }


def _draft_is_source_limited(draft: str) -> bool:
    """Return whether a draft clearly refuses unsupported current claims."""

    lowered = draft.lower()
    phrases = (
        "insufficient evidence",
        "source evidence is insufficient",
        "not enough evidence",
        "could not verify",
        "cannot verify",
        "unverified",
        "no verified score",
    )
    chinese_phrases = (
        "\u8bc1\u636e\u4e0d\u8db3",
        "\u65e0\u6cd5\u6838\u5b9e",
        "\u4e0d\u80fd\u6838\u5b9e",
        "\u672a\u6838\u5b9e",
        "\u6765\u6e90\u4e0d\u8db3",
    )
    return any(phrase in lowered for phrase in phrases) or any(
        phrase in draft for phrase in chinese_phrases
    )


def _draft_has_result_language(draft: str) -> bool:
    """Return whether a draft makes concrete sports-result claims."""

    lowered = draft.lower()
    english_terms = (
        "beat",
        "defeated",
        "won",
        "full-time",
        "final score",
        "player performance",
        "scored",
        "goal",
    )
    chinese_terms = (
        "\u6218\u80dc",
        "\u51fb\u8d25",
        "\u83b7\u80dc",
        "\u5168\u573a",
        "\u6bd4\u5206",
        "\u8fdb\u7403",
        "\u7403\u5458\u8868\u73b0",
    )
    return any(term in lowered for term in english_terms) or any(
        term in draft for term in chinese_terms
    )


def _text_contains_result_evidence(text: str) -> bool:
    """Return whether fetched text contains score-like result evidence."""

    return bool(_score_patterns(text)) or _draft_has_result_language(text)


def _draft_claims_unverified_zero_zero(draft: str, evidence_text: object) -> bool:
    """Return whether draft turns fixture-only evidence into a 0-0 score."""

    scores = _score_patterns(draft)
    if not any(score in {"0-0", "0:0"} for score in scores):
        return False
    return not _all_scores_supported(["0-0"], str(evidence_text))


def _draft_has_start_date_conflict(draft: str, evidence_text: object) -> bool:
    """Return whether a June 18 start claim conflicts with June 11 evidence."""

    lowered_draft = draft.lower()
    lowered_evidence = str(evidence_text).lower()
    draft_mentions_june_18_start = (
        ("june 18" in lowered_draft or "jun 18" in lowered_draft)
        and any(term in lowered_draft for term in ("start", "begin", "first"))
    )
    evidence_mentions_june_11_start = (
        ("june 11" in lowered_evidence or "jun 11" in lowered_evidence)
        and any(term in lowered_evidence for term in ("start", "begin", "first", "opening"))
    )
    return draft_mentions_june_18_start and evidence_mentions_june_11_start


def _score_patterns(text: str) -> list[str]:
    """Return normalized score patterns from text."""

    scores: list[str] = []
    for match in re.finditer(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b", text):
        scores.append(f"{match.group(1)}-{match.group(2)}")
    return scores


def _all_scores_supported(scores: list[str], evidence_text: object) -> bool:
    """Return whether every draft score appears in fetched evidence text."""

    normalized_evidence = str(evidence_text).replace(":", "-")
    evidence_scores = set(_score_patterns(normalized_evidence))
    normalized_scores = {score.replace(":", "-") for score in scores}
    return normalized_scores.issubset(evidence_scores)


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
