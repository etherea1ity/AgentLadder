"""Model-visible structured evidence handoff."""

from __future__ import annotations

import json

from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec
from klara.tools.base import BaseTool, ToolInputError
from klara.tools.builtin.evidence_submit.schema import (
    EVIDENCE_SUBMIT_METADATA,
    EVIDENCE_SUBMIT_SPEC,
)


class EvidenceSubmitTool(BaseTool):
    """Pass a bounded answer graph to the runtime without performing a side effect."""

    spec: ToolSpec = EVIDENCE_SUBMIT_SPEC
    metadata: ToolMetadata = EVIDENCE_SUBMIT_METADATA

    def run(self, arguments: JsonObject) -> ToolResult:
        final_text = self.optional_string(arguments, "final_text")
        if not final_text:
            raise ToolInputError("final_text must not be empty")
        for key in ("claims", "links", "citations"):
            value = arguments.get(key)
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ToolInputError(f"{key} must be an array of objects")
        abstain = arguments.get("abstain")
        if not isinstance(abstain, bool):
            raise ToolInputError("abstain must be a boolean")
        if abstain and not self.optional_string(arguments, "abstention_reason"):
            raise ToolInputError("abstention_reason is required when abstain is true")
        public = {
            "observation_kind": "evidence_submission",
            "claim_count": len(arguments["claims"]),
            "link_count": len(arguments["links"]),
            "citation_count": len(arguments["citations"]),
            "abstain": abstain,
            "final_text_exposed": False,
            "support_notes_exposed": False,
        }
        return ToolResult(
            tool_call_id=self.call_id(arguments),
            name=self.spec.name,
            content=json.dumps(arguments, ensure_ascii=False),
            public_content=json.dumps(public, ensure_ascii=False),
        )
