# Agent Product Freeze 就绪性实验

语言：中文 | [English](./agent-product-freeze-readiness.en.md)

## 问题与假设

问题：当旧的失败回放、最新隐藏切分、模块级架构门禁和外部 benchmark 同时存在时，哪一组证据可以决定 Agent 是否允许进入模型训练？

可证伪假设：如果逐个验证冻结输入哈希，并使用“新隐藏切分更新当前结论、旧失败永久保留、内部 baseline 不冒充外部竞品”的优先级规则，就能生成唯一且可重复的 Product Freeze 状态。

## 快速体验

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.product_freeze_readiness `
  --root . `
  --manifest config/stages/agent-product-freeze-readiness.manifest.json `
  --source-commit 0d3f3d5b61a2a374f504e0f8407f72de14d49cc7 `
  --python-tests-collected 513 --python-tests-skipped 2 `
  --web-tests 71 --web-test-files 20 --web-build-passed `
  --report-json docs/reports/product/agent-product-freeze-readiness.json `
  --report-md docs/reports/product/agent-product-freeze-readiness.md `
  --report-en-md docs/reports/product/agent-product-freeze-readiness.en.md `
  --ledger-json docs/reports/product/completion-ledger.json `
  --ledger-md docs/reports/product/completion-ledger.md `
  --ledger-en-md docs/reports/product/completion-ledger.en.md
```

预期输出：证据统一阶段通过，但 `agent_product_freeze_allowed=false`，模型训练仍被阻塞。

## 冻结基线与控制变量

- 父提交固定为 `0d3f3d5b61a2a374f504e0f8407f72de14d49cc7`。
- 输入路径和 SHA-256 固定在 `config/stages/agent-product-freeze-readiness.manifest.json`。
- LoCoMo 当前门禁使用 offset-10 的新鲜 100 题切分；Agent 和 direct baseline 使用相同题目、DeepSeek 模型、top-k、生成长度和 scorer。
- offset-0 的旧失败回放保留为历史修复证据，不从仓库删除，也不冒充当前隐藏成绩。
- 本实验不修改 benchmark 答案、标签、阈值或模型输出。

## 数据、来源与隔离

- LoCoMo 来源、commit、许可和数据哈希沿用冻结 benchmark 报告。
- KlaraBench 只包含公开回答与公开动作，不包含 provider hidden reasoning。
- 报告只读取聚合指标、ID 哈希和运行元数据，不把忽略目录中的原始公开数据文本复制进 Git。
- 独立 judge、人评、Mem0、MEM1、BEAM 的缺失结果继续记为阻塞或资源扩展项。

## 决策机制

```text
验证 manifest 与输入 hash
-> 分离 architecture freeze 与 product freeze
-> 选择最新新鲜隐藏切分
-> 保留旧失败回放
-> 判断内部 baseline 与外部竞品边界
-> 更新 machine-readable ledger
-> 允许或阻塞下一阶段
```

实现位于 `src/klara/eval/product_freeze_readiness.py`。输入 hash 或跨报告题目 hash 不一致时直接失败，不生成更乐观的状态。

## 指标与门槛

- 所有冻结输入哈希一致：必须为 `100%`。
- 架构门禁与 Product Freeze 状态必须分开。
- 新隐藏 LoCoMo Agent 必须通过已冻结的非劣门槛。
- 独立 judge、盲测人评和同控制变量 Mem0 对照缺失时，Product Freeze 必须保持阻塞。
- 不允许宣称 Mem0/MEM1/BEAM/GPT/Qwen/ChatGPT 或通用 Agent 框架领先。

## 验证

```powershell
python -m pytest tests/klara/eval/test_product_freeze_readiness.py -q
python -m pytest -q
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
git diff --check
```

## 产物

- `docs/reports/product/agent-product-freeze-readiness.json`
- `docs/reports/product/agent-product-freeze-readiness.md`
- `docs/reports/product/agent-product-freeze-readiness.en.md`
- `docs/reports/product/completion-ledger.json`
- `docs/reports/product/completion-ledger.md`
- `docs/reports/product/completion-ledger.en.md`

## 限制与下一实验

本实验只统一证据，不创造新的独立评审或竞品成绩。下一阶段必须完成独立模型 judge、盲测人评和可追溯的 Mem0 同控制变量复现，随后才能生成 `codex/agent-product-freeze`。
