# 章节二：RAG Agent，克拉拉的阳光图书馆
> 从模型本身能力，到可检索、可引用、可追踪的知识图书馆

当前分支： v0.2-rag-agent
如何运行： 

## 本章总结
在第一章中，Klara 只是一个能够调用 LLM、完成单次问答的 Minimal Agent。

她能够听见用户的问题，也能够依靠模型本身给出回答。但这时的 Klara 还没有真正属于自己的资料世界。她不知道自己的成长经历，不知道项目路线，也无法在回答中说明“我是从哪里知道这件事的”。

在第二章中，我们为 Klara 建造她的第一间小书房：

Klara's Sun Library

这间小书房里放的不是庞大的互联网，也不是复杂的论文库，而是 Klara 最初应该读懂的资料：

1. Klara 的身份与设定
2. Agent Ladder 的项目经历与成长路线

从这一章开始，Klara 不再只依靠模型参数来回答问题，她会学习**如何读取本地文档**、**切分知识片段**、**生成embedding**、**建立向量索引**、**召回相关资料**、**对资料进行粗/细粒度重排序**、**并且路径种有sourceCard、Citation和AnswerFrame**。
并且还有一些辅助克拉拉理解知识的设计，比如Metadata、Index、意图识别、Context Builder等。

在每一次问题中，克拉拉都会告诉我们，她每一步都分别做了什么，我们可以从一个完整的回答链路中，看到每一次思考的详细过程。

## Part A：本章定位
### 1. 为什么需要RAG
在第一章中，Klara已经能完成一次最小问答。当我们提出一个问题，她可以接受输入，调用LLM，生成回答，并且记录这一次的trace。
但是，她只能依靠LLM自己的能力去做出反应。如果你要问Klara，你的这个Klara：Agent Ladder是在做什么，我们的第一章学到了什么，第二章有什么能力，她并不知道。因为这些问题不属于普通常识，而是属于我们的私有知识、阶段知识以及需要持续更新的知识。
RAG的价值就在这里，它它可以给 LLM 外挂一个可维护的知识库，让知识不再只依赖模型本身，而是可以被新增、修改、删除、重新索引和重新检索。这样 Klara 的回答就能随着项目一起更新，也能在回答时说明自己参考了哪些资料。
并且当我们的知识有了源头，Klara就可以对自己的回答进行溯源，避免很多幻觉问题。

一次基础 RAG 流程可以理解为：Raw Documents → Cleaning → Chunking → Metadata → Embedding → Vector Index → Query → Hybrid Retrieval → Coarse Retrieval → Reranking → Context Builder → LLM Writer → SourceCard → Citation → AnswerFrameV1 → Trace。也就是说，我们先把资料清洗、切块、加上 metadata，再将文本向量化并存入索引；当用户提问时，系统会通过关键词和向量等方式进行混合检索，先粗排召回可能相关的内容，再精排选出最重要的片段，最后把这些片段交给 LLM 生成有来源支撑的回答。

### 2. Klara's Sun Library：为什么是小书房
第二章中，我们不会直接让 Klara 读取整个互联网，也不会一上来放入大量复杂论文。我们先给她一间小而清晰的书房：Klara's Sun Library。这间小书房里放的是 Klara 最应该先读懂的内容：她是谁、她的性格和边界是什么。Agent Ladder 的项目路线是什么、第一章发生了什么、第二章要学习什么。

之所以叫小书房，是因为第二章的重点不是堆资料规模，而是讲清楚 RAG 从前到后的基础链路。Klara 不需要一开始就拥有一座庞大的图书馆，她需要先学会如何整理资料、如何检索资料、如何选择相关片段、如何把资料交给 LLM，以及如何展示来源。从这一章开始，Klara 不再只是回答，而是开始学会先查资料后再回答。

因此，本章的目标可以概括为：让 Klara 拥有第一批可检索、可更新、可引用、可追踪的本地知识。第二章的 Klara 学会的是基础 RAG：如何把小书房里的资料变成可检索知识，并基于这些知识生成有来源的回答。第三章才会进一步升级到 Agentic RAG，让 Klara 学会复杂意图拆分、检索规划、query rewrite、证据选择和回答验证。
## Part B：资料进入系统

Part B 只做两件事：先读取 Klara 小书房里的 markdown 和 metadata，再把标准化后的 `Document` 切成 `TextChunk[]`。

```text
Markdown + Metadata
→ Document
→ TextChunk[]
```

这一部分还不涉及 embedding，也不涉及检索算法。它的目标是让磁盘上的知识文件进入系统，并变成下一部分索引层可以继续处理的文本块。

### 3. 读取与 Metadata 设计

这一节解决的问题是：Klara 如何把本地知识文件带着身份信息读入系统。

