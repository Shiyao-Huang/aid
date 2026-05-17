import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from aid.core import Ledger, handle_hook


class AidLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = Ledger(self.root / "ledger.sqlite")
        self.file = self.root / "demo.txt"
        self.file.write_text("v1\n", encoding="utf-8")

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_stale_write_blocks_and_chain_keeps_evaluation(self):
        self.ledger.ensure_session("s-a", "alice", harness="codex", cwd=str(self.root))
        self.ledger.set_goal("s-a", "edit demo safely")
        self.ledger.record_event("s-a", "read", path=self.file, cwd=self.root, tool_name="Read")

        self.ledger.ensure_session("s-b", "bob", harness="claude", cwd=str(self.root))
        self.ledger.set_goal("s-b", "change demo format")
        self.file.write_text("v2\n", encoding="utf-8")
        event_id = self.ledger.record_event("s-b", "write", path=self.file, cwd=self.root, tool_name="Write")
        self.ledger.add_evaluation(event_id, "bad", "Changed the file without coordinating with alice.")

        decision = self.ledger.pre_write_decision("s-a", self.file, self.root)

        self.assertEqual(decision.decision, "block")
        self.assertIn("stale write", decision.reason)
        self.assertIn("bob", decision.context)

        chain = self.ledger.event_chain(event_id)
        self.assertEqual(chain["event"]["actor_id"], "bob")
        self.assertEqual(chain["evaluations"][0]["verdict"], "bad")
        self.assertTrue(chain["adaptation_hints"])

    def test_thoughts_and_conditions_are_queryable_on_chain(self):
        self.ledger.ensure_session("s-a", "alice", harness="codex", cwd=str(self.root))
        event_id = self.ledger.record_event("s-a", "read", path=self.file, cwd=self.root, tool_name="Read")
        self.ledger.record_thought("s-a", "observation", "The file is small and safe to inspect.", event_id=event_id)
        self.ledger.record_condition(
            "s-a",
            "read-before-write",
            "Agent must read the file before editing it.",
            required=True,
            satisfied=True,
            event_id=event_id,
            evidence="Read event exists",
        )

        chain = self.ledger.event_chain(event_id)

        self.assertEqual(chain["thoughts"][0]["kind"], "observation")
        self.assertEqual(chain["conditions"][0]["kind"], "read-before-write")
        self.assertEqual(chain["conditions"][0]["satisfied"], 1)

    def test_gitnexus_context_can_mark_important_file(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake_gitnexus = fake_bin / "gitnexus"
        fake_gitnexus.write_text(
            "#!/usr/bin/env bash\n"
            "echo 'critical API handler impact callers process route execution flow'\n",
            encoding="utf-8",
        )
        fake_gitnexus.chmod(0o755)

        old_path = os.environ.get("PATH", "")
        old_flag = os.environ.get("AID_GITNEXUS")
        try:
            os.environ["PATH"] = str(fake_bin) + os.pathsep + old_path
            os.environ["AID_GITNEXUS"] = "1"
            self.ledger.ensure_session("s-g", "gitnexus-agent", harness="codex", cwd=str(self.root))

            awareness = self.ledger.awareness("s-g", self.file, self.root)

            gitnexus = awareness["behavior_context"]["gitnexus"]
            self.assertTrue(gitnexus["available"])
            self.assertEqual(gitnexus["importance"], "high")
        finally:
            os.environ["PATH"] = old_path
            if old_flag is None:
                os.environ.pop("AID_GITNEXUS", None)
            else:
                os.environ["AID_GITNEXUS"] = old_flag


class AidHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = Ledger(self.root / "ledger.sqlite")
        self.file = self.root / "hook.txt"
        self.file.write_text("hello\n", encoding="utf-8")

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_hooks_record_goal_read_and_warn_on_missing_read_for_other_session(self):
        response = handle_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "hook-a",
                "cwd": str(self.root),
                "prompt": "Update hook.txt carefully",
            },
            ledger=self.ledger,
        )
        self.assertIn("goal recorded", json.dumps(response))

        handle_hook(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "hook-a",
                "cwd": str(self.root),
                "tool_name": "Read",
                "tool_input": {"file_path": str(self.file)},
            },
            ledger=self.ledger,
        )

        response = handle_hook(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "hook-b",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.file), "content": "bye\n"},
            },
            ledger=self.ledger,
        )

        self.assertIsNotNone(response)
        encoded = json.dumps(response)
        self.assertIn("has not been read", encoded)
        self.assertIn("hook-a", encoded)

    def test_codex_apply_patch_command_paths_are_traced(self):
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "codex-apply",
            "cwd": str(self.root),
            "turn_id": "turn-1",
            "model": "gpt-5",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": (
                    "*** Begin Patch\n"
                    "*** Update File: hook.txt\n"
                    "@@\n"
                    "-hello\n"
                    "+hello world\n"
                    "*** End Patch\n"
                )
            },
        }

        response = handle_hook(payload, ledger=self.ledger)

        self.assertIsNotNone(response)
        encoded = json.dumps(response)
        self.assertIn("has not been read", encoded)
        self.assertIn("hook.txt", encoded)

    def test_non_file_tool_is_registered_and_traced(self):
        response = handle_hook(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "web-agent",
                "cwd": str(self.root),
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://example.com"},
                "tool_response": {"status": 200},
            },
            ledger=self.ledger,
        )

        self.assertIsNotNone(response)
        self.assertIn("WebFetch", json.dumps(response))
        rows = self.ledger.conn.execute(
            "SELECT event_type, tool_name FROM events WHERE session_id=? ORDER BY created_at DESC",
            ("web-agent",),
        ).fetchall()
        self.assertEqual(rows[0]["event_type"], "tool")
        self.assertEqual(rows[0]["tool_name"], "WebFetch")
        registered = self.ledger.tool_registration("WebFetch")
        self.assertEqual(registered["category"], "network.fetch")


class AidCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "ledger.sqlite"
        self.file = self.root / "bash.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def run_aid(self, *args, env=None):
        merged_env = os.environ.copy()
        merged_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        merged_env["AID_GITNEXUS"] = "0"
        merged_env.pop("AID_STRICT_MISSING_READ", None)
        if env:
            merged_env.update(env)
        return subprocess.run(
            ["python3", "-m", "aid.cli", "--ledger", str(self.ledger), *args],
            cwd=str(self.root),
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_aid_run_records_bash_write_in_same_timeline(self):
        proc = self.run_aid(
            "run",
            "--session-id",
            "bash-session",
            "--actor",
            "shell-user",
            "--goal",
            "write from bash",
            "--force",
            "--",
            "printf 'hello\\n' > bash.txt",
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        recent = self.run_aid("recent", str(self.file), "--json")
        data = json.loads(recent.stdout)
        self.assertTrue(any(row["event_type"] == "write" for row in data))
        self.assertTrue(any(row["actor_id"] == "shell-user" for row in data))

    def test_gitnexus_can_be_disabled_for_awareness(self):
        self.file.write_text("x\n", encoding="utf-8")
        proc = self.run_aid("awareness", str(self.file), "--json")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIsNone(data["behavior_context"]["gitnexus"])

    def test_cli_blocks_missing_read_by_default_and_can_relax(self):
        self.file.write_text("existing\n", encoding="utf-8")

        blocked = self.run_aid("check-write", str(self.file), "--json")
        relaxed = self.run_aid("check-write", str(self.file), "--allow-missing-read", "--json")

        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(json.loads(blocked.stdout)["decision"], "block")
        self.assertEqual(relaxed.returncode, 0)
        self.assertEqual(json.loads(relaxed.stdout)["decision"], "warn")

    def test_cli_registers_custom_tool(self):
        registered = self.run_aid(
            "tool",
            "register",
            "image_gen.imagegen",
            "--category",
            "asset.generate",
            "--impact",
            "high",
            "--description",
            "Generate project images.",
            "--resource-hint",
            "writes generated image assets",
            "--side-effect",
            "may create files under assets/",
        )
        listed = self.run_aid("tool", "list", "--json")
        matcher = self.run_aid("tool", "matcher")
        explained = self.run_aid("tool", "explain", "image_gen.imagegen", "--json")

        self.assertEqual(registered.returncode, 0, registered.stderr)
        tools = json.loads(listed.stdout)
        image_tool = next(row for row in tools if row["tool_name"] == "image_gen.imagegen")
        self.assertEqual(image_tool["category"], "asset.generate")
        self.assertEqual(image_tool["impact"], "high")
        self.assertIn("image_gen\\.imagegen", matcher.stdout)
        metadata = json.loads(explained.stdout)["metadata"]
        self.assertEqual(metadata["description"], "Generate project images.")
        self.assertEqual(metadata["resource_hints"], ["writes generated image assets"])


if __name__ == "__main__":
    unittest.main()
