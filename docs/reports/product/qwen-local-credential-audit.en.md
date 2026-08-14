# Local Qwen Credential Audit

Language: [Chinese](./qwen-local-credential-audit.md) | English

- Verdict: `no usable Qwen credential found`
- Matching dotenv files: `5`
- Non-empty entries: `3`
- Distinct credentials: `2`
- Live probes: `2/2 returned HTTP 401`
- Working fallback: `deepseek/deepseek-v4-flash`

The audit covered relevant dotenv files under the owner's Desktop and Codex directories plus process-environment variable names. The current project credential matches another Desktop copy; a Desktop backup contains a second distinct credential. A minimal real tool-call probe against `qwen/qwen3.7-flash` returned typed `provider_authentication_failed` / HTTP 401 for both distinct credentials.

No API key, prefix, suffix, or fingerprint is stored in this report. Browser password stores, cloud consoles, and unrelated documents were intentionally excluded. Continuing with DeepSeek is therefore a real fallback, not a Qwen quality result. Qwen candidate and cross-model independent-judge runs still require a new or repaired DashScope credential.
