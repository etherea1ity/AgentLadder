# Klara README Conventions Reference

Klara READMEs must work as GitHub landing pages, teaching guides, and source-code walkthroughs.

## Output Locations

For the active chapter, maintain both:

- Root preview: `README.md` and `README.en.md` when the branch should display the chapter on GitHub.
- Chapter archive: `docs/chapters/<chapter-slug>.md` and `docs/chapters/<chapter-slug>.en.md`.

Fix relative links when copying chapter docs into root README files:

- Root image path: `./docs/assets/...`
- Chapter image path: `../assets/...`
- Root roadmap path: `./docs/skills/roadmap.md`
- Chapter roadmap path: `../skills/roadmap.md`
- Root language toggle: `README.md` <-> `README.en.md`
- Chapter language toggle: `<chapter>.md` <-> `<chapter>.en.md`

## Required Chapter Structure

Use this order:

1. Title and bilingual navigation.
2. Previous / next chapter navigation.
3. Roadmap link.
4. Main chapter contents: what this chapter builds and intentionally excludes.
5. One clear chapter image.
6. Core idea section, such as loop, tool registry, memory, RAG, or hooks.
7. Compact input -> process -> output flow.
8. Code map with real paths.
9. Main teaching sections.
10. Code walkthroughs inside `<details>`.
11. Run and verification instructions.
12. Next chapter preview.

## Outer Layer

The visible README must be readable without opening `<details>`.

For each teaching section, include:

- the problem solved
- a compact flow block
- what Klara learns
- real code paths

Do not hide code paths inside `<details>`.

Use this shape:

````md
## 2. Loop 接收依赖，不自己创建世界

1-3 short paragraphs that enter the topic quickly.

```text
input
-> process
-> output
```

Klara learns: ...

对应代码：

```text
src/klara/core/loop.py
```

<details>
<summary>展开：KlaraLoop.__init__ 逐行精读</summary>

Real code and line-by-line explanation.

</details>
````

## Code Walkthroughs

Use real code blocks from the repository. Explain in execution order.

For each code block:

1. Explain why this code appears at this point in the run.
2. Show real code.
3. Explain important parameters, variables, and emitted events.
4. State the architecture boundary protected by the code.

Prefer concrete walkthroughs over abstract explanation.

## Images

Each chapter should have one clear visual near the top.

Use generated raster images when useful. Save project-bound images under:

```text
docs/assets/
```

Requirements:

- landscape layout
- clear labels
- no tiny unreadable text
- no fake UI screenshots unless the chapter is about UI
- no chain-of-thought wording
- visually explain the chapter's runtime idea

## Bilingual Docs

Write Chinese first unless asked otherwise, then create the English mirror.

The English version must preserve structure, diagrams, code blocks, paths, commands, and section order. Translate prose; do not invent new technical claims.

## Run And Verification

Use realistic local execution instructions.

For Chapter 1 and similar full-stack chapters:

```powershell
Copy-Item .env.example .env
```

List required keys without secrets:

```text
DEEPSEEK_API_KEY=...
DASHSCOPE_API_KEY=...
```

Prefer the one-command dev script when available:

```powershell
.\scripts\dev.ps1
```

List default URLs and targeted tests. Do not claim tests passed unless they were run in the current task.

## Stop Checks

Before finishing README work, verify:

- root README displays the intended chapter if requested
- bilingual links are not broken
- image paths exist
- `<details>` open and close counts match
- code paths referenced in visible sections exist or are intentionally future-facing
- run commands match current scripts and config
- targeted tests were run, or the validation gap is reported
