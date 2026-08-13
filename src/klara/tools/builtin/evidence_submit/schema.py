"""Schema and metadata for evidence_submit."""

from klara.core.tools import ToolMetadata, ToolSideEffect, ToolSpec


EVIDENCE_SUBMIT_SPEC = ToolSpec(
    name="evidence_submit",
    description=(
        "Submit a web-backed proposed answer, material claims, exact fetched-source "
        "links, citations, or an explicit abstention for runtime verification."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "final_text": {"type": "string"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string"},
                        "text": {"type": "string"},
                        "required": {"type": "boolean"},
                    },
                    "required": ["claim_id", "text"],
                    "additionalProperties": False,
                },
            },
            "links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string"},
                        "source_id": {"type": "string"},
                        "judgment": {
                            "type": "string",
                            "enum": ["supported", "contradicted", "insufficient"],
                        },
                        "support_note": {
                            "type": "string",
                            "description": "Exact short witness copied from fetched source text.",
                        },
                    },
                    "required": ["claim_id", "source_id", "judgment", "support_note"],
                    "additionalProperties": False,
                },
            },
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string"},
                        "source_id": {"type": "string"},
                    },
                    "required": ["claim_id", "source_id"],
                    "additionalProperties": False,
                },
            },
            "abstain": {"type": "boolean"},
            "abstention_reason": {"type": "string"},
        },
        "required": ["final_text", "claims", "links", "citations", "abstain"],
        "additionalProperties": False,
    },
)

EVIDENCE_SUBMIT_METADATA = ToolMetadata(
    label="Verify evidence",
    category="evidence",
    side_effect=ToolSideEffect.NONE,
    parallel_safe=False,
    max_output_chars=16000,
)
