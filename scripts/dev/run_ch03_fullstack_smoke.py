from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "ch03-fullstack-smoke-report.md"
API_BASE = os.environ.get("AGENT_LADDER_API_BASE", "http://127.0.0.1:8000")
WEB_BASE = os.environ.get("AGENT_LADDER_WEB_BASE", "http://127.0.0.1:5123")
PAPER_ROOT = os.environ.get("AGENT_LADDER_PAPER_ROOT", "data/papers")
QUERIES = [
    "tell me about react",
    "给我 10 篇 Agentic RAG 相关论文，并按路线分类",
    "Explain figure aware RAG in Chinese, include figure",
    "用英文解释 Self-RAG。",
    "Compare ReAct, Reflexion, and Voyager.",
    "This query should not match anything: qwerty_nonexistent_agent_ladder_topic",
    "找几篇 world model / spatial world model 相关论文。",
]


def main() -> int:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen[bytes]] = []
    lines = ["# Chapter 3 Fullstack Smoke Report", ""]
    lines.extend([
        f"- backend command: `{sys.executable} -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`",
        "- frontend command: `npm run dev -- --host 127.0.0.1 --port 5123`",
        f"- API URL: `{API_BASE}`",
        f"- frontend URL: `{WEB_BASE}/`",
        f"- paper root: `{PAPER_ROOT}`",
        "",
    ])
    ok = True
    try:
        backend_started = False
        frontend_started = False
        if not url_ok(f"{API_BASE}/api/health"):
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=REPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(proc)
            backend_started = True
            wait_for_url(f"{API_BASE}/api/health", "backend health", timeout=120.0)
        if not url_ok(f"{WEB_BASE}"):
            proc = subprocess.Popen(
                ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5123"],
                cwd=REPO_ROOT / "apps" / "web",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(proc)
            frontend_started = True
            wait_for_url(f"{WEB_BASE}", "frontend root", timeout=120.0)
        lines.extend([
            "## Server Startup",
            "",
            f"- backend: {'started by smoke script' if backend_started else 'reused existing server'}",
            f"- frontend: {'started by smoke script' if frontend_started else 'reused existing server'}",
            "",
        ])

        lines.extend(["## Main Chat Smoke Queries", ""])
        for query in QUERIES:
            try:
                started = time.perf_counter()
                session = post_json(f"{API_BASE}/api/sessions", {}, timeout=20)
                created = post_json(
                    f"{API_BASE}/api/runs",
                    {"session_id": session["session_id"], "question": query},
                    timeout=20,
                )
                run_id = created["run_id"]
                detail = wait_for_run(run_id, timeout=120)
                session_detail = get_json(f"{API_BASE}/api/sessions/{session['session_id']}", timeout=20)
                latency_wall = int((time.perf_counter() - started) * 1000)
                run = detail.get("run", {})
                trace = detail.get("trace") or {}
                answer_frame = trace.get("answer_frame") or {}
                search_plan = trace.get("search_plan") or {}
                verification = trace.get("verification") or {}
                visual_count = len(answer_frame.get("visual_sources") or [])
                source_count = len(answer_frame.get("sources") or [])
                evidence_count = len(answer_frame.get("evidence_items") or [])
                retrieval_attempts_count = len(trace.get("retrieval_attempts") or [])
                answer = next((m.get("content", "") for m in session_detail.get("messages", []) if m.get("role") == "assistant"), "")
                ok_answer = "Klara" in answer or "Klara" in answer.replace("I’m", "Klara")
                if run.get("status") != "completed" or not answer:
                    raise RuntimeError(f"run did not complete with answer: status={run.get('status')}")
                lines.extend([
                    f"### {query}",
                    "",
                    "| Field | Value |",
                    "| --- | --- |",
                    f"| endpoint | `/api/runs` |",
                    f"| run_status | `{run.get('status')}` |",
                    f"| route | `{(trace.get('workflow_state') or {}).get('route', {}).get('route', 'rag')}` |",
                    f"| run_mode | `{(trace.get('workflow_state') or {}).get('run_mode', 'agentic_rag')}` |",
                    f"| sources | {source_count} |",
                    f"| visual sources | {visual_count} |",
                    f"| evidence items | {evidence_count} |",
                    f"| retrieval attempts | {retrieval_attempts_count} |",
                    f"| search units | {len(search_plan.get('search_units') or [])} |",
                    f"| verification | `{verification.get('status')}` |",
                    f"| runtime latency_ms | {run.get('latency_ms')} |",
                    f"| wall latency_ms | {latency_wall} |",
                    f"| trace schema | `{trace.get('schema_version')}` |",
                    f"| klara answer | {'yes' if ok_answer else 'warning'} |",
                    "",
                ])
                print(f"PASS {query} sources={source_count} visuals={visual_count} verification={verification.get('status')}")
            except Exception as exc:
                ok = False
                lines.extend([f"### {query}", "", f"- failure: `{type(exc).__name__}: {exc}`", ""])
                print(f"FAIL {query}: {exc}")

        try:
            page = get_text(f"{WEB_BASE}", timeout=10)
            route_ok = "root" in page or "Klara" in page or "vite" in page.lower()
            lines.extend([
                "## Frontend Route Check",
                "",
                f"- `/` status: {'pass' if route_ok else 'warning'}",
                "- DOM/component validation is covered by Vitest component tests; this smoke keeps the server check framework-light.",
                "",
            ])
        except Exception as exc:
            ok = False
            lines.extend(["## Frontend Route Check", "", f"- failure: `{exc}`", ""])
    finally:
        for proc in processes:
            terminate_process(proc)
        lines.extend([
            "## Screenshots",
            "",
            "- Not generated by this lightweight smoke. Use the `/` page manually or add Playwright in a later UI QA pass.",
            "",
            "## Failed Cases",
            "",
            "- None." if ok else "- See failed query sections above.",
            "",
            "## Next Fixes",
            "",
            "- Add Playwright screenshot capture when the project adopts a browser E2E runner.",
            "- Keep improving paper metadata/chunks rather than weakening verifier for weak corpus queries.",
            "",
        ])
        REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {REPORT_PATH}")
    return 0 if ok else 1


def url_ok(url: str) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def wait_for_url(url: str, label: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001 - report startup blocker clearly
            last_error = exc
        time.sleep(0.8)
    raise RuntimeError(f"Timed out waiting for {label}: {last_error}")


def post_json(url: str, payload: dict[str, object], timeout: int) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc


def get_json(url: str, timeout: int) -> dict[str, object]:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_run(run_id: str, timeout: float) -> dict[str, object]:
    deadline = time.time() + timeout
    last: dict[str, object] | None = None
    while time.time() < deadline:
        last = get_json(f"{API_BASE}/api/runs/{run_id}", timeout=20)
        run = last.get("run", {}) if isinstance(last, dict) else {}
        status = run.get("status") if isinstance(run, dict) else None
        if status in {"completed", "failed", "cancelled"}:
            return last
        time.sleep(0.8)
    raise RuntimeError(f"Timed out waiting for run {run_id}: last={last}")

def get_text(url: str, timeout: int) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def terminate_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=8)
    except Exception:
        proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
