# Mem0 同控制复现实验

语言：中文 | [English](./mem0-comparable-reproduction.en.md)

## 问题与假设

问题：AgentLadder 的 Memory Agent 在固定 LoCoMo 隐藏切分上与官方 Mem0 OSS v3 相比表现如何，而且这个比较能否避免不同模型、不同题目、不同 top-k 和不同 scorer 造成的假领先？

可证伪假设：把官方 `feat/v3-pipeline` 最终 PR head 固定为不可变 SHA，真实执行其 Memory formation 和 hybrid retrieval，再复用 AgentLadder 已冻结的 100 题、DeepSeek 答案模型、512-token 预算、top-20 上下文和确定性 LoCoMo F1 scorer，可以得到一个可追溯的同控制 Mem0 对照成绩。

## 快速体验

先启动只用于本实验的本机 embedding 服务：

```powershell
$env:PYTHONPATH='src'
python -m uvicorn klara.eval.local_embedding_server:app --host 0.0.0.0 --port 18989
```

另开一个终端，再启动 Mem0 容器：

```powershell
docker compose --env-file .env -f docker/mem0-comparable/compose.yaml up -d --build
```

运行真实 formation/search smoke：

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.mem0_comparable_live `
  --root . --server-url http://localhost:18888 --smoke
```

完整 100 题运行可以断点续跑：

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.mem0_comparable_live `
  --root . `
  --manifest config/stages/mem0-comparable-reproduction.manifest.json `
  --source-commit 3b93e9b91e83b48e405e21a932d1d1b3702ef7f1 `
  --dataset .tmp/public-benchmarks/locomo/data/locomo10.json `
  --ingestion-checkpoint .tmp/mem0-comparable/ingestion.jsonl `
  --answer-checkpoint .tmp/mem0-comparable/answers.jsonl `
  --server-url http://localhost:18888 `
  --max-ingest-workers 2 --max-answer-workers 4 `
  --python-tests-collected 517 --python-tests-skipped 2
```

原始问题、答案、检索文本和预测只进入忽略目录；Git 中的 JSON 报告只保留哈希、分数和聚合运行指标。

## 冻结基线与控制变量

- `memory-benchmarks` 固定在 `4b61c5d31b9c668a12b4f5e78064248a02c82d2b`。
- 其失效依赖名 `feat/v3-pipeline` 由官方 PR #4805 最终 head `5e941e24c2cb260f73cc6d31113a92bb1ce62d46` 精确替换。
- LoCoMo 数据固定在 commit `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376` 和 SHA-256 `79fa87e...98ff4`。
- 题目固定为 offset-10、每段对话 10 题，共 100 题；case-ID 哈希为 `8b80b91c...3e12`。
- 三个系统使用相同的 `deepseek/deepseek-v4-flash` 答案模型、temperature 0、top-k 20、最大 512 输出 token 和确定性 scorer；Mem0 与 direct baseline 复用相同的 answer-only prompt，Agent 保留冻结的工具能力 prompt。
- Mem0 formation 使用相同 DeepSeek 模型和 `sentence-transformers/all-MiniLM-L6-v2` embedding。
- 每个单-turn extraction 最多输出 2,400 token。真实兼容性探针表明 512 token 会被 `deepseek-v4-flash` 的内部推理用尽并留下空正文；1,400 token 可通过简单 smoke，但在复杂 LoCoMo turn 上仍出现截断式非法 JSON，因此正式配置在接受 checkpoint 前冻结为 2,400。按每次最多 20,000 输入 token 估算，5,882 次 formation 的保守费用上界低于冻结的 25 美元预算。官方 SDK 不返回 extraction usage，因此报告同时标注这个遥测缺口；答案生成仍固定为 512 token。

## 数据、来源与隔离

官方 benchmark 的 requirements 指向已经删除的 branch。GitHub 的 PR API 和 `refs/pull/4805/head` 同时证明该 branch 最终 head；构建文件直接固定 SHA，绝不使用 `main` 或 `latest` 代替。

LoCoMo 采用 CC-BY-NC-4.0，原始数据和由其派生的 checkpoint 不进入仓库。`.env` 只由 Docker Compose 传入容器；服务健康检查、smoke 和公开报告均不写出 API key。

## 执行机制

