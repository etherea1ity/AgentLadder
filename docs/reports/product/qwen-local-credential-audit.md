# 千问本机凭据审计

语言：中文 | [English](./qwen-local-credential-audit.en.md)

- 结论：`没有找到可用的千问凭据`
- 发现相关 dotenv 文件：`5`
- 非空配置项：`3`
- 去重后的凭据：`2`
- 真实探针：`2/2 均返回 HTTP 401`
- 可工作的回退：`deepseek/deepseek-v4-flash`

审计覆盖桌面与 Codex 目录中的相关 dotenv 文件以及当前进程环境变量名。项目当前凭据和另一个桌面副本相同；桌面备份中还有一份不同凭据。我对两份不同凭据都用 `qwen/qwen3.7-flash` 发出了最小真实工具调用，服务端均返回类型化的 `provider_authentication_failed` / HTTP 401。

报告没有保存 API Key、前后缀或指纹，也没有读取浏览器密码库、云控制台和无关文档。因此，当前继续用 DeepSeek 是真实 fallback，不代表千问质量不合格；千问候选和跨模型独立裁判仍需新的或修复后的 DashScope 凭据。
