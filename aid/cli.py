from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .core import (
    DEFAULT_TOOL_MATCHER,
    Ledger,
    compact_awareness_lines,
    default_actor_id,
    default_ledger_path,
    detect_harness,
    extract_bash_write_paths,
    handle_hook,
    json_dumps,
    strict_missing_read_enabled,
    stable_session_id,
)
from . import __version__


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def print_json(value: Any) -> None:
    print(json_dumps(value))


def cmd_init(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    print(f"AID ledger initialized: {ledger.path}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    info = {
        "version": __version__,
        "ledger": str(ledger.path),
        "home": str(ledger.path.parent),
        "actor": default_actor_id(),
        "session": os.environ.get("AID_SESSION_ID"),
        "harness": os.environ.get("AID_HARNESS") or "auto",
    }
    print_json(info) if args.json else print("\n".join(f"{k}: {v}" for k, v in info.items()))
    return 0


def cmd_session_start(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    session_id = args.session_id or stable_session_id(None)
    harness = args.harness or detect_harness(None)
    ledger.ensure_session(session_id, args.actor or default_actor_id(), harness=harness, cwd=args.cwd)
    goal_id = None
    if args.goal:
        goal_id = ledger.set_goal(session_id, args.goal, source="manual")
    output = {"session_id": session_id, "goal_id": goal_id, "ledger": str(ledger.path)}
    print_json(output)
    return 0


def cmd_goal_set(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    session_id = args.session_id or stable_session_id(None)
    ledger.ensure_session(session_id, args.actor or default_actor_id(), harness=args.harness or detect_harness(None), cwd=args.cwd)
    goal_id = ledger.set_goal(session_id, args.summary, source="manual")
    print_json({"session_id": session_id, "goal_id": goal_id})
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    session_id = args.session_id or stable_session_id(None)
    ledger.ensure_session(session_id, args.actor or default_actor_id(), harness=args.harness or detect_harness(None), cwd=args.cwd)
    event_id = ledger.record_event(
        session_id,
        args.event_type,
        path=args.path,
        cwd=args.cwd,
        tool_name=args.tool,
        status=args.status,
        metadata={"source": "manual-record"},
    )
    print_json({"event_id": event_id, "session_id": session_id})
    return 0


def cmd_think(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    session_id = args.session_id or stable_session_id(None)
    ledger.ensure_session(session_id, args.actor or default_actor_id(), harness=args.harness or detect_harness(None), cwd=args.cwd)
    thought_id = ledger.record_thought(
        session_id,
        args.kind,
        args.summary,
        event_id=args.event_id,
        metadata={"source": "manual-think"},
    )
    print_json({"thought_id": thought_id, "session_id": session_id, "event_id": args.event_id})
    return 0


def cmd_condition(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    session_id = args.session_id or stable_session_id(None)
    ledger.ensure_session(session_id, args.actor or default_actor_id(), harness=args.harness or detect_harness(None), cwd=args.cwd)
    resource_id = None
    if args.path:
        resource_id, _ = ledger.ensure_resource(args.path, args.cwd)
    condition_id = ledger.record_condition(
        session_id,
        args.kind,
        args.description,
        required=not args.optional,
        satisfied=args.satisfied,
        event_id=args.event_id,
        resource_id=resource_id,
        evidence=args.evidence,
        metadata={"source": "manual-condition"},
    )
    print_json({"condition_id": condition_id, "session_id": session_id, "event_id": args.event_id})
    return 0


def cmd_chain(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    data = ledger.event_chain(args.event_id)
    if args.json:
        print_json(data)
        return 0
    event = data["event"]
    print(f"Event: {event['event_id']} {event['event_type']} {event['tool_name'] or '-'}")
    print(f"Actor/session: {event['actor_id']}/{event['session_id']} ({event['harness']})")
    print(f"Goal: {event['goal_summary'] or '-'}")
    print(f"Resource: {event['uri'] or '-'}")
    if data["conditions"]:
        print("Conditions:")
        for row in data["conditions"]:
            state = "ok" if row["satisfied"] else "missing"
            print(f"- [{state}] {row['kind']}: {row['description']} ({row['evidence'] or '-'})")
    if data["thoughts"]:
        print("Thoughts:")
        for row in data["thoughts"][:8]:
            print(f"- {row['kind']}: {row['summary']}")
    if data["outcomes"]:
        print("Outcomes:")
        for row in data["outcomes"]:
            print(f"- {row['kind']}: {row['summary']}")
    if data["evaluations"]:
        print("Evaluations:")
        for row in data["evaluations"]:
            print(f"- {row['verdict']}: {row['reason']}")
    if data["adaptation_hints"]:
        print("Adaptation:")
        for row in data["adaptation_hints"]:
            print(f"- {row['pattern']}: {row['recommendation']}")
    return 0


def cmd_recent(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    resource_id, path = ledger.ensure_resource(args.path, args.cwd)
    rows = ledger.recent_events_for_resource(resource_id, limit=args.limit)
    data = [dict(row) for row in rows]
    if args.json:
        print_json(data)
    else:
        if not data:
            print(f"No AID activity for {path}")
        for row in data:
            print(
                f"{row['created_at']} {row['event_type']} {row['tool_name'] or '-'} "
                f"{row['actor_id'] or row['session_id']} goal={row['goal_summary'] or '-'} event={row['event_id']}"
            )
    return 0


def cmd_awareness(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    session_id = args.session_id or stable_session_id(None)
    ledger.ensure_session(session_id, args.actor or default_actor_id(), harness=args.harness or detect_harness(None), cwd=args.cwd)
    data = ledger.awareness(session_id, args.path, args.cwd)
    if args.json:
        print_json(data)
    else:
        print("\n".join(compact_awareness_lines(data)))
    return 0


def cmd_check_write(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    session_id = args.session_id or stable_session_id(None)
    ledger.ensure_session(session_id, args.actor or default_actor_id(), harness=args.harness or detect_harness(None), cwd=args.cwd)
    strict = False if args.allow_missing_read else (args.strict_missing_read or strict_missing_read_enabled())
    decision = ledger.pre_write_decision(session_id, args.path, args.cwd, strict_missing_read=strict)
    data = {
        "decision": decision.decision,
        "reason": decision.reason,
        "context": decision.context,
        "resource_paths": decision.resource_paths,
    }
    print_json(data) if args.json else print(decision.context or decision.reason or decision.decision)
    return 2 if decision.should_block else 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    evaluation_id = ledger.add_evaluation(
        args.event_id,
        args.verdict,
        args.reason,
        reviewer_session_id=args.reviewer_session_id,
        reviewer_actor_id=args.reviewer_actor_id or default_actor_id(),
        evidence_uri=args.evidence,
    )
    print_json({"evaluation_id": evaluation_id, "event_id": args.event_id})
    return 0


def cmd_outcome(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    outcome_id = ledger.add_outcome(args.event_id, args.kind, args.summary, evidence_uri=args.evidence)
    print_json({"outcome_id": outcome_id, "event_id": args.event_id})
    return 0


def cmd_tool_list(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    rows = [dict(row) for row in ledger.list_tools()]
    if args.json:
        print_json(rows)
        return 0
    for row in rows:
        print(
            f"{row['tool_name']}\timpact={row['impact']}\tcategory={row['category']}\t"
            f"pre={bool(row['pre_hook'])}\tpost={bool(row['post_hook'])}\tpath_mode={row['path_mode']}"
        )
    return 0


def cmd_tool_register(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    metadata = {
        "source": "cli",
        "description": args.description,
        "resource_hints": args.resource_hint,
        "side_effects": args.side_effect,
    }
    ledger.register_tool(
        args.name,
        category=args.category,
        impact=args.impact,
        pre_hook=not args.no_pre,
        post_hook=not args.no_post,
        path_mode=args.path_mode,
        metadata=metadata,
    )
    print_json({"registered": args.name, "category": args.category, "impact": args.impact})
    return 0


def cmd_tool_explain(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    row = ledger.tool_registration(args.name)
    if not row:
        print(f"No AID tool registration found for {args.name}", file=sys.stderr)
        return 1
    data = dict(row)
    try:
        metadata = json.loads(data.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        metadata = {}
    payload = {**data, "metadata": metadata}
    if args.json:
        print_json(payload)
        return 0
    print(f"Tool: {data['tool_name']}")
    print(f"Category: {data['category']}")
    print(f"Impact: {data['impact']}")
    print(f"Pre/Post hook: {bool(data['pre_hook'])}/{bool(data['post_hook'])}")
    print(f"Path mode: {data['path_mode']}")
    if metadata.get("description"):
        print(f"Description: {metadata['description']}")
    if metadata.get("resource_hints"):
        print("Resource hints:")
        for hint in metadata["resource_hints"]:
            print(f"- {hint}")
    if metadata.get("side_effects"):
        print("Side effects:")
        for effect in metadata["side_effects"]:
            print(f"- {effect}")
    return 0


def cmd_tool_matcher(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    names = [row["tool_name"] for row in ledger.list_tools() if row["pre_hook"] or row["post_hook"]]
    escaped = [re.escape(name) for name in names]
    matcher = "|".join(dict.fromkeys([DEFAULT_TOOL_MATCHER, *escaped]))
    print(matcher)
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    payload = read_stdin_json()
    response = handle_hook(payload, event_override=args.event, ledger=ledger)
    if response:
        print_json(response)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    command_parts = list(args.command)
    if command_parts and command_parts[0] == "--":
        command_parts = command_parts[1:]
    if not command_parts:
        print("aid run requires a command after --", file=sys.stderr)
        return 2
    command = " ".join(command_parts)
    ledger = Ledger(args.ledger)
    session_id = args.session_id or stable_session_id(None)
    harness = args.harness or "bash"
    actor = args.actor or default_actor_id()
    ledger.ensure_session(session_id, actor, harness=harness, cwd=args.cwd)
    if args.goal:
        ledger.set_goal(session_id, args.goal, source="manual")
    ledger.record_thought(
        session_id,
        "intent",
        f"Manual bash command via AID: {command}",
        metadata={"source": "aid-run"},
    )

    write_paths = extract_bash_write_paths(command, args.cwd)
    for path in write_paths:
        strict = False if args.allow_missing_read else (args.strict_missing_read or strict_missing_read_enabled())
        decision = ledger.pre_write_decision(session_id, path, args.cwd, strict_missing_read=strict)
        if decision.context:
            print(decision.context, file=sys.stderr)
        if decision.should_block and not args.force:
            print(decision.reason, file=sys.stderr)
            return 2

    run_event = ledger.record_event(
        session_id,
        "run",
        tool_name="Bash",
        status="started",
        metadata={"command": command, "source": "aid-run", "write_paths": write_paths},
    )
    proc = subprocess.run(command, cwd=args.cwd, shell=True)
    status = "success" if proc.returncode == 0 else "failure"
    ledger.add_outcome(run_event, "command-exit", f"Command exited with {proc.returncode}")
    ledger.record_event(
        session_id,
        "run",
        tool_name="Bash",
        status=status,
        metadata={"command": command, "exit_code": proc.returncode, "source_event_id": run_event},
    )
    if proc.returncode == 0:
        for path in write_paths:
            ledger.record_event(
                session_id,
                "write",
                path=path,
                cwd=args.cwd,
                tool_name="Bash",
                metadata={"command": command, "source": "aid-run"},
            )
    return proc.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aid", description="Agent Identity Daemon: shared agent operation timeline")
    parser.add_argument("--ledger", default=str(default_ledger_path()), help="Path to ledger SQLite database")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("doctor")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("session")
    session_sub = p.add_subparsers(dest="session_command", required=True)
    p_start = session_sub.add_parser("start")
    p_start.add_argument("--session-id")
    p_start.add_argument("--actor")
    p_start.add_argument("--harness")
    p_start.add_argument("--cwd", default=os.getcwd())
    p_start.add_argument("--goal")
    p_start.set_defaults(func=cmd_session_start)

    p = sub.add_parser("goal")
    goal_sub = p.add_subparsers(dest="goal_command", required=True)
    p_set = goal_sub.add_parser("set")
    p_set.add_argument("summary")
    p_set.add_argument("--session-id")
    p_set.add_argument("--actor")
    p_set.add_argument("--harness")
    p_set.add_argument("--cwd", default=os.getcwd())
    p_set.set_defaults(func=cmd_goal_set)

    p = sub.add_parser("record")
    p.add_argument("event_type", choices=["read", "write", "patch", "delete", "move", "run", "claim", "tool", "tool-pre"])
    p.add_argument("path")
    p.add_argument("--session-id")
    p.add_argument("--actor")
    p.add_argument("--harness")
    p.add_argument("--cwd", default=os.getcwd())
    p.add_argument("--tool")
    p.add_argument("--status", default="success")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("think")
    p.add_argument("kind", choices=["observation", "intent", "plan", "precondition-check", "reflection", "adaptation"])
    p.add_argument("summary")
    p.add_argument("--event-id")
    p.add_argument("--session-id")
    p.add_argument("--actor")
    p.add_argument("--harness")
    p.add_argument("--cwd", default=os.getcwd())
    p.set_defaults(func=cmd_think)

    p = sub.add_parser("condition")
    p.add_argument("kind")
    p.add_argument("description")
    p.add_argument("--event-id")
    p.add_argument("--path")
    p.add_argument("--session-id")
    p.add_argument("--actor")
    p.add_argument("--harness")
    p.add_argument("--cwd", default=os.getcwd())
    p.add_argument("--optional", action="store_true")
    p.add_argument("--satisfied", action="store_true")
    p.add_argument("--evidence")
    p.set_defaults(func=cmd_condition)

    p = sub.add_parser("chain")
    p.add_argument("event_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_chain)

    p = sub.add_parser("recent")
    p.add_argument("path")
    p.add_argument("--cwd", default=os.getcwd())
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_recent)

    p = sub.add_parser("awareness")
    p.add_argument("path")
    p.add_argument("--session-id")
    p.add_argument("--actor")
    p.add_argument("--harness")
    p.add_argument("--cwd", default=os.getcwd())
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_awareness)

    p = sub.add_parser("check-write")
    p.add_argument("path")
    p.add_argument("--session-id")
    p.add_argument("--actor")
    p.add_argument("--harness")
    p.add_argument("--cwd", default=os.getcwd())
    p.add_argument("--strict-missing-read", action="store_true")
    p.add_argument("--allow-missing-read", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check_write)

    p = sub.add_parser("evaluate")
    p.add_argument("event_id")
    p.add_argument("--verdict", required=True, choices=["good", "bad", "mixed", "uncertain"])
    p.add_argument("--reason", required=True)
    p.add_argument("--evidence")
    p.add_argument("--reviewer-session-id")
    p.add_argument("--reviewer-actor-id")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("outcome")
    p.add_argument("event_id")
    p.add_argument("--kind", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--evidence")
    p.set_defaults(func=cmd_outcome)

    p = sub.add_parser("tool")
    tool_sub = p.add_subparsers(dest="tool_command", required=True)
    p_list = tool_sub.add_parser("list")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_tool_list)

    p_register = tool_sub.add_parser("register")
    p_register.add_argument("name")
    p_register.add_argument("--category", default="custom")
    p_register.add_argument("--impact", choices=["low", "medium", "high", "critical"], default="medium")
    p_register.add_argument("--path-mode", choices=["none", "auto", "read", "write"], default="auto")
    p_register.add_argument("--description")
    p_register.add_argument("--resource-hint", action="append", default=[])
    p_register.add_argument("--side-effect", action="append", default=[])
    p_register.add_argument("--no-pre", action="store_true")
    p_register.add_argument("--no-post", action="store_true")
    p_register.set_defaults(func=cmd_tool_register)

    p_explain = tool_sub.add_parser("explain")
    p_explain.add_argument("name")
    p_explain.add_argument("--json", action="store_true")
    p_explain.set_defaults(func=cmd_tool_explain)

    p_matcher = tool_sub.add_parser("matcher")
    p_matcher.set_defaults(func=cmd_tool_matcher)

    p = sub.add_parser("hook")
    p.add_argument("event", nargs="?", help="Override hook event name, e.g. pre-tool-use")
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("run")
    p.add_argument("--session-id")
    p.add_argument("--actor")
    p.add_argument("--harness")
    p.add_argument("--cwd", default=os.getcwd())
    p.add_argument("--goal")
    p.add_argument("--strict-missing-read", action="store_true")
    p.add_argument("--allow-missing-read", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
