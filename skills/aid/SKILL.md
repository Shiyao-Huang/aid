---
name: aid
description: Use AID when working in a mixed-agent workspace and you need to know who touched a file, why they touched it, what operation chain exists, what conditions were checked, or how past operations were evaluated.
---

# AID

AID means Agent Identity Daemon / Agent ID.

Use AID before editing shared or recently changed files. AID records and queries:

- agent/session identity
- current goal
- explicit thought summaries
- operation preconditions
- read/write events
- outcomes and semantic evaluations
- adaptation hints for future agents

Useful commands:

```bash
aid awareness <file>
aid recent <file>
aid check-write <file>
aid chain <event-id>
aid evaluate <event-id> --verdict good|bad|mixed|uncertain --reason "..."
aid think observation "..."
aid condition read-before-write "Existing file must be read before writing" --satisfied
```

When AID reports another agent's trace, adapt instead of overwriting blindly: read the latest state, inspect the chain, coordinate if needed, then continue.
