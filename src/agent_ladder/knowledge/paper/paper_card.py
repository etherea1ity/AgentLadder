"""
论文知识卡 (PaperCard) — 用于 RAG 系统中的论文元数据和引用。

对应 knowledge/paper/ 模块，与 SourceCard 的 source_type="paper" 配合使用。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PaperCard(BaseModel):
    """论文的标准化知识卡，可被 RAG 系统作为 SourceCard 引用。"""

    paper_id: str
    title: str
    authors: list[str]
    year: int
    venue: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    code_url: str | None = None

    # 分类
    category: str  # "01-agent-paradigms" 等
    tags: list[str] = []

    # 内容状态
    status: Literal[
        "to_download",
        "downloaded",
        "converted",
        "indexed",
    ] = "to_download"

    relevance: Literal["core", "important", "background"] = "important"
    abstract: str | None = None
    key_contributions: list[str] = []
    description: str = ""

    # 文件路径 (相对于项目根目录)
    pdf_path: str | None = None
    md_path: str | None = None

    # 时间戳
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()

    def to_source_card_snippet(self) -> str:
        """生成适合 RAG 检索使用的摘要片段。"""
        parts = [self.title]
        if self.venue:
            parts.append(f"({self.venue})")
        parts.append(f" — {self.description}")
        return " ".join(parts)

    def to_citation(self) -> str:
        """生成标准引用格式。"""
        authors_str = ", ".join(self.authors[:3])
        if len(self.authors) > 3:
            authors_str += " et al."
        citation = f"{authors_str} ({self.year}). {self.title}"
        if self.venue:
            citation += f". {self.venue}."
        if self.arxiv_id:
            citation += f" arXiv:{self.arxiv_id}."
        return citation
