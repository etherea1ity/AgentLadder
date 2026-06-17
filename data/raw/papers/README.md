# Agent Ladder Papers

> Klara 的研究论文库：收集、整理和索引与 Agent 学习路线配套的学术论文。

## 目录结构

```
data/raw/papers/
├── paper-index.yaml          # 论文元数据索引 (主文件)
├── 01-agent-paradigms/       # Agent 基础范式
├── 02-agentic-rag/           # Agentic RAG / 检索控制
├── 03-agent-architecture/    # LLM Agent 架构
├── 04-memory-reflection-skill/ # 记忆 / 反思 / 技能学习
├── 05-world-models/          # 世界模型
├── 06-3d-spatial-world/      # 3D / 空间世界模型
└── 07-deep-research-tool-use/ # Deep Research / 工具使用

data/processed/papers/        # MinerU 转换后的 Markdown
    ├── 01-agent-paradigms/
    │   ├── paper-0101/
    │   │   ├── paper-0101.md
    │   │   └── images/
    │   └── ...
    └── ...

scripts/papers/
├── download_papers.py        # 从 arxiv 下载 PDF
└── convert_pdfs.py           # MinerU PDF → Markdown 转换

src/agent_ladder/knowledge/paper/
└── paper_card.py             # PaperCard 数据模型
```

## 论文分类与章节对应

| 分类 | 对应章节 | 核心主题 |
|------|----------|----------|
| 01 Agent 基础范式 | v0.1~v0.3 | ReAct, CoT, ToT, Agent 综述 |
| 02 Agentic RAG | v0.2~v0.3 | CRAG, Self-RAG, GraphRAG |
| 03 Agent 架构 | v0.1~v0.7 | 多 Agent 框架, 统一建模 |
| 04 记忆/反思/技能 | v0.4 | MemGPT, Voyager, 反思机制 |
| 05 世界模型 | v0.5~v0.9 | WALL-E, WebDreamer, 具身 AI |
| 06 3D/空间世界模型 | v0.5~v0.9 | 3D-VLM, 空间推理, Genie 2 |
| 07 Deep Research/工具 | v0.5~v0.6 | Search Agent, SWE-agent, Toolformer |

## 论文状态流转

```
to_download  →  downloaded  →  converted  →  indexed
   (待下载)       (已下载)       (已转MD)      (已入库)
```

## 快速开始

### 1. 下载论文 PDF

```bash
# 预览论文列表
python scripts/papers/download_papers.py --dry-run

# 下载所有 core 论文
python scripts/papers/download_papers.py --tag core

# 下载指定分类
python scripts/papers/download_papers.py --category 04
```

### 2. 使用 MinerU 转换 PDF → Markdown

```bash
# 方式 A: 本地 magic-pdf
pip install magic-pdf
python scripts/papers/convert_pdfs.py --mode local

# 方式 B: OpenXLab MinerU API (推荐，处理图片更好)
# 设置环境变量 MINERU_API_TOKEN 后:
python scripts/papers/convert_pdfs.py --mode api
```

### 3. 将论文编入 RAG 索引

```bash
# 在 convert 完成后，更新索引将论文纳入 Klara 的知识库
python scripts/papers/index_papers.py
```

## 论文选择原则

- **Core (~25篇)**: 每个子领域最基础/最核心的论文，Klara 必须精读
- **Important (~15篇)**: 重要的前沿进展和对比参考
- **Background (~5篇)**: 补充上下文的基础工作

论文优先选择: 有开源代码 + 有影响力的会议/期刊 + 2023-2025 最新研究。
