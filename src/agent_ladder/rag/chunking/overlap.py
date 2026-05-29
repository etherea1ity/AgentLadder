"""Basic overlap chunking for Klara's first RAG chapter."""

from agent_ladder.rag.contracts.chunk import TextChunk
from agent_ladder.rag.contracts.document import Document


class OverlapTextSplitter:
    """Split Documents into fixed-size chunks with character overlap."""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be greater than or equal to 0")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_documents(self, documents: list[Document]) -> list[TextChunk]:
        """Split multiple Documents and keep their original order."""

        chunks: list[TextChunk] = []
        for document in documents:
            chunks.extend(self.split_document(document))
        return chunks

    def split_document(self, document: Document) -> list[TextChunk]:
        """Split one Document into overlapping TextChunks."""

        text = document.text.strip()
        if not text:
            return []

        chunks: list[TextChunk] = []
        step = self.chunk_size - self.chunk_overlap
        start = 0
        chunk_index = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end].strip()

            if chunk_text:
                chunks.append(
                    TextChunk(
                        chunk_id=f"{document.document_id}_chunk_{chunk_index:04d}",
                        document_id=document.document_id,
                        text=chunk_text,
                        chunk_index=chunk_index,
                        start_char=start,
                        end_char=end,
                        metadata=document.metadata,
                    )
                )
                chunk_index += 1

            if end == len(text):
                break
            start += step

        return chunks
