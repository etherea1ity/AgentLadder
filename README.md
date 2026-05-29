# Klara / Agent Ladder

**From Prompt to Policy**

当前分支：

```text
v0.1-minimal-agent
```

当前章节：

```text
Chapter 1：克拉拉诞生
```

下一个分支：

```text
v0.2-rag-agent
```

下一章中，Klara 会开始学习 RAG：读取本地知识库、切分文档、向量检索、source card、citation，并基于资料回答问题。

Klara 现在还只是一个最小形态的 **Artificial Friend**。她可以接收一个问题，调用真实的大模型 API，生成回答，统计 token，保存运行记录，并在前端展示一次可观察的 run。

这个分支要讲清楚一件事：

> 一次 LLM API Call，如何变成一个有状态、可观察、可追踪的 Minimal Agent。

---

> 【截图占位 1：首页截图】
>
> 建议文件：`docs/assets/readme/klara-home.png`
>
> 建议内容：Klara 首页，包含大 logo、输入框、左侧会话栏。

---

## 当前分支里，Klara 会什么？

在 `v0.1-minimal-agent` 中，Klara 已经具备以下能力：

- 接收用户输入的问题
- 调用真实 LLM，而不是 mock 回答
- 流式输出回答
- 创建 `AskState`
- 创建 `AnswerState`
- 创建 `RunLog`
- 统计 input tokens / output tokens
- 保存 JSONL trace
- 在前端展示对话
- 在右侧 Run Margin 中展示当前 run 的公开运行信息
- 支持会话创建、删除、恢复
- 保持 core / backend / frontend 分离

这一章的 Klara 还不会：

- RAG
- 记忆
- 搜索网页
- MCP 工具
- 长报告研究
- Eval
- RL 自优化

这些会在后续章节逐步加入。

---

## 快速启动

### 1. 准备 API Key

本项目当前使用阿里云百炼 / DashScope 的 OpenAI-compatible API。

你需要先在阿里云百炼平台创建自己的 API Key。

官方入口：

