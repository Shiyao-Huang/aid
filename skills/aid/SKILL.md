---
name: aid
description: Use AID as the operating manual for mixed-agent awareness. It explains how to use AID, register new tools, inspect operation chains, and safely modify AID itself.
---

# AID Operator Manual

AID means Agent Identity Daemon / Agent ID.

Use this skill when you need to:

- know who touched a resource, why, and with which tool
- check a file before editing it
- inspect a full operation chain
- evaluate an operation after seeing its result
- register a new tool into the shared timeline
- modify AID itself without breaking the awareness model

## One-Sentence Rule

Before acting in a shared workspace, use AID to see self, others, tool traces, resource risk, and prior feedback.

## Three-Sentence Rule

AID is not only for reads and writes; it is a tool-trace bus. Reads, writes, shell, agent spawning, web fetches, MCP calls, planning tools, and custom tools can all register into the same local ledger. Only resource-changing tools trigger strict pre-write checks, but every important tool can leave identity, goal, and outcome traces.

## Daily Use

```bash
aid doctor
aid awareness <file>
aid recent <file>
aid check-write <file>
aid chain <event-id>
aid evaluate <event-id> --verdict good|bad|mixed|uncertain --reason "..."
aid outcome <event-id> --kind test-result --summary "..."
aid run --goal "manual shell action" -- "printf 'hello\n' > note.txt"
```

Default mode is maximum capability:

- `AID_STRICT_MISSING_READ=1`: existing files must be read by the current session before writing
- `AID_GITNEXUS=1`: GitNexus context is included when available
- Codex, Claude Code, and Bash share one ledger
- high-impact tools are hooked by default
- awareness output is budgeted by default: nearest, riskiest, highest-signal lines first

Relax only when there is a clear reason:

```bash
AID_STRICT_MISSING_READ=0 aid check-write <file>
AID_GITNEXUS=0 aid awareness <file>
aid check-write <file> --allow-missing-read
```

Expand context only when needed:

```bash
aid awareness <file> --lines 12
aid awareness <file> --verbose
AID_AWARENESS_LINES=12 AID_AWARENESS_CHARS=220 aid awareness <file>
aid recent <file> --limit 20
aid chain <event-id>
```

Context rule:

```text
nearest > risky > evaluated > high-impact > everything else
```

Keep default hook context short. Use `recent` and `chain` for deep inspection.

## Tool Registration

List registered tools:

```bash
aid tool list
aid tool list --json
```

Register a new tool:

```bash
aid tool register image_gen.imagegen --category asset.generate --impact high
aid tool register deploy --category release.deploy --impact critical
aid tool register browser.click --category browser.action --impact medium
```

Register it as a tool contract when possible:

```bash
aid tool register image_gen.imagegen \
  --category asset.generate \
  --impact high \
  --description "Generate or edit project image assets" \
  --resource-hint "may create files under assets/" \
  --side-effect "changes project-facing visual communication"
```

Inspect a tool contract:

```bash
aid tool explain image_gen.imagegen
aid tool explain image_gen.imagegen --json
```

Impact guide:

- `critical`: can write files, run shell, patch code, deploy, delete, mutate data, change credentials, or spawn irreversible side effects
- `high`: can spawn agents, call MCPs, generate assets, operate browsers, or alter plans that steer later work
- `medium`: can fetch/search/list/inspect context
- `low`: observational or formatting-only tools

Default high-impact matcher:

```bash
aid tool matcher
```

To change installed hook coverage:

```bash
AID_TOOL_MATCHER="$(aid tool matcher)" ./install.sh --local --scope project --target all
```

Use `AID_TOOL_MATCHER='.*'` only when you intentionally want to trace every tool event; it can be noisy.

## How To Interpret AID

When AID reports a recent writer:

1. Read the latest resource.
2. Inspect the writer's goal.
3. If the write was evaluated badly, adapt before editing.
4. If your last read is stale, do not overwrite.
5. Continue only after the chain makes sense.

When AID reports GitNexus importance:

1. Treat `high` as blast-radius risk.
2. Inspect call paths or run GitNexus directly.
3. Add tests around affected flows.
4. Record outcome and evaluation after validation.

## How To Modify AID Itself

Before editing AID:

```bash
aid awareness aid/core.py
aid awareness aid/cli.py
aid recent aid/core.py
aid tool list
```

Choose the smallest correct layer:

- `aid/core.py`: ledger schema, hook semantics, awareness, GitNexus integration, tool registry
- `aid/cli.py`: user commands and command-line UX
- `hooks/aid-hook`: harness environment bridge
- `install.sh`: one-line installer, hook matcher, GitNexus dependency, scopes
- `skills/aid/SKILL.md`: this operating manual
- `README.md` / `README.zh-CN.md`: public explanation
- `examples/wow_demo.py`: emotional comparison scenarios
- `tests/test_aid.py`: behavior locks

After changing AID:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 -m py_compile aid/*.py examples/wow_demo.py
PYTHONPATH=. python3 examples/wow_demo.py
./install.sh --dry-run --target all --scope user
```

If the change affects hooks, refresh local project hooks:

```bash
./install.sh --local --scope project --target all
```

## Design Boundary

AID should not become a giant policy prompt. It should expose enough self, peer, tool, resource, impact, and feedback context for agents to adapt.

The invariant:

```text
Every important operation has an actor, session, goal, tool, timestamp, optional resource, optional outcome, and optional evaluation.
```

Reads and writes are just the first visible case. The real model is: every tool can carry identity and leave traces.

The ideal tool contract says:

```text
tool name
category
impact
what resources it may read/write/touch
what side effects it may cause
how AID should trace it
how future agents should interpret it
```

## Borrowed From Selftools

AID hook metadata should include a compact canonical tool envelope:

```text
schema_version = aid.tool-envelope.v1
runtime
phase
tool.name/input/response/contract
session.id/actor/runtime/cwd
intent.value/source
timestamps.received_at
```

This keeps AID interoperable with file-backed systems such as selftools/AIDS that think in ToolEnvelope, timeline, trace, and rating records.
