# Chapter 9: Skills / Procedural Memory

Language: [Chinese](./ch09-skills-procedural-memory.md) | English

Previous: [Chapter 8: Error Recovery and Fallback](./ch08-error-recovery-and-fallback.en.md)

Next: [Chapter 10: Memory System](../skills/roadmap.md#chapter-10---memory-system)

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## Chapter in one sentence

Klara first sees only compact Skill metadata; a procedure body enters the next private model context only after an explicit `skill_view` call passes dependency, tool, and permission validation.

![Klara Skills progressive disclosure](../assets/ch09-skills-runtime.svg)

| Signal | Klara action |
| --- | --- |
| `skills_list` | Return name, description, version, scope, hash, and declarations without reading bodies |
| Valid `skill_view(name)` | Load one body so the next model turn can use it |
| Invalid tool, permission, dependency, or reference | Fail closed and emit `skills.load_rejected` |
| No Skill selected | Keep bodies outside context and answer or continue normally |

## Quick experience

```powershell
.\scripts\dev.ps1
```

Open `http://127.0.0.1:5123` and choose **Skills** in the sidebar. The page shows the resolved catalog, `project → user → built_in` precedence, and declarations, but never instruction bodies.

Run the deterministic loading gate:

```powershell
python -m klara.eval.chapter09_cli `
  --json-out docs/reports/product/ch09-skills-runtime.json `
  --markdown-out docs/reports/product/ch09-skills-runtime.md `
  --markdown-en-out docs/reports/product/ch09-skills-runtime.en.md
```

Expected result: every check passes. The fixture's private Skill body appears only in the second model-call prompt, never in public trace, API, or UI output.

## The real problem: what if every tutorial is placed in every prompt?

Procedural knowledge differs from factual memory. It describes how a class of work should proceed, such as inspecting repository state before editing and running tests afterward. Attaching every procedure to every call wastes context and creates rule interference. Allowing a procedure to grant its own permissions would also create a prompt-based privilege-escalation path.

Chapter 8's loop, tool execution, and recovery path remain unchanged. This chapter adds one controlled path:

```text
catalog metadata
-> model selects one Skill
-> runtime validates dependencies / allowed tools / granted permissions
-> body is read
-> next private model prompt uses it
```

Implementation:

```text
src/klara/skills/catalog.py
src/klara/skills/tools.py
src/klara/skills/controller.py
src/klara/app/harness.py
```

## Mechanism 1: three catalogs use fixed precedence

Klara supports `built_in`, `user`, and `project` sources. Identical names resolve in this order:

```text
project > user > built_in
```

Lower-precedence bodies are never merged. The catalog retains their shadowed metadata for audit. Version, source, file hash, tools, permissions, dependencies, and references remain metadata.

<details>
<summary>Expand: how the catalog resolves one version</summary>

`SkillCatalog` sorts by name, scope weight, and source before updating the resolved entry:

```python
for entry in sorted(entries, key=lambda value: (
    value.descriptor.name,
    _SCOPE_PRIORITY[value.descriptor.scope],
    value.descriptor.source,
)):
    previous = self._entries.get(entry.descriptor.name)
    if previous is not None:
        self._shadowed.setdefault(entry.descriptor.name, []).append(
            previous.descriptor
        )
    self._entries[entry.descriptor.name] = entry
```

The input is `_SkillEntry` values discovered from three roots. The output is one resolved entry per name plus auditable shadowed definitions. No body has entered model context at this point.

State change: `filesystem packages -> resolved metadata catalog`.

Boundary: catalog resolution belongs to `klara.skills`, not `klara.core`.

</details>

## Mechanism 2: `skills_list` and `skill_view` are separate

`skills_list` supports capability discovery through a compact catalog. `skill_view` requires one explicit name and may optionally read a declared reference.

| Field | Consumer | Current behavior |
| --- | --- | --- |
| `description` | model and Skills UI | Decide whether a procedure is relevant |
| `version` / `sha256` | trace and evaluation | Pin the exact replayable version |
| `tools` | `SkillCatalog.load` | Must already be allowed for this run |
| `permissions` | `SkillCatalog.load` | Must already be granted externally |
| `dependencies` | `SkillCatalog.load` | Missing dependencies fail; nothing is installed implicitly |
| `references` | `skill_view` | Only declared files inside the package are readable |

<details>
<summary>Expand: how the body affects only the next turn</summary>

After `SkillViewTool` validates the request, its observation contains only the loaded identity. `SkillRuntimeController` confirms the same catalog entry and retains its body:

```python
document = self.catalog.load(name, reference=reference)
self._loaded[(name, reference)] = document
```

The controller produces `<loaded_skills>` only when the next model-call prompt is assembled:

```python
def system_prompt_suffix(self) -> str:
    if not self._loaded:
        return ""
    ...
```

The first model call cannot see the body; the second can use the selected procedure. The body is not written to conversation history, so it does not become a user message or implicit cross-run memory.

State change: `metadata-only -> selected -> validated -> loaded-for-this-run`.

</details>

## Mechanism 3: instruction text cannot grant authority

A Skill may declare requirements, but cannot approve itself. Loading requires:

```text
declared tools ⊆ frozen visible tools
declared permissions ⊆ externally granted permissions
declared dependencies ⊆ resolved catalog
reference path ⊆ Skill package root
```

Even if a body says to ignore policy and execute a shell, an undeclared runtime shell causes `skill_tool_not_allowed:shell`. The later Permission Engine remains the sole source of action authority.

## Mechanism 4: lifecycle is public while bodies remain private

Public events are:

```text
skills.catalog_ready
skills.selected
skills.loaded
skills.load_rejected
```

They contain only name, version, scope, hash, reference, and outcome. Skill bodies are private model-visible prompt material and never enter public trace, SSE, or the Skills page.

Frontend path:

```text
apps/api/routes/skills.py
apps/web/src/components/SkillsCatalog.tsx
apps/web/src/styles/app.css
```

The UI projects the real `/api/skills` catalog instead of maintaining a second source of truth.

## Run and verify

Targeted tests:

```powershell
python -m pytest tests/klara/skills tests/klara/eval/test_chapter09.py tests/apps/api/test_skills_route.py -q
```

Frontend verification:

```powershell
Push-Location apps/web
npm test
npm run build
Pop-Location
```

Full regression:

```powershell
python -m pytest -q
```

## Small experiments

1. Create three same-named Skills in temporary project, user, and built-in roots; prove project wins and the shadow order is stable.
2. Declare a tool absent from the run; prove the body never reaches the prompt and trace contains a rejection.
3. Add `references/checklist.md`; compare `skill_view(name)` with the reference-specific call.
4. Open the Skills page at mobile width and verify long names, declarations, and errors do not overflow horizontally.

## Limitations

This chapter does not implement a remote marketplace, automatic installation, organization-wide publication approval, or a plugin ecosystem. The user directory remains a local single-user adapter; Chapter 18 adds production Auth, tenancy, and persistence boundaries.

## Next chapter

Chapter 10 implements long-term Memory. Facts, preferences, episodes, and task continuity gain their own scope, provenance, time, update, forgetting, and deletion semantics instead of borrowing Skills for factual storage.