```text
.md file + .metadata.yaml file
→ LocalMarkdownLoader
→ Document
```

输入是小书房里的 markdown 正文和同名 metadata 文件；输出是统一的 `Document`。Klara 在这里学会：每一份资料都不只是文本，还必须知道它来自哪里、属于哪一章、对应哪个版本。

对应代码：

```text
src/agent_ladder/rag/contracts/document.py
src/agent_ladder/rag/ingestion/local_markdown.py
```

<details>
<summary>展开：资料、metadata 字段与 Document 设计</summary>

Klara 的小书房里现在有三份最初的英文知识资料：

```text
data/knowledge/
├── global/
│   ├── klara-overview.md
│   └── klara-overview.metadata.yaml
└── chapters/
    ├── ch01-minimal-agent.md
    ├── ch01-minimal-agent.metadata.yaml
    ├── ch02-rag-agent.md
    └── ch02-rag-agent.metadata.yaml
```

其中：

- `klara-overview.md`：Klara 的全局能力地图，说明 Klara 是谁、Agent Ladder 是什么、她会沿着哪些能力成长
- `ch01-minimal-agent.md`：Klara 第一章已经学会的 Minimal Agent 能力
- `ch02-rag-agent.md`：Klara 第二章正在学习的 RAG Agent 能力

每一份 markdown 都有一个同名 metadata 文件。例如：

```text
ch02-rag-agent.md
ch02-rag-agent.metadata.yaml
```

这样设计是因为正文和身份信息要分开：

- `.md` 负责保存 Klara 能阅读的知识正文
- `.metadata.yaml` 负责说明这份资料是谁、来自哪里、属于哪一章、对应哪个版本

读取后的结果是统一的 `Document`：

```text
Markdown File
+
Metadata File
→ Document
```

在代码里，`Document` 的最小结构是：

```text
Document = text + metadata
```

其中 metadata 包含：

```text
document_id
title
source_path
source_type
category
chapter
version
language
tags
summary
```

例如 `ch02-rag-agent.metadata.yaml` 会告诉系统：

```text
document_id: doc_ch02_rag_agent
title: Chapter 2 Capability: RAG Agent
category: chapters
chapter: ch02
version: v0.2-rag-agent
source_type: markdown
```

这一层解决的是：Klara 的资料如何带着身份进入系统。后续做 source card、citation、版本过滤、章节过滤时，都依赖这些 metadata。

</details>

### 4. 分块策略：Overlap Chunking

这一节解决的问题是：整篇 `Document` 太长，不适合直接检索，需要切成更小的文本块。

```text
Document
→ OverlapTextSplitter
→ TextChunk[]
```

输入是 `Document`，输出是带来源信息的 `TextChunk[]`。Klara 在这里学会：检索系统通常检索的是片段，不是整篇文章；相邻片段保留一点 overlap，可以减少边界信息丢失。

对应代码：

```text
src/agent_ladder/rag/contracts/chunk.py
src/agent_ladder/rag/chunking/overlap.py
```

<details>
<summary>展开：常见切块策略与本章为什么选择 overlap</summary>

如果整篇文档太长，检索会变粗；如果片段太短，又容易丢失上下文。所以 RAG 系统通常会使用 chunking 策略。

常见的 chunking 策略包括：

```text
fixed-size chunking
recursive markdown chunking
heading-based chunking
semantic chunking
overlap chunking
```

这一章先不做复杂策略，只选择一个最基础、最容易理解、也最常见的策略：

```text
overlap chunking
```

它的意思是：相邻 chunk 之间保留一小段重叠文本。

例如：

```text
chunk_size = 800
chunk_overlap = 120
```

这样切块时，大概会形成：

```text
Chunk 1: characters 0-800
Chunk 2: characters 680-1480
Chunk 3: characters 1360-2160
```

重叠部分可以减少边界信息丢失。

Part B 结束时，Klara 的资料会从：

```text
Markdown + Metadata
```

变成：

```text
Document
→ TextChunk[]
```

这些 chunk 还没有向量，也还不能被检索。它们只是进入下一部分算法层的输入。

</details>

## Part C：从文本块到可检索索引

Part C 的目标是：让每一个 `TextChunk` 进入索引层，拥有语义表示和关键词表示，最终可以被检索、融合排序和精排。

```text
TextChunk[]
→ IndexRecord[]
→ Dense Embedding
→ Dense Vector Index
→ Sparse / BM25 Index
→ Hybrid Retrieval
→ Reranked Results
```

### 5. IndexRecord：Chunk 如何进入索引层

这一节解决的问题是：`TextChunk` 只是文档切块层对象，不能承担 embedding、tokens、scores 等检索状态。

