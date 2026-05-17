from __future__ import annotations

import hashlib
import json
import os
import shlex
import socket
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch", "ApplyPatch"}
READ_TOOLS = {"Read", "Grep", "Glob", "LS"}

DEFAULT_TOOL_MATCHER = (
    "Task|Bash|Shell|exec_command|functions\\.exec_command|apply_patch|ApplyPatch|"
    "Read|Write|Edit|MultiEdit|NotebookEdit|Grep|Glob|LS|"
    "WebFetch|WebSearch|TodoWrite|update_plan|spawn_agent|send_input|wait_agent|mcp__.*"
)

DEFAULT_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "Read": {"category": "filesystem.read", "impact": "high"},
    "Grep": {"category": "filesystem.search", "impact": "medium"},
    "Glob": {"category": "filesystem.search", "impact": "medium"},
    "LS": {"category": "filesystem.list", "impact": "medium"},
    "Write": {"category": "filesystem.write", "impact": "critical"},
    "Edit": {"category": "filesystem.write", "impact": "critical"},
    "MultiEdit": {"category": "filesystem.write", "impact": "critical"},
    "NotebookEdit": {"category": "filesystem.write", "impact": "critical"},
    "apply_patch": {"category": "filesystem.patch", "impact": "critical"},
    "ApplyPatch": {"category": "filesystem.patch", "impact": "critical"},
    "Bash": {"category": "shell", "impact": "critical"},
    "Shell": {"category": "shell", "impact": "critical"},
    "exec_command": {"category": "shell", "impact": "critical"},
    "functions.exec_command": {"category": "shell", "impact": "critical"},
    "WebFetch": {"category": "network.fetch", "impact": "medium"},
    "WebSearch": {"category": "network.search", "impact": "medium"},
    "TodoWrite": {"category": "planning", "impact": "medium"},
    "update_plan": {"category": "planning", "impact": "medium"},
    "Task": {"category": "agent.spawn", "impact": "high"},
    "spawn_agent": {"category": "agent.spawn", "impact": "high"},
    "send_input": {"category": "agent.control", "impact": "high"},
    "wait_agent": {"category": "agent.control", "impact": "medium"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def aid_home() -> Path:
    return Path(os.environ.get("AID_HOME", "~/.aid")).expanduser()


def default_ledger_path() -> Path:
    return Path(os.environ.get("AID_LEDGER", aid_home() / "ledger.sqlite")).expanduser()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def file_hash(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def normalize_path(path: str | Path, cwd: str | Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(cwd or os.getcwd()) / candidate
    return candidate.resolve()


def resource_uri(path: str | Path, cwd: str | Path | None = None) -> str:
    return normalize_path(path, cwd).as_uri()


def detect_harness(input_json: dict[str, Any] | None = None) -> str:
    if os.environ.get("AID_HARNESS"):
        return os.environ["AID_HARNESS"]
    if input_json:
        if input_json.get("turn_id") or input_json.get("model"):
            return "codex"
        transcript = str(input_json.get("transcript_path") or "")
        if ".claude" in transcript or input_json.get("hook_event_name"):
            if "codex" not in transcript.lower():
                return "claude"
    if os.environ.get("CODEX_HOME"):
        return "codex"
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_PROJECT_DIR"):
        return "claude"
    return "unknown"


def default_actor_id() -> str:
    base = (
        os.environ.get("AID_ACTOR")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "unknown"
    )
    harness = detect_harness()
    if harness and harness not in ("unknown", "bash"):
        return f"{base}/{harness}"
    return base


def stable_session_id(input_json: dict[str, Any] | None = None) -> str:
    if input_json and input_json.get("session_id"):
        return str(input_json["session_id"])
    if os.environ.get("AID_SESSION_ID"):
        return os.environ["AID_SESSION_ID"]
    cwd = str(Path(os.getcwd()).resolve())
    seed = f"{socket.gethostname()}:{os.getppid()}:{cwd}"
    return "local-" + short_hash(seed)


def current_git_head(cwd: str | Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def git_root(cwd: str | Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def env_enabled(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "off", "no"}


def gitnexus_enabled() -> bool:
    return env_enabled("AID_GITNEXUS", default=True)


def strict_missing_read_enabled() -> bool:
    return env_enabled("AID_STRICT_MISSING_READ", default=True)


def awareness_line_budget() -> int:
    raw = os.environ.get("AID_AWARENESS_LINES", "8")
    try:
        return max(3, min(40, int(raw)))
    except ValueError:
        return 8


def awareness_text_budget() -> int:
    raw = os.environ.get("AID_AWARENESS_CHARS", "140")
    try:
        return max(60, min(500, int(raw)))
    except ValueError:
        return 140


def clip_text(value: str | None, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    limit = limit or awareness_text_budget()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def run_gitnexus(args: list[str], cwd: str | Path, timeout: int = 8) -> subprocess.CompletedProcess[str] | None:
    if not gitnexus_enabled():
        return None
    if not shutil_which("gitnexus"):
        return None
    try:
        proc = subprocess.run(
            ["gitnexus", *args],
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode == 0:
        return proc
    return None


def shutil_which(command: str) -> str | None:
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / command
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def gitnexus_file_context(path: str | Path, cwd: str | Path | None = None) -> dict[str, Any] | None:
    if not gitnexus_enabled():
        return None
    normalized = normalize_path(path, cwd)
    root = git_root(normalized.parent) or git_root(cwd or normalized.parent)
    if not root:
        return {
            "enabled": True,
            "path": str(normalized),
            "available": False,
            "importance": "unknown",
            "summary": "GitNexus skipped: target is not inside a git repository.",
        }
    run_cwd = root
    rel = str(normalized)
    try:
        rel = str(normalized.relative_to(root))
    except Exception:
        pass

    context: dict[str, Any] = {
        "enabled": True,
        "path": rel,
        "available": False,
        "importance": "unknown",
        "summary": "",
    }
    proc = run_gitnexus(["query", rel], run_cwd, timeout=8)
    if not proc:
        context["summary"] = "GitNexus unavailable, disabled, or repo not indexed."
        return context
    output = (proc.stdout or proc.stderr or "").strip()
    context["available"] = True
    context["summary"] = output[:1200]
    lowered = output.lower()
    hits = sum(token in lowered for token in ["critical", "route", "api", "handler", "caller", "impact", "process"])
    if hits >= 3:
        context["importance"] = "high"
    elif hits >= 1:
        context["importance"] = "medium"
    else:
        context["importance"] = "low"
    return context


@dataclass
class Decision:
    decision: str
    reason: str = ""
    context: str = ""
    resource_paths: tuple[str, ...] = ()

    @property
    def should_block(self) -> bool:
        return self.decision == "block"


class Ledger:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or default_ledger_path()).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS actors (
              actor_id TEXT PRIMARY KEY,
              display_name TEXT,
              kind TEXT,
              home_harness TEXT,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              actor_id TEXT,
              harness TEXT,
              cwd TEXT,
              transcript_path TEXT,
              parent_session_id TEXT,
              started_at TEXT,
              ended_at TEXT,
              metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS goals (
              goal_id TEXT PRIMARY KEY,
              session_id TEXT,
              summary TEXT,
              raw_prompt_hash TEXT,
              source TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS resources (
              resource_id TEXT PRIMARY KEY,
              uri TEXT UNIQUE,
              repo_root TEXT,
              kind TEXT,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
              event_id TEXT PRIMARY KEY,
              session_id TEXT,
              goal_id TEXT,
              resource_id TEXT,
              event_type TEXT,
              tool_name TEXT,
              status TEXT,
              before_hash TEXT,
              after_hash TEXT,
              diff_summary TEXT,
              line_ranges_json TEXT,
              created_at TEXT,
              metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS claims (
              claim_id TEXT PRIMARY KEY,
              session_id TEXT,
              resource_id TEXT,
              intent TEXT,
              status TEXT,
              created_at TEXT,
              expires_at TEXT
            );
            CREATE TABLE IF NOT EXISTS evaluations (
              evaluation_id TEXT PRIMARY KEY,
              event_id TEXT,
              reviewer_session_id TEXT,
              reviewer_actor_id TEXT,
              verdict TEXT,
              reason TEXT,
              evidence_uri TEXT,
              created_at TEXT,
              metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS outcomes (
              outcome_id TEXT PRIMARY KEY,
              event_id TEXT,
              kind TEXT,
              summary TEXT,
              evidence_uri TEXT,
              created_at TEXT,
              metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS adaptation_hints (
              hint_id TEXT PRIMARY KEY,
              source_event_id TEXT,
              pattern TEXT,
              recommendation TEXT,
              confidence TEXT,
              created_at TEXT,
              metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS thoughts (
              thought_id TEXT PRIMARY KEY,
              session_id TEXT,
              goal_id TEXT,
              event_id TEXT,
              kind TEXT,
              summary TEXT,
              created_at TEXT,
              metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS conditions (
              condition_id TEXT PRIMARY KEY,
              event_id TEXT,
              session_id TEXT,
              resource_id TEXT,
              kind TEXT,
              description TEXT,
              required INTEGER,
              satisfied INTEGER,
              evidence TEXT,
              created_at TEXT,
              metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS hazards (
              hazard_id TEXT PRIMARY KEY,
              session_id TEXT,
              resource_id TEXT,
              hazard_type TEXT,
              severity TEXT,
              message TEXT,
              created_at TEXT,
              resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tool_registry (
              tool_name TEXT PRIMARY KEY,
              category TEXT,
              impact TEXT,
              pre_hook INTEGER,
              post_hook INTEGER,
              path_mode TEXT,
              created_at TEXT,
              updated_at TEXT,
              metadata_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_resource_created
              ON events(resource_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_events_session_resource
              ON events(session_id, resource_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_goals_session_created
              ON goals(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_evaluations_event
              ON evaluations(event_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_outcomes_event
              ON outcomes(event_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_thoughts_session_created
              ON thoughts(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_thoughts_event_created
              ON thoughts(event_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_conditions_event
              ON conditions(event_id, created_at);
            """
        )
        self.seed_default_tools()
        self.conn.commit()

    def seed_default_tools(self) -> None:
        now = utc_now()
        for tool_name, spec in DEFAULT_TOOL_SPECS.items():
            self.conn.execute(
                """
                INSERT INTO tool_registry(
                  tool_name, category, impact, pre_hook, post_hook,
                  path_mode, created_at, updated_at, metadata_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tool_name) DO NOTHING
                """,
                (
                    tool_name,
                    spec.get("category", "custom"),
                    spec.get("impact", "medium"),
                    1,
                    1,
                    spec.get("path_mode", "auto"),
                    now,
                    now,
                    json_dumps({"source": "default"}),
                ),
            )

    def register_tool(
        self,
        tool_name: str,
        category: str = "custom",
        impact: str = "medium",
        pre_hook: bool = True,
        post_hook: bool = True,
        path_mode: str = "auto",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO tool_registry(
              tool_name, category, impact, pre_hook, post_hook,
              path_mode, created_at, updated_at, metadata_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tool_name) DO UPDATE SET
              category=excluded.category,
              impact=excluded.impact,
              pre_hook=excluded.pre_hook,
              post_hook=excluded.post_hook,
              path_mode=excluded.path_mode,
              updated_at=excluded.updated_at,
              metadata_json=excluded.metadata_json
            """,
            (
                tool_name,
                category,
                impact,
                1 if pre_hook else 0,
                1 if post_hook else 0,
                path_mode,
                now,
                now,
                json_dumps(metadata or {}),
            ),
        )
        self.conn.commit()

    def tool_registration(self, tool_name: str) -> sqlite3.Row | None:
        row = self.conn.execute(
            "SELECT * FROM tool_registry WHERE tool_name=?",
            (tool_name,),
        ).fetchone()
        if row:
            return row
        if tool_name.startswith("mcp__"):
            self.register_tool(tool_name, category="mcp", impact="high", metadata={"source": "auto-mcp"})
            return self.tool_registration(tool_name)
        if "." in tool_name:
            self.register_tool(tool_name, category="external", impact="medium", metadata={"source": "auto-dotted"})
            return self.tool_registration(tool_name)
        return None

    def list_tools(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT * FROM tool_registry
                ORDER BY CASE impact
                  WHEN 'critical' THEN 0
                  WHEN 'high' THEN 1
                  WHEN 'medium' THEN 2
                  WHEN 'low' THEN 3
                  ELSE 4
                END, tool_name
                """
            )
        )

    def ensure_actor(
        self,
        actor_id: str | None = None,
        display_name: str | None = None,
        kind: str = "agent",
        home_harness: str = "unknown",
    ) -> str:
        actor_id = actor_id or default_actor_id()
        self.conn.execute(
            """
            INSERT INTO actors(actor_id, display_name, kind, home_harness, created_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(actor_id) DO UPDATE SET
              display_name=COALESCE(excluded.display_name, actors.display_name),
              home_harness=excluded.home_harness
            """,
            (actor_id, display_name or actor_id, kind, home_harness, utc_now()),
        )
        self.conn.commit()
        return actor_id

    def ensure_session(
        self,
        session_id: str,
        actor_id: str | None = None,
        harness: str = "unknown",
        cwd: str | None = None,
        transcript_path: str | None = None,
        parent_session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        actor_id = self.ensure_actor(actor_id, home_harness=harness)
        self.conn.execute(
            """
            INSERT INTO sessions(
              session_id, actor_id, harness, cwd, transcript_path,
              parent_session_id, started_at, metadata_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              actor_id=excluded.actor_id,
              harness=excluded.harness,
              cwd=COALESCE(excluded.cwd, sessions.cwd),
              transcript_path=COALESCE(excluded.transcript_path, sessions.transcript_path),
              metadata_json=excluded.metadata_json
            """,
            (
                session_id,
                actor_id,
                harness,
                cwd or os.getcwd(),
                transcript_path,
                parent_session_id,
                utc_now(),
                json_dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return session_id

    def set_goal(
        self,
        session_id: str,
        summary: str,
        source: str = "manual",
        raw_prompt: str | None = None,
    ) -> str:
        summary = " ".join(summary.split())
        goal_id = "goal-" + short_hash(f"{session_id}:{summary}:{raw_prompt or ''}")
        raw_hash = short_hash(raw_prompt) if raw_prompt else None
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO goals(goal_id, session_id, summary, raw_prompt_hash, source, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(goal_id) DO UPDATE SET
              summary=excluded.summary,
              updated_at=excluded.updated_at
            """,
            (goal_id, session_id, summary[:500], raw_hash, source, now, now),
        )
        self.conn.commit()
        return goal_id

    def current_goal(self, session_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM goals
            WHERE session_id=?
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()

    def ensure_resource(self, path: str | Path, cwd: str | Path | None = None) -> tuple[str, Path]:
        normalized = normalize_path(path, cwd)
        uri = normalized.as_uri()
        resource_id = "res-" + short_hash(uri)
        root = git_root(normalized.parent if normalized.suffix else normalized) or git_root(cwd or os.getcwd())
        kind = "file" if normalized.suffix or normalized.exists() and normalized.is_file() else "path"
        self.conn.execute(
            """
            INSERT INTO resources(resource_id, uri, repo_root, kind, created_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(uri) DO UPDATE SET repo_root=COALESCE(excluded.repo_root, resources.repo_root)
            """,
            (resource_id, uri, root, kind, utc_now()),
        )
        self.conn.commit()
        return resource_id, normalized

    def record_event(
        self,
        session_id: str,
        event_type: str,
        path: str | Path | None = None,
        cwd: str | Path | None = None,
        goal_id: str | None = None,
        tool_name: str | None = None,
        status: str = "success",
        before_hash: str | None = None,
        after_hash: str | None = None,
        diff_summary: str | None = None,
        line_ranges: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        resource_id = None
        normalized = None
        if path is not None:
            resource_id, normalized = self.ensure_resource(path, cwd)
            if after_hash is None and event_type in {"read", "write", "patch"}:
                after_hash = file_hash(normalized)
        if goal_id is None:
            current = self.current_goal(session_id)
            goal_id = current["goal_id"] if current else None
        event_id = "evt-" + uuid.uuid4().hex[:20]
        self.conn.execute(
            """
            INSERT INTO events(
              event_id, session_id, goal_id, resource_id, event_type, tool_name,
              status, before_hash, after_hash, diff_summary, line_ranges_json,
              created_at, metadata_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                session_id,
                goal_id,
                resource_id,
                event_type,
                tool_name,
                status,
                before_hash,
                after_hash,
                diff_summary,
                json_dumps(line_ranges) if line_ranges is not None else None,
                utc_now(),
                json_dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return event_id

    def record_thought(
        self,
        session_id: str,
        kind: str,
        summary: str,
        goal_id: str | None = None,
        event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if goal_id is None:
            current = self.current_goal(session_id)
            goal_id = current["goal_id"] if current else None
        thought_id = "th-" + uuid.uuid4().hex[:20]
        self.conn.execute(
            """
            INSERT INTO thoughts(thought_id, session_id, goal_id, event_id, kind, summary, created_at, metadata_json)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (thought_id, session_id, goal_id, event_id, kind, summary[:2000], utc_now(), json_dumps(metadata or {})),
        )
        self.conn.commit()
        return thought_id

    def record_condition(
        self,
        session_id: str,
        kind: str,
        description: str,
        required: bool,
        satisfied: bool,
        event_id: str | None = None,
        resource_id: str | None = None,
        evidence: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        condition_id = "cond-" + uuid.uuid4().hex[:20]
        self.conn.execute(
            """
            INSERT INTO conditions(
              condition_id, event_id, session_id, resource_id, kind, description,
              required, satisfied, evidence, created_at, metadata_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                condition_id,
                event_id,
                session_id,
                resource_id,
                kind,
                description,
                1 if required else 0,
                1 if satisfied else 0,
                evidence,
                utc_now(),
                json_dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return condition_id

    def last_read(self, session_id: str, resource_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM events
            WHERE session_id=? AND resource_id=? AND event_type='read'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id, resource_id),
        ).fetchone()

    def recent_events_for_resource(
        self,
        resource_id: str,
        limit: int = 10,
        exclude_session: str | None = None,
        event_types: Iterable[str] | None = None,
    ) -> list[sqlite3.Row]:
        clauses = ["e.resource_id=?"]
        params: list[Any] = [resource_id]
        if exclude_session:
            clauses.append("e.session_id<>?")
            params.append(exclude_session)
        if event_types:
            values = list(event_types)
            clauses.append("e.event_type IN (%s)" % ",".join("?" for _ in values))
            params.extend(values)
        params.append(limit)
        return list(
            self.conn.execute(
                f"""
                SELECT e.*, s.actor_id, s.harness, g.summary AS goal_summary, r.uri
                FROM events e
                LEFT JOIN sessions s ON s.session_id=e.session_id
                LEFT JOIN goals g ON g.goal_id=e.goal_id
                LEFT JOIN resources r ON r.resource_id=e.resource_id
                WHERE {' AND '.join(clauses)}
                ORDER BY e.created_at DESC
                LIMIT ?
                """,
                params,
            )
        )

    def evaluations_for_resource(self, resource_id: str, limit: int = 5) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT ev.*, e.event_type, e.tool_name, e.session_id, s.actor_id, g.summary AS goal_summary
                FROM evaluations ev
                JOIN events e ON e.event_id=ev.event_id
                LEFT JOIN sessions s ON s.session_id=e.session_id
                LEFT JOIN goals g ON g.goal_id=e.goal_id
                WHERE e.resource_id=?
                ORDER BY ev.created_at DESC
                LIMIT ?
                """,
                (resource_id, limit),
            )
        )

    def add_evaluation(
        self,
        event_id: str,
        verdict: str,
        reason: str,
        reviewer_session_id: str | None = None,
        reviewer_actor_id: str | None = None,
        evidence_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        evaluation_id = "eval-" + uuid.uuid4().hex[:20]
        self.conn.execute(
            """
            INSERT INTO evaluations(
              evaluation_id, event_id, reviewer_session_id, reviewer_actor_id,
              verdict, reason, evidence_uri, created_at, metadata_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id,
                event_id,
                reviewer_session_id,
                reviewer_actor_id,
                verdict,
                reason,
                evidence_uri,
                utc_now(),
                json_dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        if verdict in {"good", "bad", "mixed"}:
            self.add_adaptation_hint(
                event_id,
                pattern=verdict,
                recommendation=reason,
                confidence="medium",
                metadata={"source": "evaluation"},
            )
        return evaluation_id

    def add_outcome(
        self,
        event_id: str,
        kind: str,
        summary: str,
        evidence_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        outcome_id = "out-" + uuid.uuid4().hex[:20]
        self.conn.execute(
            """
            INSERT INTO outcomes(outcome_id, event_id, kind, summary, evidence_uri, created_at, metadata_json)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (outcome_id, event_id, kind, summary, evidence_uri, utc_now(), json_dumps(metadata or {})),
        )
        self.conn.commit()
        return outcome_id

    def add_adaptation_hint(
        self,
        source_event_id: str,
        pattern: str,
        recommendation: str,
        confidence: str = "low",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        hint_id = "hint-" + uuid.uuid4().hex[:20]
        self.conn.execute(
            """
            INSERT INTO adaptation_hints(
              hint_id, source_event_id, pattern, recommendation,
              confidence, created_at, metadata_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (hint_id, source_event_id, pattern, recommendation, confidence, utc_now(), json_dumps(metadata or {})),
        )
        self.conn.commit()
        return hint_id

    def add_hazard(
        self,
        session_id: str,
        resource_id: str,
        hazard_type: str,
        severity: str,
        message: str,
    ) -> str:
        hazard_id = "haz-" + uuid.uuid4().hex[:20]
        self.conn.execute(
            """
            INSERT INTO hazards(hazard_id, session_id, resource_id, hazard_type, severity, message, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (hazard_id, session_id, resource_id, hazard_type, severity, message, utc_now()),
        )
        self.conn.commit()
        return hazard_id

    def event_chain(self, event_id: str) -> dict[str, Any]:
        event = self.conn.execute(
            """
            SELECT e.*, r.uri, r.repo_root, s.actor_id, s.harness, s.cwd,
                   g.summary AS goal_summary
            FROM events e
            LEFT JOIN resources r ON r.resource_id=e.resource_id
            LEFT JOIN sessions s ON s.session_id=e.session_id
            LEFT JOIN goals g ON g.goal_id=e.goal_id
            WHERE e.event_id=?
            """,
            (event_id,),
        ).fetchone()
        if not event:
            raise KeyError(f"event not found: {event_id}")
        thoughts = list(
            self.conn.execute(
                "SELECT * FROM thoughts WHERE event_id=? OR session_id=? ORDER BY created_at DESC LIMIT 20",
                (event_id, event["session_id"]),
            )
        )
        conditions = list(
            self.conn.execute(
                "SELECT * FROM conditions WHERE event_id=? ORDER BY created_at",
                (event_id,),
            )
        )
        evaluations = list(
            self.conn.execute(
                "SELECT * FROM evaluations WHERE event_id=? ORDER BY created_at",
                (event_id,),
            )
        )
        outcomes = list(
            self.conn.execute(
                "SELECT * FROM outcomes WHERE event_id=? ORDER BY created_at",
                (event_id,),
            )
        )
        hints = list(
            self.conn.execute(
                "SELECT * FROM adaptation_hints WHERE source_event_id=? ORDER BY created_at",
                (event_id,),
            )
        )
        return {
            "event": dict(event),
            "thoughts": [dict(row) for row in thoughts],
            "conditions": [dict(row) for row in conditions],
            "evaluations": [dict(row) for row in evaluations],
            "outcomes": [dict(row) for row in outcomes],
            "adaptation_hints": [dict(row) for row in hints],
        }

    def awareness(self, session_id: str, path: str | Path, cwd: str | Path | None = None) -> dict[str, Any]:
        resource_id, normalized = self.ensure_resource(path, cwd)
        current = file_hash(normalized)
        gn_context = gitnexus_file_context(normalized, cwd)
        last_read = self.last_read(session_id, resource_id)
        recent_writes = self.recent_events_for_resource(
            resource_id, limit=3, exclude_session=session_id, event_types=("write", "patch", "delete", "move")
        )
        recent_reads = self.recent_events_for_resource(
            resource_id, limit=2, exclude_session=session_id, event_types=("read",)
        )
        evaluations = self.evaluations_for_resource(resource_id, limit=2)
        goal = self.current_goal(session_id)
        session = self.conn.execute(
            """
            SELECT s.*, a.display_name, a.kind AS actor_kind
            FROM sessions s LEFT JOIN actors a ON a.actor_id=s.actor_id
            WHERE s.session_id=?
            """,
            (session_id,),
        ).fetchone()
        return {
            "session": dict(session) if session else {"session_id": session_id},
            "goal": dict(goal) if goal else None,
            "resource": {
                "resource_id": resource_id,
                "path": str(normalized),
                "uri": normalized.as_uri(),
                "exists": normalized.exists(),
                "hash": current,
            },
            "my_last_read": dict(last_read) if last_read else None,
            "recent_writes": [dict(row) for row in recent_writes],
            "recent_reads": [dict(row) for row in recent_reads],
            "evaluations": [dict(row) for row in evaluations],
            "behavior_context": {
                "gitnexus": gn_context,
            },
        }

    def pre_write_decision(
        self,
        session_id: str,
        path: str | Path,
        cwd: str | Path | None = None,
        strict_missing_read: bool = False,
    ) -> Decision:
        awareness = self.awareness(session_id, path, cwd)
        resource = awareness["resource"]
        resource_id = resource["resource_id"]
        exists = resource["exists"]
        current_hash = resource["hash"]
        last_read = awareness["my_last_read"]
        recent_writes = awareness["recent_writes"]
        evaluations = awareness["evaluations"]

        lines = compact_awareness_lines(awareness)
        context = "\n".join(lines)

        if not exists:
            self.record_condition(
                session_id,
                "resource-exists",
                "Target resource does not exist; treating this as a new-file write.",
                required=False,
                satisfied=False,
                resource_id=resource_id,
                evidence=resource["path"],
            )
            return Decision("allow", context=context, resource_paths=(resource["path"],))

        if not last_read:
            message = f"AID: {resource['path']} has not been read by this session before writing."
            self.add_hazard(session_id, resource_id, "missing-read", "warn", message)
            self.record_condition(
                session_id,
                "read-before-write",
                "Existing file should be read by this session before writing.",
                required=True,
                satisfied=False,
                resource_id=resource_id,
                evidence=message,
            )
            if strict_missing_read:
                return Decision("block", reason=message, context=context, resource_paths=(resource["path"],))
            return Decision("warn", reason=message, context=context, resource_paths=(resource["path"],))

        read_hash = last_read["after_hash"]
        self.record_condition(
            session_id,
            "read-before-write",
            "Existing file was read by this session before writing.",
            required=True,
            satisfied=True,
            resource_id=resource_id,
            evidence=str(read_hash or "")[:16],
        )
        if read_hash and current_hash and read_hash != current_hash:
            message = (
                f"AID blocked stale write: {resource['path']} changed after this session last read it. "
                "Read the latest file or inspect recent activity before editing."
            )
            self.add_hazard(session_id, resource_id, "stale-read", "block", message)
            self.record_condition(
                session_id,
                "fresh-read",
                "Last read hash must match current file hash before writing.",
                required=True,
                satisfied=False,
                resource_id=resource_id,
                evidence=f"last_read={str(read_hash)[:16]} current={str(current_hash)[:16]}",
            )
            return Decision("block", reason=message, context=context, resource_paths=(resource["path"],))

        self.record_condition(
            session_id,
            "fresh-read",
            "Last read hash matches current file hash before writing.",
            required=True,
            satisfied=True,
            resource_id=resource_id,
            evidence=str(current_hash or "")[:16],
        )

        if recent_writes or evaluations:
            return Decision("warn", context=context, resource_paths=(resource["path"],))

        return Decision("allow", context=context, resource_paths=(resource["path"],))


def compact_awareness_lines(awareness: dict[str, Any], max_lines: int | None = None) -> list[str]:
    max_lines = max_lines or awareness_line_budget()
    path = awareness["resource"]["path"]
    lines = [f"AID awareness for {path}:"]
    goal = awareness.get("goal")
    if goal:
        lines.append(f"- Goal: {clip_text(goal['summary'])}")
    last_read = awareness.get("my_last_read")
    if last_read:
        lines.append(f"- Your last read: {last_read['created_at']} hash {str(last_read['after_hash'] or '')[:12]}")
    else:
        lines.append("- Your last read: none recorded")
    risk_lines: list[str] = []
    for row in awareness.get("recent_writes", [])[:3]:
        who = row.get("actor_id") or row.get("session_id")
        why = clip_text(row.get("goal_summary") or "unknown goal")
        risk_lines.append(f"- Recent write: {who}/{row.get('session_id')} at {row.get('created_at')}, goal: {why}")
    for row in awareness.get("evaluations", [])[:2]:
        verdict = row.get("verdict")
        reason = clip_text(row.get("reason") or "")
        risk_lines.append(f"- Prior evaluation: {verdict}, {reason}")
    lines.extend(risk_lines)
    for row in awareness.get("recent_reads", [])[:2]:
        who = row.get("actor_id") or row.get("session_id")
        why = clip_text(row.get("goal_summary") or "unknown goal")
        lines.append(f"- Recent read: {who}/{row.get('session_id')} at {row.get('created_at')}, goal: {why}")
    gitnexus = (awareness.get("behavior_context") or {}).get("gitnexus")
    if gitnexus:
        if gitnexus.get("available"):
            lines.append(f"- GitNexus importance: {gitnexus.get('importance', 'unknown')}")
            summary = clip_text(gitnexus.get("summary") or "")
            if summary:
                lines.append(f"- GitNexus context: {summary}")
        else:
            lines.append(f"- GitNexus context: {clip_text(gitnexus.get('summary'))}")
    if len(lines) == 2:
        lines.append("- No peer writes or evaluations found for this resource.")
    if len(lines) > max_lines:
        hidden = len(lines) - max_lines + 1
        return lines[: max_lines - 1] + [f"- More context clipped: {hidden} lines. Use `aid recent` or `aid chain` to expand."]
    return lines


def extract_prompt(input_json: dict[str, Any]) -> str | None:
    for key in ("prompt", "user_prompt", "message", "text"):
        value = input_json.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_patch_paths(text: str, cwd: str | Path | None = None) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        prefixes = ("*** Update File: ", "*** Add File: ", "*** Delete File: ")
        for prefix in prefixes:
            if line.startswith(prefix):
                paths.append(str(normalize_path(line[len(prefix) :].strip(), cwd)))
    return paths


def extract_bash_write_paths(command: str, cwd: str | Path | None = None) -> list[str]:
    paths: list[str] = []
    tokens = command.replace(";", " ").split()
    for index, token in enumerate(tokens):
        if token in {">", ">>"} and index + 1 < len(tokens):
            paths.append(str(normalize_path(tokens[index + 1].strip("'\""), cwd)))
        elif token.startswith(">") and len(token) > 1:
            paths.append(str(normalize_path(token[1:].strip("'\""), cwd)))
        elif token == "-i" and index > 0 and "sed" in tokens[max(0, index - 2) : index]:
            if tokens:
                candidate = tokens[-1].strip("'\"")
                if candidate and not candidate.startswith("-"):
                    paths.append(str(normalize_path(candidate, cwd)))
    if tokens and tokens[0] in {"rm", "mv", "cp"}:
        for candidate in tokens[1:]:
            if candidate.startswith("-"):
                continue
            paths.append(str(normalize_path(candidate.strip("'\""), cwd)))
    return list(dict.fromkeys(paths))


def extract_read_paths(tool_name: str, tool_input: dict[str, Any], cwd: str | Path | None = None) -> list[str]:
    if tool_name in READ_TOOLS and tool_input.get("file_path"):
        return [str(normalize_path(tool_input["file_path"], cwd))]
    if tool_name in {"Grep", "Glob", "LS"}:
        paths = []
        for key in ("path", "file_path", "directory"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                paths.append(str(normalize_path(value, cwd)))
        return paths
    return []


def extract_write_paths(tool_name: str, tool_input: dict[str, Any], cwd: str | Path | None = None) -> list[str]:
    paths: list[str] = []
    if tool_name in WRITE_TOOLS:
        if tool_input.get("file_path"):
            paths.append(str(normalize_path(tool_input["file_path"], cwd)))
        patch = (
            tool_input.get("patch")
            or tool_input.get("input")
            or tool_input.get("content")
            or tool_input.get("command")
        )
        if isinstance(patch, str):
            paths.extend(extract_patch_paths(patch, cwd))
    if tool_name == "Bash":
        command = str(tool_input.get("command") or "")
        paths.extend(extract_bash_write_paths(command, cwd))
    return list(dict.fromkeys(paths))


def tool_metadata(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "tool_name": row["tool_name"],
        "category": row["category"],
        "impact": row["impact"],
        "pre_hook": bool(row["pre_hook"]),
        "post_hook": bool(row["post_hook"]),
        "path_mode": row["path_mode"],
    }


def hook_response(event_name: str, decision: Decision) -> dict[str, Any]:
    context = decision.context
    if decision.reason and decision.reason not in context:
        context = f"{decision.reason}\n{context}" if context else decision.reason
    payload: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
        }
    }
    if context:
        payload["hookSpecificOutput"]["additionalContext"] = context
    if decision.should_block:
        payload["decision"] = "block"
        payload["reason"] = decision.reason
        payload["hookSpecificOutput"]["permissionDecision"] = "deny"
        payload["hookSpecificOutput"]["permissionDecisionReason"] = decision.reason
    return payload


def merge_decisions(decisions: list[Decision]) -> Decision:
    if not decisions:
        return Decision("allow")
    block = next((d for d in decisions if d.should_block), None)
    contexts = [d.context for d in decisions if d.context]
    paths: list[str] = []
    for decision in decisions:
        paths.extend(decision.resource_paths)
    if block:
        return Decision("block", reason=block.reason, context="\n".join(contexts), resource_paths=tuple(paths))
    if any(d.decision == "warn" for d in decisions):
        reason = next((d.reason for d in decisions if d.decision == "warn" and d.reason), "")
        return Decision("warn", reason=reason, context="\n".join(contexts), resource_paths=tuple(paths))
    return Decision("allow", context="\n".join(contexts), resource_paths=tuple(paths))


def handle_hook(input_json: dict[str, Any], event_override: str | None = None, ledger: Ledger | None = None) -> dict[str, Any] | None:
    ledger = ledger or Ledger()
    event = event_override or input_json.get("hook_event_name") or ""
    session_id = stable_session_id(input_json)
    cwd = input_json.get("cwd") or os.getcwd()
    harness = detect_harness(input_json)
    ledger.ensure_session(
        session_id=session_id,
        actor_id=default_actor_id(),
        harness=harness,
        cwd=cwd,
        transcript_path=input_json.get("transcript_path"),
        metadata={"hook_event_name": event, "permission_mode": input_json.get("permission_mode")},
    )

    normalized_event = event.replace("_", "-").lower()
    if normalized_event in {"session-start", "sessionstart"}:
        context = f"AID active: session {session_id}, actor {default_actor_id()}, harness {harness}."
        return {"hookSpecificOutput": {"hookEventName": input_json.get("hook_event_name", "SessionStart"), "additionalContext": context}}

    if normalized_event in {"user-prompt-submit", "userpromptsubmit"}:
        prompt = extract_prompt(input_json)
        if prompt:
            summary = prompt[:300]
            ledger.set_goal(session_id, summary, source="user_prompt", raw_prompt=prompt)
            ledger.record_thought(
                session_id,
                "intent",
                f"User goal captured for this session: {summary}",
                metadata={"source": "UserPromptSubmit"},
            )
            context = f"AID goal recorded for session {session_id}: {summary[:180]}"
            return {"hookSpecificOutput": {"hookEventName": input_json.get("hook_event_name", "UserPromptSubmit"), "additionalContext": context}}
        return None

    tool_name = str(input_json.get("tool_name") or "")
    tool_input = input_json.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    registration = ledger.tool_registration(tool_name)
    if tool_name and not registration:
        ledger.register_tool(
            tool_name,
            category="custom",
            impact="medium",
            metadata={"source": "auto-seen-hook"},
        )
        registration = ledger.tool_registration(tool_name)
    registration_metadata = tool_metadata(registration)

    if normalized_event in {"pre-tool-use", "pretooluse"}:
        ledger.record_event(
            session_id,
            "tool-pre",
            tool_name=tool_name,
            status="started",
            metadata={
                "tool_input": tool_input,
                "tool_registration": registration_metadata,
                "source": "hook",
            },
        )
        paths = extract_write_paths(tool_name, tool_input, cwd)
        if not paths:
            return None
        strict = strict_missing_read_enabled()
        decisions = [ledger.pre_write_decision(session_id, path, cwd, strict_missing_read=strict) for path in paths]
        decision = merge_decisions(decisions)
        ledger.record_thought(
            session_id,
            "precondition-check",
            f"Pre-write check for {', '.join(paths)} returned {decision.decision}. {decision.reason or 'No blocking reason.'}",
            metadata={"tool_name": tool_name, "paths": paths},
        )
        if decision.decision == "allow":
            return None
        return hook_response(input_json.get("hook_event_name", "PreToolUse"), decision)

    if normalized_event in {"post-tool-use", "posttooluse"}:
        paths = extract_read_paths(tool_name, tool_input, cwd)
        tool_response = input_json.get("tool_response") or input_json.get("tool_output")
        ledger.record_event(
            session_id,
            "tool",
            tool_name=tool_name,
            status="success",
            metadata={
                "tool_input": tool_input,
                "tool_response": tool_response,
                "tool_registration": registration_metadata,
                "source": "hook",
            },
        )
        for path in paths:
            ledger.record_event(
                session_id,
                "read",
                path=path,
                cwd=cwd,
                tool_name=tool_name,
                metadata={"tool_input": tool_input, "tool_response": tool_response, "tool_registration": registration_metadata},
            )
        write_paths = extract_write_paths(tool_name, tool_input, cwd)
        for path in write_paths:
            ledger.record_event(
                session_id,
                "write" if tool_name != "apply_patch" else "patch",
                path=path,
                cwd=cwd,
                tool_name=tool_name,
                metadata={"tool_input": tool_input, "tool_response": tool_response, "tool_registration": registration_metadata},
            )
        if paths or write_paths:
            changed = ", ".join(Path(p).name for p in paths + write_paths)
            return {
                "hookSpecificOutput": {
                    "hookEventName": input_json.get("hook_event_name", "PostToolUse"),
                    "additionalContext": f"AID recorded {tool_name} activity: {changed}",
                }
            }
        if tool_name:
            return {
                "hookSpecificOutput": {
                    "hookEventName": input_json.get("hook_event_name", "PostToolUse"),
                    "additionalContext": f"AID recorded {tool_name} tool activity",
                }
            }
    return None
