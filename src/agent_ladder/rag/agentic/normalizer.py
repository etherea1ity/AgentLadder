from __future__ import annotations

import re

from agent_ladder.rag.contracts.agentic import AnswerRequirement, LanguagePlan, OutputStyleSpec, RequestSpec

_ZH_RE = re.compile(r"[\u4e00-\u9fff]")

_TRANSLATIONS = {
    "给我": "give me",
    "篇": " papers",
    "相关论文": " related papers",
    "并按路线分类": " and classify by research route",
    "用英文解释": "explain in English",
    "解释": "explain",
    "中文": "Chinese",
    "英文": "English",
    "图片": "figure",
    "图": "figure",
    "表格": "table",
    "论文": "paper",
    "相关": "related",
}


def normalize_request(question: str) -> RequestSpec:
    language = detect_language(question)
    output_language = infer_output_language(question, language)
    canonical = canonical_query(question)
    return RequestSpec(
        original_query=question,
        canonical_query_en=canonical,
        query_variants_by_domain={
            "paper_corpus": canonical,
            "paper_visuals": canonical,
            "project_docs": question,
            "chapter_docs": question,
        },
        language_plan=LanguagePlan(
            input_language=language,
            output_language=output_language,
            explicit_output_language=has_explicit_output_language(question),
            reason="explicit language request" if has_explicit_output_language(question) else "follow input language",
        ),
        output_style=infer_output_style(question),
        requirements=parse_answer_requirements(question),
    )


def detect_language(text: str):
    has_zh = bool(_ZH_RE.search(text))
    has_ascii = bool(re.search(r"[A-Za-z]", text))
    if has_zh and has_ascii:
        return "mixed"
    return "zh" if has_zh else "en"


def infer_output_language(text: str, input_language: str):
    lower = text.lower()
    if "in chinese" in lower or "用中文" in text or "中文" in text:
        return "zh"
    if "in english" in lower or "用英文" in text or "英文" in text:
        return "en"
    if input_language == "mixed":
        return "zh" if _ZH_RE.search(text) else "en"
    return input_language if input_language in {"zh", "en"} else "en"


def has_explicit_output_language(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in ["in chinese", "in english"]) or any(marker in text for marker in ["用中文", "用英文", "中文", "英文"])


def canonical_query(text: str) -> str:
    result = text
    for zh, en in _TRANSLATIONS.items():
        result = result.replace(zh, en)
    if _ZH_RE.search(result):
        # Small teaching fallback: preserve known technical terms and remove remaining CJK separators.
        result = _ZH_RE.sub(" ", result)
    result = re.sub(r"\s+", " ", result).strip()
    result = expand_paper_abbreviations(result)
    return result or text


def expand_paper_abbreviations(text: str) -> str:
    """Keep internal paper retrieval English/canonical and disambiguate known agent terms."""
    lower = text.lower()
    if re.search(r"\breact\b", lower) and not any(marker in lower for marker in ["react.js", "javascript", "frontend", "component", "hooks", "vite"]):
        if "reasoning acting" not in lower:
            return f"{text} ReAct reasoning acting language models"
    return text


def parse_answer_requirements(text: str) -> AnswerRequirement:
    lower = text.lower()
    requested = None
    match = re.search(r"(\d+)(?=[^\n]{0,30}(?:篇|papers?|results?))", lower)
    if match:
        requested = int(match.group(1))
    return AnswerRequirement(
        requested_count=requested,
        need_diversity=any(x in lower for x in ["diverse", "classify", "路线", "分类", "different"]),
        need_recent=any(x in lower for x in ["recent", "latest", "new", "最新", "最近"]),
        need_method_details=any(x in lower for x in ["method", "方法", "details"]),
        need_limitations=any(x in lower for x in ["limitation", "不足", "局限"]),
    )


def infer_output_style(text: str) -> OutputStyleSpec:
    lower = text.lower()
    if re.search(r"\b(compare|comparison|对比|比较)\b", lower):
        return OutputStyleSpec(answer_style="comparison")
    if re.search(r"\b(brief|综述|research brief)\b", lower):
        return OutputStyleSpec(answer_style="research_brief")
    if re.search(r"\d+\s*(?:篇|papers?)", lower):
        return OutputStyleSpec(answer_style="paper_list", max_bullets=20)
    if re.search(r"\b(short|简短)\b", lower):
        return OutputStyleSpec(answer_style="short", max_bullets=5)
    return OutputStyleSpec(answer_style="explanatory")