```text
TextChunk[]
→ records_from_chunks()
→ IndexRecord[]
```

输入是 `TextChunk[]`，输出是 `IndexRecord[]`。Klara 在这里学会：把“文档切块层”和“索引检索层”分开，后面的 dense vector、sparse tokens、BM25 信息和检索分数都放到索引层对象里。

对应代码：

```text
src/agent_ladder/rag/indexing/index_record.py
```

<details>
<summary>展开：为什么需要 IndexRecord，以及它和真实向量库的关系</summary>

Part B 的终点是 `TextChunk`。一个 `TextChunk` 只说明：

```text
这段文本来自哪份 Document
它是第几个 chunk
它在原文中的起止位置是什么
它带着哪些 metadata
```

例如：

```text
chunk_id: doc_ch02_rag_agent_chunk_0003
document_id: doc_ch02_rag_agent
text: "RAG lets Klara search local knowledge before answering..."
metadata:
  chapter: ch02
  version: v0.2-rag-agent
```

但是检索系统需要的不只是文本。Dense retrieval 需要：

```text
dense_vector
```

Sparse / BM25 retrieval 需要：

```text
sparse_tokens
term frequency
document length
```

Hybrid retrieval 后面还会产生：

```text
dense_score
sparse_score
hybrid_score
```

这些都不应该直接塞回 `TextChunk`。因为 `TextChunk` 的职责是表示文本如何从 `Document` 中切出来，而索引层需要一个新的对象：

```text
IndexRecord = TextChunk + 检索层信息
```

在本章的最小版本里，`IndexRecord` 包含：

```text
record_id
chunk_id
document_id
text
metadata
dense_vector
sparse_tokens
token_count
```

这一层的意义是把三个世界分开：

```text
TextChunk      = 文档切块层
IndexRecord    = 索引检索层
RetrievedChunk = 检索结果层
```

真实向量库里也有类似边界：

```text
Qdrant point      = id + vector + payload
Weaviate object   = properties + vector + inverted index entry
Elasticsearch doc = _source + dense_vector field + text field
```

我们现在不直接接这些数据库，而是先手写一个教学版 `IndexRecord`。这样后面无论换成本地 JSONL、Qdrant、Weaviate、Milvus，核心结构都不会乱。

</details>

### 6. Dense Embedding：把文本变成语义向量

这一节解决的问题是：普通文本不能直接做语义相似度计算，需要先变成 dense vector。

```text
IndexRecord.text
→ Embedding Model
→ dense_vector
```

输入是 `IndexRecord.text`，输出是 `dense_vector`。Klara 在这里学会：把 chunk 和用户 query 都转成向量，下一节再用相似度搜索找到相关资料。本章不训练 embedding model，而是调用已有 embedding model；Sparse / BM25 部分会自己手写，Dense Embedding 使用真实模型生成语义向量。

对应代码：

```text
src/agent_ladder/rag/embeddings/base.py
src/agent_ladder/rag/embeddings/dashscope.py
```

<details>
<summary>展开：从 one-hot、Bag of Words 到 Dense Embedding</summary>

#### 为什么文本不能直接计算

用户可能会问：

```text
What did Klara learn in chapter one?
```

资料里可能写的是：

```text
Chapter 1 introduced AskState, AnswerState, RunLog, and the MinimalAgent runtime.
```

人可以看出它们相关，但是程序看到的只是两段字符串。字符串本身只能直接做一些很浅的比较：是否完全相等、是否包含某个词、两个字符串编辑距离是多少。

它不知道：

```text
learn ≈ introduced
chapter one ≈ Chapter 1
Klara's first ability ≈ Minimal Agent
```

所以，我们需要把文本变成数字。只有变成数字后，系统才能计算“这两个文本有多相似”。

#### Vocabulary：先把世界变成词表

最基础的方法是先定义一个词表：

```text
vocabulary = ["klara", "agent", "rag", "answer", "trace"]
```

词表里的每个词对应一个位置：

```text
klara  → 0
agent  → 1
rag    → 2
answer → 3
trace  → 4
```

这不是现代 embedding，但它能帮助我们理解：文本向量化的第一步，是把文本放进一个可计算的坐标系统。

#### One-hot Encoding：一个词一个位置

如果当前词是 `rag`，那么它在上面词表里的 one-hot 表示就是：

```text
[0, 0, 1, 0, 0]
```

如果当前词是 `klara`，就是：

```text
[1, 0, 0, 0, 0]
```

one-hot 的特点是只有一个位置是 1，其他位置都是 0。它非常容易理解，但它只能表示“这是哪个词”，不能表示“这个词和哪个词语义更近”。

#### Bag of Words：一句话里出现了哪些词

一句话可以看成多个词的集合。例如：

