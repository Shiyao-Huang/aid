#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

from aid.core import Ledger, compact_awareness_lines


def title(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def show_lines(prefix: str, lines: list[str], keep: int = 8) -> None:
    print(prefix)
    for line in lines[:keep]:
        print("  " + line)


def no_aid_scene(root: Path) -> None:
    title("SCENE 1 - WITHOUT AID: everyone edits in the dark")
    file_path = root / "payment_schema.txt"
    file_path.write_text("version = 1\nowner = alice\n", encoding="utf-8")

    alice_memory = file_path.read_text(encoding="utf-8")
    file_path.write_text("version = 2\nowner = bob\nnew_field = risk_score\n", encoding="utf-8")
    file_path.write_text(alice_memory.replace("owner = alice", "owner = alice\nnote = quick fix"), encoding="utf-8")

    print("Alice read v1. Bob wrote v2. Alice wrote from old memory.")
    print("Result:")
    print(file_path.read_text(encoding="utf-8").rstrip())
    print("Pain: Bob's new field vanished. There is no who, no why, no warning.")


def aid_conflict_scene(root: Path) -> None:
    title("SCENE 2 - WITH AID: the room suddenly remembers")
    old_gitnexus = os.environ.get("AID_GITNEXUS")
    os.environ["AID_GITNEXUS"] = "0"
    ledger = Ledger(root / "aid.sqlite")
    file_path = root / "shared_schema.txt"
    file_path.write_text("version = 1\nowner = alice\n", encoding="utf-8")

    ledger.ensure_session("codex-alice", "Alice", harness="codex", cwd=str(root))
    ledger.set_goal("codex-alice", "safely update shared schema")
    ledger.record_event("codex-alice", "read", path=file_path, cwd=root, tool_name="Read")

    ledger.ensure_session("claude-bob", "Bob", harness="claude", cwd=str(root))
    ledger.set_goal("claude-bob", "add risk score to payment schema")
    file_path.write_text("version = 2\nowner = bob\nnew_field = risk_score\n", encoding="utf-8")
    bob_event = ledger.record_event("claude-bob", "write", path=file_path, cwd=root, tool_name="Write")

    decision = ledger.pre_write_decision("codex-alice", file_path, root)
    print(f"Decision: {decision.decision.upper()}")
    print(f"Reason: {decision.reason}")
    show_lines("Awareness injected into Alice:", decision.context.splitlines())

    title("SCENE 3 - FEEDBACK TURNS INTO FUTURE BEHAVIOR")
    ledger.add_evaluation(
        bob_event,
        "bad",
        "Changed a shared schema while Alice had an older read. Coordinate before touching shared schema.",
        reviewer_actor_id="reviewer",
    )
    chain = ledger.event_chain(bob_event)
    print("Operation author:", chain["event"]["actor_id"], "/", chain["event"]["harness"])
    print("Operation goal:", chain["event"]["goal_summary"])
    print("Evaluation:", chain["evaluations"][0]["verdict"], "-", chain["evaluations"][0]["reason"])
    print("Adaptation hint:", chain["adaptation_hints"][0]["pattern"], "->", chain["adaptation_hints"][0]["recommendation"])
    ledger.close()
    if old_gitnexus is None:
        os.environ.pop("AID_GITNEXUS", None)
    else:
        os.environ["AID_GITNEXUS"] = old_gitnexus


def bash_scene(root: Path) -> None:
    title("SCENE 4 - BASH ALSO GETS A NAME TAG")
    ledger_path = root / "bash.sqlite"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["AID_GITNEXUS"] = "0"
    run_proc = subprocess.run(
        [
            "python3",
            "-m",
            "aid.cli",
            "--ledger",
            str(ledger_path),
            "run",
            "--session-id",
            "shell-session",
            "--actor",
            "shell-user",
            "--goal",
            "write release note from plain bash",
            "--force",
            "--",
            "printf 'ship it\\n' > release.txt",
        ],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    print("AID told Bash before writing:")
    for line in run_proc.stderr.splitlines()[:4]:
        print("  " + line)
    proc = subprocess.run(
        [
            "python3",
            "-m",
            "aid.cli",
            "--ledger",
            str(ledger_path),
            "recent",
            str(root / "release.txt"),
        ],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    print(proc.stdout.strip())


def gitnexus_scene(root: Path) -> None:
    title("SCENE 5 - GITNEXUS ADDS CODE DANGER SENSE")
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    target = repo / "api.py"
    target.write_text("def handler():\n    return 'ok'\n", encoding="utf-8")

    fake_bin = root / "bin"
    fake_bin.mkdir()
    gitnexus = fake_bin / "gitnexus"
    gitnexus.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'critical API handler impact: callers, process flow, route map, execution flow'\n",
        encoding="utf-8",
    )
    gitnexus.chmod(gitnexus.stat().st_mode | stat.S_IXUSR)

    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(fake_bin) + os.pathsep + old_path
    os.environ["AID_GITNEXUS"] = "1"
    ledger = Ledger(root / "gitnexus.sqlite")
    ledger.ensure_session("codex-impact", "ImpactAgent", harness="codex", cwd=str(repo))
    awareness = ledger.awareness("codex-impact", target, repo)
    show_lines("Awareness with GitNexus:", compact_awareness_lines(awareness))
    ledger.close()
    os.environ["PATH"] = old_path


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        no_aid_scene(root)
        aid_conflict_scene(root)
        bash_scene(root)
        gitnexus_scene(root)

    title("THE PUNCHLINE")
    print("Before AID: agents collide and we debug the ashes.")
    print("After AID: every agent enters with identity, memory, context, and consequences.")
    print("That is the jump from tool calls to a living workspace.")


if __name__ == "__main__":
    main()
