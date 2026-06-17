# Chapter 3 Labs: Multimodal RAG Ideas Not in the Mainline

The v0.3 mainline only implements caption-based visual retrieval over local `visuals.jsonl` metadata. These ideas are intentionally postponed to labs or later branches:

1. Query-time VLM reading of figures.
2. OCR over pages and figures.
3. ColPali or page-as-image retrieval.
4. Layout-aware PDF parsing.
5. Table structure extraction from real PDFs.
6. Screenshot/thumbnail rendering in the web UI beyond existing trace payloads.

Reason: Chapter 3 teaches controlled runtime architecture. Heavy multimodal extraction would hide the core lesson behind PDF processing complexity.