```text
Klara uses RAG to answer.
```

在词表：

```text
["klara", "agent", "rag", "answer", "trace"]
```

里，可以表示成：

```text
[1, 0, 1, 1, 0]
```

如果记录出现次数：

```text
Klara uses RAG. Klara answers.
→ [2, 0, 1, 1, 0]
```

这就是 bag of words 的直觉。它比单个 one-hot 更像“文本向量”，但它仍然主要关心词有没有出现、出现了几次，还不真正理解语义。

#### Sparse Vector 的问题

词表向量通常是 sparse vector。真实词表可能有几万、几十万词，而一句话只会出现其中很少一部分，所以向量大概会长这样：

```text
[0, 0, 0, 1, 0, 0, 0, 0, ...]
```

这类表示的问题是：维度很大、大部分位置为空、只知道词出现没出现、不理解同义词、不理解改写后的相同含义。

但是 sparse representation 也不是没用。它非常适合处理：

```text
AskState
RunLog
AnswerFrameV1
v0.2-rag-agent
source_card
```

这些项目术语、字段名、版本号、代码名，往往需要精确匹配。所以后面第 8 节我们还会学习 BM25。

#### Dense Embedding：把语义压缩进向量

现代 embedding 模型做的是：

```text
text → dense vector
```

例如：

```text
"What did Klara learn in chapter one?"
→ [0.031, -0.482, 0.105, 0.774, ...]
```

dense vector 和 sparse vector 不同。它通常大部分位置都有小数值，每个维度不再对应一个人工指定的词，而是模型从大量数据里学出来的语义特征。

所以这两句话虽然字面不同：

```text
What did Klara learn in chapter one?
Which abilities did Klara gain in the first chapter?
```

它们的 dense vector 仍然可能很接近。这就是 dense embedding 对 RAG 的价值：Klara 不只按字面找资料，也能按语义找资料。

#### Cosine Similarity：比较两个向量方向

当 chunk 和 query 都变成向量后，我们还需要一个相似度算法。最常用的是 cosine similarity：

```text
cosine_similarity(a, b)
= (a · b) / (||a|| × ||b||)
```

其中：

```text
a · b = dot product，两个向量对应位置相乘再相加
||a|| = 向量 a 的长度
||b|| = 向量 b 的长度
```

直觉是比较两个向量的方向是否接近。如果两个向量方向越接近，分数越高。在 RAG 里就是：

```text
query_vector
vs
chunk_vector
```

谁更接近，谁就更可能是相关资料。这会成为下一节 `Dense Vector Index` 的数学基础。

#### 我们自己写 embedding model 吗？

这一章不训练 dense embedding model。原因是 dense embedding model 本身需要大量语料、训练目标、对比学习数据、GPU、评估集和持续调优，这不是本章重点。

本章采用：

```text
Sparse / BM25：我们自己手写
Dense Embedding：调用已有 embedding model
```

这样 Klara 可以使用真实语义向量，学习者仍然能手写并理解检索、BM25、hybrid 和 reranking。

#### Embedding 存在哪里？

刚生成的 embedding 可以先放在内存里的 `IndexRecord.dense_vector`：

```text
IndexRecord.text
→ embedding model
→ IndexRecord.dense_vector
```

但是如果每次运行都重新调用 embedding API，会慢，也会增加成本。所以后面第 7 节会把带向量的索引记录保存到本地：

```text
data/rag/index/index_records.jsonl
```

这一章先使用本地 JSONL。未来可以替换成真正的向量库：Qdrant、Weaviate、Milvus、Elasticsearch / OpenSearch。

#### Klara 这一章怎么做

Klara 当前会使用 DashScope 的 OpenAI-compatible embedding API。这里的重点是区分：

```text
Chat Model ≠ Embedding Model
```

Chat model 负责生成回答：

```text
question → answer
```

Embedding model 负责生成向量：

```text
text → vector
```

Klara 会把每个 `IndexRecord.text` 送给 embedding model：

```text
IndexRecord.text
→ text-embedding-v4
→ dense_vector
```

这一节只负责 `Text → Dense Vector`。下一节才会继续 `Dense Vector → Vector Index → Similarity Search`。

</details>

### 7. Dense Vector Index：最小世界算法
### 8. Sparse / BM25 Index：关键词检索
### 9. Hybrid Retrieval + Reranking

## Part D：问题进入 RAG 链路
### 10. Direct vs RAG Decision
### 11. Context Builder

## Part E：从资料到答案
### 12. SourceCard / Citation
### 13. AnswerFrameV1 / Trace

## Part F：章节冻结
### 14. How to Run
### 15. Tests
### 16. Known Limitations
### 17. Next Chapter: Agentic RAG