```text
冻结来源与输入哈希
-> 构建精确 Mem0 PR head
-> 每个 LoCoMo turn 执行一次官方 v3 ADD formation
-> 记录来源 dia_id / 时间作为观测 metadata
-> 官方 v3 dense + BM25 + entity hybrid search
-> 按原时间排序 top-20 memories
-> 相同 DeepSeek prompt / 512-token 预算生成答案
-> 确定性 F1、EM、Evidence Recall@20
-> 更新 Product Freeze blocker 和完成台账
```

formation 和 search 来自官方 `Memory.add` / `Memory.search`。适配器只负责 HTTP 边界、source metadata、相同答案 prompt 和报告生成。

## 已披露的官方包装层缺口

- 官方 benchmark client 发送 `timestamp`，但固定 server request schema 没有该字段；适配器把时间放入官方 SDK 已支持的 `created_at` metadata。
- 固定 server 仍以 `user_id=` 调用 search，而 v3 SDK 已改为 `filters={"user_id": ...}`；适配器只做这个参数映射。
- Qdrant 使用官方 v3 Qdrant adapter 连接固定版本的服务容器。精确 PR head 在嵌入式模式下延迟创建实体库时会复制本地客户端并触发 RocksDB 文件锁；服务模式保留相同 dense、BM25 与 entity additive scoring，同时消除该锁冲突。
- 精确 PR head 会把 malformed extraction JSON 和 provider 异常静默折叠成空记忆。适配器仅在相同 DeepSeek 调用返回空、非对象或缺少 `memory` list 的 JSON 时最多重试两次；三次仍非法则把该 HTTP request 显式标为失败。外层客户端随后对同一个 turn 最多尝试 16 次，退避上限为 4 秒；这个 durable retry 只改变故障恢复，不改变模型、提示、轨迹顺序、检索或评分。最终仍失败会中止运行；报告公开 JSON retry、request-failure 和 HTTP policy，不把 provider/schema 失败伪装成“无记忆”。
- 相同的 `all-MiniLM-L6-v2` 在本机缓存服务中运行，Mem0 通过其官方 OpenAI-compatible embedding provider 调用；这样不在容器内重复下载 Torch。
- 官方 benchmark 的 LLM judge 被冻结的确定性 LoCoMo token F1 取代，这是保证三个系统 scorer 相同所必需的偏差。

## 指标与门槛

- 100/100 题必须完成，provider/retrieval error 必须为 0。
- 全部 LoCoMo turns 必须由官方 Mem0 formation 执行。
- 最终未恢复的 extraction JSON failure 会直接中止运行；恢复过的 JSON retry 与 HTTP request failure 次数必须公开。
- 正式运行经过多个 checkpoint-resume 进程，旧进程没有持久化持续时间，因此机器报告只标注最后一次恢复进程耗时，并把端到端耗时明确记为不可用。JSON retry 与 request-failure 是 Mem0 适配服务生命周期计数，包含正式 checkpoint 前的有界 smoke，不能解释成纯正式样本计数。
- 题目、模型、embedding、top-k、生成预算和 scorer 哈希必须一致；Mem0 与 direct baseline 的答案 prompt 哈希必须一致。
- P0 奇怪回答必须为 0。
- F1、EM、Recall@20、P50/P95 检索延迟、端到端延迟和答案 token 都必须原样报告；不设“必须赢”的后验阈值。
- 即使本切分超过 Mem0，也只能声称“冻结 100 题同控制结果”，不能推广为普遍超过 Mem0。

## 验证

```powershell
python -m pytest -q tests/klara/eval/test_mem0_comparable_live.py
python -m pytest -q
docker compose --env-file .env -f docker/mem0-comparable/compose.yaml ps
git diff --check
```

## 产物

- `docs/reports/product/mem0-comparable-reproduction.json`
- `docs/reports/product/mem0-comparable-reproduction.md`
- `docs/reports/product/mem0-comparable-reproduction.en.md`
- `.tmp/mem0-comparable/ingestion.jsonl`（忽略、可恢复）
- `.tmp/mem0-comparable/answers.jsonl`（忽略、包含公开数据派生文本）
- 更新后的 `agent-product-freeze-readiness.*` 和 `completion-ledger.*`

## 限制与下一实验

本实验不是 Mem0 Platform 云服务成绩，也不复刻官方 LLM judge。它只比较固定 OSS v3 的 formation/retrieval。Mem0 门槛通过后，Product Freeze 仍必须等待独立模型 judge 和盲测人工标签；MEM1 与 BEAM 仍是资源扩展项，训练继续禁止。
