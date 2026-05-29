from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
load_dotenv(ROOT / ".env")

from agent_ladder.rag.chunking.overlap import OverlapTextSplitter
from agent_ladder.rag.embeddings.dashscope import DashScopeEmbedder
from agent_ladder.rag.indexing.index_record import records_from_chunks
from agent_ladder.rag.indexing.local_index_store import LocalIndexStore
from agent_ladder.rag.ingestion.local_markdown import LocalMarkdownLoader
from agent_ladder.rag.retrieval.tokenizer import tokenize


def build_index(knowledge_root: str = "data/knowledge", output: str = "data/rag/index/index_records.jsonl") -> int:
    loader = LocalMarkdownLoader(knowledge_root)
    documents = loader.load_directory()
    splitter = OverlapTextSplitter(chunk_size=800, chunk_overlap=120)
    chunks = splitter.split_documents(documents)
    records = records_from_chunks(chunks)
    embedder = DashScopeEmbedder()
    vectors = embedder.embed_texts([record.text for record in records])
    enriched = []
    for record, vector in zip(records, vectors, strict=True):
        tokens = tokenize("\n".join([record.metadata.title or "", record.metadata.summary or "", " ".join(record.metadata.tags), record.text]))
        enriched.append(record.model_copy(update={"dense_vector": vector, "sparse_tokens": tokens, "token_count": len(tokens)}))
    LocalIndexStore(output).save_records(enriched)
    return len(enriched)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Klara's local RAG JSONL index.")
    parser.add_argument("--knowledge-root", default="data/knowledge")
    parser.add_argument("--output", default="data/rag/index/index_records.jsonl")
    args = parser.parse_args()
    count = build_index(args.knowledge_root, args.output)
    print(f"Built {count} index records at {args.output}")


if __name__ == "__main__":
    main()
