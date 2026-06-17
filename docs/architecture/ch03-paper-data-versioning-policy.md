# Chapter 3 Paper Data Versioning Policy

## What should be committed

Recommended to commit:

- `data/papers/fixtures/**`
- lightweight docs and schemas
- scripts under `scripts/ingest`, `scripts/index`, and `scripts/dev`
- quality reports when they are small and useful for review
- small deterministic indexes if they are not too large

## What should usually be ignored

Recommended to ignore by default:

- `data/papers/raw/*.pdf`
- large extracted page images
- large figure/table image dumps
- very large processed corpora generated from local PDFs

## How to rebuild local corpus

```bash
python scripts/ingest/audit_local_paper_drop.py --input "data/papers/论文" --output data/papers/quality_reports/source_audit_report.md
python scripts/ingest/build_paper_corpus.py --input "data/papers/论文" --root data/papers --mode migrate_existing
python scripts/ingest/validate_paper_corpus.py --root data/papers --strict
python scripts/index/build_paper_indexes.py --root data/papers
```

## How CI should run

CI should use stable fixtures:

```bash
python -m pytest tests/unit tests/integration
```

Unit/integration tests that need real corpus should use the local `data/papers` root only when present and should not require external downloads.

## How local smoke tests use real corpus

```bash
python scripts/dev/run_ch03_real_corpus_smoke.py
python -m agent_ladder.app.cli.main ask-agentic "给我 10 篇 Agentic RAG 相关论文，并按路线分类" --paper-root data/papers
```

## Policy note

Do not claim a local paper is open access unless the source metadata already verifies that status. If the file simply came from a local user folder, record `access_status = local_existing` and an access note saying the open-access status is not asserted.