- [阿里云百炼控制台](https://bailian.console.aliyun.com/)
- [阿里云百炼官方文档：如何获取 API Key](https://help.aliyun.com/zh/model-studio/get-api-key/)

> 注意：不要把真实 API Key 提交到 GitHub。真实 key 只应该放在本地 `.env` 文件中。

---

> 【截图占位 2：阿里云百炼 API Key 页面】
>
> 建议文件：`docs/assets/readme/bailian-api-key.png`
>
> 建议内容：展示 API Key 创建入口，注意不要露出真实 key。

---

复制 `.env.example` 为 `.env`：

```env
DASHSCOPE_API_KEY=your_api_key_here
AGENT_LADDER_MODEL=qwen3.6-flash
AGENT_LADDER_ENABLE_THINKING=false
```

默认模型建议使用：

```text
qwen3.6-flash
```

因为第一章的目标不是追求最强回答，而是观察一次 agent run 是怎么发生的。

---

### 2. 启动前后端

在项目根目录运行：

```powershell
.\start.ps1
```

如果不想自动打开浏览器：

```powershell
.\start.ps1 -NoOpen
```

默认地址：

```text
Frontend: http://localhost:5123
Backend:  http://localhost:8000
```

---

> 【截图占位 3：PowerShell 启动截图】
>
> 建议文件：`docs/assets/readme/start-script.png`
>
> 建议内容：展示 `.\start.ps1` 启动成功，前端和后端都挂起来。

---

### 3. 发送第一个问题

你可以问：

```text
What is an AI Agent?
```

或者：

```text
什么是 AI Agent？
```

Klara 会开始一次最小运行：

```text
User Question
→ AskState
→ Prompt
→ LLM Call
→ AnswerState
→ RunLog
→ JSONL Trace
→ UI Run Margin
```

---

> 【截图占位 4：一次完整问答截图】
>
> 建议文件：`docs/assets/readme/klara-chat.png`
>
> 建议内容：中间对话区显示用户问题和 Klara 回答。

---

> 【截图占位 5：右侧 Run Margin 截图】
>
> 建议文件：`docs/assets/readme/klara-run-margin.png`
>
> 建议内容：点击 thinking / run 后，右侧展示 LLM Call、latency、input/output tokens、summary。

---

## Chapter 1：克拉拉诞生

我们要设计一个新一代的 **AF：Artificial Friend**。

她的名字叫 **Klara**。

Klara 不是一开始就会搜索网页、调用工具、记住上下文、写研究报告。她一开始只是一个非常简单的存在：

> 你给她一句话，她加工后，返回一句话。

这一章，我们要从零开始，看一个 AF 是如何诞生的。

---

## 什么是 Klara？

在这个项目里，Klara 可以先被理解成两个部分：

```text
Klara = 内核 + 四肢
```

### 内核

Klara 的内核，就是一个大语言模型，也就是 LLM。

LLM 最本质的能力非常简单：

```text
输入一段信息
→ 加工这段信息
→ 输出一段信息
```

比如：

```text
User: hi
LLM: hi, how can I help you?
```

或者：

```text
User: 什么是 AI Agent？
LLM: AI Agent 是一种能够感知输入、进行推理，并采取行动的系统。
```

这就是 Klara 最早的大脑。

她现在还不会主动去查网页。她也不会自己操作电脑。她不会真的打开文件、调用搜索引擎、访问数据库。

她的大脑只会做一件事：

> 接收信息，然后生成新的信息。

---

### 四肢和工具

那为什么市面上的 AI 产品可以搜索网页、调用工具、读文件、查资料？

因为真正的 Agent 不是只有一个 LLM。

它通常是：

```text
LLM 大脑
+ 状态
+ 工具
+ 运行流程
+ 观察记录
+ 错误处理
+ 记忆
+ 评估
```

LLM 本身不会真的“伸手”去搜索网页。它只是判断：

```text
我可能需要搜索
我可能需要调用工具
我可能需要读取资料
```

真正调用工具的是外层程序。

比如用户问：

```text
今天北京天气怎么样？
```

更合理的运行过程是：

```text
用户问题
→ LLM 判断：这需要天气工具
→ 程序调用 weather tool
→ weather tool 返回天气数据
→ LLM 阅读工具返回结果
→ LLM 用自然语言回答用户
```

也就是说：

```text
大脑决定方向
工具执行动作
大脑阅读结果
最后生成回答
```

这一章我们还不做工具。我们先做 Klara 的第一颗种子：

> 一次真实 LLM 调用，变成一次有状态、可观察、可保存的运行。

---

## 为什么一次 API Call 还不是 Agent？

最小的 LLM 调用大概长这样：

```python
from openai import OpenAI
import os

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

completion = client.chat.completions.create(
    model="qwen3.6-flash",
    messages=[
        {"role": "user", "content": "你好，你是谁？"}
    ],
)

print(completion.choices[0].message.content)
```

这一段代码说明了 LLM 的本质：

```text
messages 输入进去
content 输出出来
```

但是如果只停留在这里，它还不是 Agent。

因为我们不知道：

```text
这次问题有没有编号？
这次回答属于哪个问题？
使用了哪个模型？
用了多少 token？
耗时多久？
有没有保存 trace？
失败时发生了什么？
```

所以我们要把一次 API call 包装成一次可观察的运行。

---

## 从 API Call 到 Minimal Agent

在第一章里，我们加入三个核心状态：

```text
AskState
AnswerState
RunLog
```

它们分别回答三个问题：

```text
用户问了什么？
Klara 回答了什么？
这次运行发生了什么？
```

这就是 Minimal Agent 的最小骨架。

---

## AskState：用户问了什么

`AskState` 是一次提问的结构化记录。

```python
class AskState(BaseModel):
    ask_id: str
    question: str
    language: str = "auto"
    created_at: datetime
```

它不是 prompt。它也不是模型输出。

它是 Klara 在程序内部保存的状态。

比如用户问：

```text
什么是 AI Agent？
```

Klara 会先创建：

```json
{
  "ask_id": "ask_xxx",
  "question": "什么是 AI Agent？",
  "language": "auto",
  "created_at": "..."
}
```

这一步很重要。

因为从这里开始，用户的问题不再只是一段临时字符串。它变成了 Klara 可以追踪、保存、关联的状态。

---

## AnswerState：Klara 回答了什么

当 LLM 返回内容后，我们把它封装成 `AnswerState`。

```python
class AnswerState(BaseModel):
    ask_id: str
    answer: str
    model: str
    created_at: datetime
```

它记录：

```text
这次回答对应哪个 ask_id
回答内容是什么
使用了哪个模型
什么时候生成
```

比如：

```json
{
  "ask_id": "ask_xxx",
  "answer": "AI Agent 是一种能够接收输入、进行推理，并采取行动的系统。",
  "model": "qwen3.6-flash",
  "created_at": "..."
}
```

这一步让 Klara 的回答可以被追踪。

不是简单地：

```text
print(answer)
```

而是：

```text
这个 answer 属于哪个 question？
由哪个 model 生成？
什么时候生成？
```

---

## RunLog：这次运行发生了什么

`RunLog` 是 Klara 的观察记录。

```python
class RunLog(BaseModel):
    run_id: str
    ask_id: str
    model: str
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    token_source: str = "unknown"
    error: str | None = None
    created_at: datetime
```

它回答的是：

```text
这次运行用了多久？
用了多少 token？
token 是 API 返回的，还是本地估算的？
有没有报错？
```

比如：

```json
{
  "run_id": "run_xxx",
  "ask_id": "ask_xxx",
  "model": "qwen3.6-flash",
  "latency_ms": 1840,
  "prompt_tokens": 52,
  "completion_tokens": 128,
  "total_tokens": 180,
  "token_source": "reported",
  "error": null
}
```

这里的 token 统计规则是：

```text
优先使用模型 API 返回的真实 usage
如果 API 没返回，就使用本地估算
```

所以前端一定会尽量展示 token 信息。

---

## Trace：把一次运行保存下来

Klara 每次回答后，都会保存一条 JSONL trace。

一条 trace 大概长这样：

```json
{
  "schema_version": "v0.1",
  "ask": {
    "ask_id": "ask_xxx",
    "question": "什么是 AI Agent？"
  },
  "prompt": {
    "messages": [
      {
        "role": "system",
        "content": "You are Klara..."
      },
      {
        "role": "user",
        "content": "什么是 AI Agent？"
      }
    ]
  },
  "answer": {
    "ask_id": "ask_xxx",
    "answer": "AI Agent 是一种..."
  },
  "run": {
    "run_id": "run_xxx",
    "model": "qwen3.6-flash",
    "latency_ms": 1840,
    "prompt_tokens": 52,
    "completion_tokens": 128,
    "total_tokens": 180
  }
}
```

这就是我们第一章的核心：

```text
一次问题
一次回答
一次运行记录
一条 trace
```

Klara 不只是回答了问题。她留下了自己运行的痕迹。

---

## 为什么这些状态一开始就要设计好？

因为后面的 Klara 会越来越复杂。

现在她只会：

```text
问题 → LLM → 回答
```

但以后她会学会：

```text
问题 → 判断意图
问题 → 检索资料
问题 → 调用工具
问题 → 读取网页
问题 → 使用记忆
问题 → 验证 citation
问题 → 评估回答质量
```

到那时，Klara 的状态会越来越多：

```text
AskState
AnswerState
RunLog
ToolCallState
ObservationState
EvidenceItem
EvidencePack
MemoryState
EvalResult
PolicyTrace
```

所以第一章虽然简单，但它在打地基。

我们先让 Klara 学会：

```text
每一步都可以被记录
每一次运行都可以被观察
每一个回答都可以被追踪
```

这就是 Agent 工程的开始。

---

## 当前代码结构

第一章的核心代码在这里：

```text
src/agent_ladder/
  core/
    contracts/
      ask.py        # AskState
      answer.py     # AnswerState
      run.py        # RunLog
      usage.py      # TokenUsage

    runtime/
      minimal_agent.py   # MinimalAgent
      lifecycle.py       # answer / run / token lifecycle helpers

    tracing/
      jsonl_tracer.py    # JSONL trace writer

  llm/
    prompts/
      minimal.py         # Klara system prompt

    providers/
      dashscope.py       # DashScope / OpenAI-compatible provider

  infra/
    config/
      loader.py          # config + env loader
```

前后端在这里：

```text
apps/
  api/     # FastAPI backend
  web/     # React frontend
```

配置在这里：

```text
configs/
  default.yaml
  models.yaml
```

---

## Learning Ladder：Klara 会如何成长？

Agent Ladder 的主线不是把所有功能一次性塞进 main。

我们会按大主题冻结分支：

| Branch | 主题 | Klara 学会什么 |
|---|---|---|
| `v0.1-minimal-agent` | Minimal Agent | 从一次 LLM 调用变成可观察的最小 Agent |
| `v0.2-rag-agent` | RAG Agent | 阅读本地知识库并基于资料回答 |
| `v0.3-agentic-rag` | Agentic RAG | 检索、阅读、选择证据、写作、验证 |
| `v0.4-memory-agent` | Memory Agent | 记住上下文并处理追问 |
| `v0.5-research-agent` | Research Agent | 联网搜索、阅读、交叉验证、综合报告 |
| `v0.6-mcp-tool-agent` | MCP Tool Agent | 接入外部工具生态 |
| `v0.7-production-agent` | Production Agent | 处理并发、重试、超时、成本、鉴权、安全 |
| `v0.8-eval-data-flywheel` | Eval Data Flywheel | 用测试和 trace 判断 Agent 是否变好 |
| `v0.9-rl-for-agent` | RL for Agent | 从轨迹和反馈中优化策略 |

---

## Branch Philosophy

每个主线 branch 对应一个大主题。

我们不为每一个小概念创建一个 branch。

不是这样：

```text
learn/v0.0-hello-llm-api
learn/v0.1-ask-answer-agent
learn/v0.2-observable-agent
```

而是这样：

```text
v0.1-minimal-agent
```

然后在这个分支内部讲清楚：

```text
API Call
AskState
AnswerState
RunLog
JSONL Trace
MinimalAgent
Web UI
```

这样仓库会更清爽，学习路径也更清楚。

---

## 下一章：Klara 学会阅读资料

在 `v0.2-rag-agent` 中，Klara 会学习 RAG。

她不再只依赖模型自己的参数回答问题。她会开始读取本地知识库：

```text
document loading
chunking
embedding
vector search
retriever
source card
citation
RAG answer
```

那时 Klara 会从：

```text
只会回答
```

变成：

```text
能基于资料回答
```

这就是她成长的第二步。

---

## 一句话总结

Chapter 1 不是在做一个 ChatGPT clone。

我们是在见证 Klara 的诞生：

```text
一次 API Call
变成 AskState
变成 AnswerState
变成 RunLog
变成 Trace
最后变成一个最小但可观察的 Agent
```

她还很小。

但她已经开始留下自己的光。
