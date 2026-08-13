# Permission Engine：证据之后，动作之前

语言：中文 | [English](./permission-engine.en.md)

上一章：[Chapter 13：Research Agent](./ch13-research-agent.md)

下一章：[Chapter 14：Durable Tasks](../skills/roadmap.md#chapter-14---background-tasks)

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Klara 在每次工具执行前，把模型请求转换为“身份 + 工具 + 能力 + 精确资源 + 风险 + 副作用”，只有冻结的低风险本地策略或尚未过期的精确授权能继续；未知、外部、付费、控制或破坏性动作一律停止并等待用户决定。

![Klara 权限决策流](../assets/permission-engine.svg)

| 决策信号 | 下一状态 |
| --- | --- |
| 已知、低风险、非外部本地读取 | `allow -> tool.started` |
| 精确的 `allow_once` / task / standing grant | `allow -> audit -> tool.started` |
| 外部、写入、控制或破坏性动作没有授权 | `block -> permission.requested` |
| 未知能力、无法规范化资源、权限服务失败 | `fail closed -> permission.denied` |
| 拒绝、过期、撤销、跨租户或父子越权 | `block -> no side effect` |

## 快速体验

```powershell
.\scripts\dev.ps1
```

打开 `http://127.0.0.1:5123`，在左侧选择 **Permissions**。当 Agent 请求 `web_fetch`、图像生成、删除或控制型工具时，工具不会先运行；界面显示工具、能力、规范化资源、风险、到期时间和重复请求次数，再提供 **Deny / Allow once / Allow for task / Allow 7 days**。授权后应重新发起或由 Chapter 14 的 Durable Task 恢复该动作。

运行确定性安全门禁：

```powershell
python -m klara.eval.permission_engine_cli `
  --json-out docs/reports/product/permission-engine.json `
  --markdown-out docs/reports/product/permission-engine.md `
  --markdown-en-out docs/reports/product/permission-engine.en.md
```

预期：所有检查通过，`critical_isolation_and_bypass_rate = 1.0`，原始参数泄漏为 `0`。

## 真实问题：模型说“我有权限”为什么不算权限

语言模型输出是不可信建议，不是授权来源。攻击文本可以要求忽略规则、换一个别名工具、双重编码 URL、穿越工作区路径，或者重复请求直到偶然放行。如果权限只依赖 prompt，模型的一句话就可能改变外部世界。

Chapter 13 的单一 `KlaraLoop`、工具执行器与 evidence controller 保持不变。本阶段只在真正的工具边界之前增加确定性链路：

```text
ToolCall
-> PermissionActionResolver
-> PermissionService.evaluate
-> HookDecision
-> allow: ToolExecutor
-> block: failed observation + approval request + audit
```

真实实现：

```text
src/klara/permissions/models.py
src/klara/permissions/resolver.py
src/klara/permissions/repository.py
src/klara/permissions/service.py
src/klara/permissions/hook.py
src/klara/app/harness.py
apps/api/routes/permissions.py
apps/web/src/components/PermissionCenter.tsx
```

## 机制一：先规范化动作，再查授权

`PermissionActionResolver` 不接受“看起来差不多”的资源。URL 会反复解码、统一 scheme/host/path，并丢弃可能含密钥的 query；路径用真实工作区根目录解析，`..` 与 symlink 逃逸都会失败；MCP 绑定 server/tool；Shell 只保存命令 hash，编码控制字符会直接拒绝。

<details>
<summary>展开：真实的 URL 资源规范化</summary>

输入是模型给出的 URL 字符串，输出是不会包含 query、fragment 或凭证的授权资源：

```python
value = _fully_unquote(raw)
parsed = urlsplit(value)
if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
    raise PermissionResolutionError("permission_invalid_url")
if parsed.username or parsed.password:
    raise PermissionResolutionError("permission_url_credentials_forbidden")
host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
normalized_path = posixpath.normpath(parsed.path or "/")
return f"{parsed.scheme.lower()}://{authority}{normalized_path}"
```

`https%3A%2F%2Fexample.com%2Fdocs` 和 `https://EXAMPLE.com/docs` 得到同一 scope；`http://127.0.0.1/admin`、带 userinfo 的 URL 或过度编码资源失败关闭。状态从原始 ToolCall 变成可比较的 `PermissionAction`；若转换失败，不会产生执行权限。

</details>

## 机制二：授权精确绑定身份、任务与资源

每个 request 和 grant 都保存 tenant、actor、agent、可选 task、tool、capability、side effect、resource type、canonical resource、risk、到期时间和参数 hash。匹配要求这些字段一致；换工具、换租户、换任务或提高风险都不能复用旧授权。

| effect | 可用范围 | 终止信号 |
| --- | --- | --- |
| `deny` | 精确动作与 owner | 撤销或过期 |
| `allow_once` | 精确动作的一次原子消费 | `consumed` |
| `allow_task` | 精确 task | task 不同、撤销或过期 |
| `allow_standing` | owner 下精确工具与资源 | 撤销或过期 |

<details>
<summary>展开：授权匹配与一次性原子消费</summary>

```python
if grant.scope.tenant_id != scope.tenant_id or grant.scope.actor_id != scope.actor_id:
    return False
if grant.scope.agent_id != scope.agent_id:
    return False
if grant.effect is PermissionEffect.ALLOW_TASK and grant.scope.task_id != scope.task_id:
    return False
return expected.tool_name == action.tool_name and expected.resource == action.resource
```

`allow_once` 在 SQLite 写锁与事务内把 `remaining_uses=1` 原子改为 `0` 与 `consumed`。并发的两个调用最多一个获得 authority；另一个重新进入审批请求，不会重复副作用。

</details>

## 机制三：子 Agent 只能衰减父授权

子 grant 必须保持相同 tenant/actor、相同动作、不能比父 grant 更久，也不能把 task grant 放大为 standing grant。父 grant 已拒绝、一次性、过期或撤销时不能委托。Chapter 16 会复用这条边界，而不是再实现一套权限系统。

## 机制四：用户看到的是可决策状态，不是原始参数

`PermissionCenter` 展示 action 与 canonical resource，支持拒绝、一次性、任务级、七天授权和撤销。API/SSE 只投影安全字段；原始工具参数、prompt、query 与 `arguments_sha256` 不进入公开事件。SQLite audit 也只保存动作元数据与 hash。

阻塞观测明确告诉模型“不要重试”，防止重复调用绕过或制造奇怪回答：

```text
Tool blocked: explicit user approval is required. Do not retry this action unless the user grants its exact scope.
```

这与用户问题一致：如果用户要求危险动作，Agent 应说明精确动作被拦截并等待决定，不能声称已经执行，也不能换工具暗中尝试。

## 测试与评估

```powershell
python -m pytest tests/klara/permissions tests/apps/api/test_permissions_route.py tests/klara/eval/test_permission_engine.py -q
python -m pytest -q
Set-Location apps/web
npm test -- --run
npm run build
```

安全门禁覆盖：低风险策略、外部审批、deny、once、task、standing、expiry、revocation、audit、restart、租户隔离、父子衰减、并发一次性消费、替代工具、MCP、路径穿越、symlink、private URL、编码 URL、编码 Shell 与未知能力。

## 练习

1. 在 `resolver.py` 加入一个 file-write fixture，验证同一路径的大小写或相对别名不会扩大授权。
2. 在 `test_permission_engine.py` 增加一个 task grant 的重启测试，确认 task 不同后仍然拒绝。
3. 在 Permission Center 用键盘完成 deny 和 revoke，并检查 focus 没有落到 dialog 外。
4. 查看 `permissions.sqlite3`，证明测试 secret 没有以明文出现。

## 局限与下一章

本阶段没有声称覆盖所有 Shell 语法；未知语法失败关闭。当前同步 run 被审批阻塞后会得到失败观测，不会在内存线程中无限等待；用户授权后需要重新发起，真正的持久 pause/resume、lease、attempt history 与 crash recovery 属于 Chapter 14 Durable Tasks。权限系统自身已可被该章节直接复用。
