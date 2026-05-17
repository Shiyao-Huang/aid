#!/usr/bin/env bash
set -euo pipefail

# AID — Agent Identity Daemon
# One-line install:
#   curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aid/main/install.sh | bash

REPO="${AID_REPO:-https://github.com/Shiyao-Huang/aid.git}"
REF="${AID_REF:-main}"
AID_HOME="${AID_HOME:-$HOME/.aid}"
INSTALL_DIR="${AID_INSTALL_DIR:-$AID_HOME/aid}"
BIN_DIR="$AID_HOME/bin"
BIN_PATH="$BIN_DIR/aid"
LEDGER_PATH="${AID_LEDGER:-$AID_HOME/ledger.sqlite}"
TARGET="all"
SCOPE="user"
DRY_RUN=0
UNINSTALL=0
SKIP_CLONE=0
WITH_GITNEXUS=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --scope)
      SCOPE="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --uninstall)
      UNINSTALL=1
      shift
      ;;
    --local)
      SKIP_CLONE=1
      shift
      ;;
    --with-gitnexus)
      WITH_GITNEXUS=1
      shift
      ;;
    --without-gitnexus)
      WITH_GITNEXUS=0
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

case "$TARGET" in
  all|codex|claude) ;;
  *) echo "--target must be one of: all, codex, claude" >&2; exit 2 ;;
esac

case "$SCOPE" in
  user|project|plugin) ;;
  *) echo "--scope must be one of: user, project, plugin" >&2; exit 2 ;;
esac

say() { printf '%s\n' "$*"; }
run() {
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] $*"
  else
    "$@"
  fi
}

detect_script_root() {
  local src="${BASH_SOURCE[0]}"
  local dir
  dir="$(cd "$(dirname "$src")" 2>/dev/null && pwd || true)"
  if [ -n "$dir" ] && [ -d "$dir/aid" ] && [ -f "$dir/.codex-plugin/plugin.json" ]; then
    printf '%s\n' "$dir"
    return
  fi
  printf '%s\n' ""
}

ensure_repo() {
  local local_root
  local_root="$(detect_script_root)"
  if [ "$SKIP_CLONE" = "1" ] && [ -n "$local_root" ]; then
    INSTALL_DIR="$local_root"
    return
  fi
  if [ -n "$local_root" ] && [ "$local_root" != "$INSTALL_DIR" ]; then
    INSTALL_DIR="$local_root"
    return
  fi

  say "Installing AID from $REPO ..."
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] clone/update $REPO#$REF -> $INSTALL_DIR"
    return
  fi

  command -v git >/dev/null 2>&1 || {
    echo "git is required for remote install" >&2
    exit 1
  }

  if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$REF"
    git -C "$INSTALL_DIR" checkout --quiet FETCH_HEAD
  else
    rm -rf "$INSTALL_DIR"
    git clone --depth 1 --branch "$REF" "$REPO" "$INSTALL_DIR"
  fi
}

ensure_gitnexus() {
  if [ "$WITH_GITNEXUS" != "1" ]; then
    say "Skipping GitNexus dependency (--without-gitnexus)."
    return
  fi
  if command -v gitnexus >/dev/null 2>&1; then
    say "GitNexus already installed: $(command -v gitnexus)"
    return
  fi
  say "Installing GitNexus dependency..."
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] npm install -g gitnexus"
    return
  fi
  command -v npm >/dev/null 2>&1 || {
    echo "npm is required to install GitNexus. Re-run with --without-gitnexus to skip." >&2
    exit 1
  }
  npm install -g gitnexus
}

write_cli_shims() {
  say "Installing AID CLI shims..."
  run mkdir -p "$BIN_DIR"
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] write $BIN_PATH"
    return
  fi

  python3 - "$BIN_PATH" "$INSTALL_DIR" "$LEDGER_PATH" <<'PY'
from pathlib import Path
import os
import sys

aid, root, ledger = map(Path, sys.argv[1:])
content = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    f"export AID_LEDGER=\"${{AID_LEDGER:-{ledger}}}\"\n"
    f"export PYTHONPATH={str(root)!r}:\"${{PYTHONPATH:-}}\"\n"
    "exec python3 -m aid.cli \"$@\"\n"
)
aid.write_text(content, encoding="utf-8")
os.chmod(aid, 0o755)
PY
}

configure_direct_hooks() {
  local mode="$1"
  local scope="$2"
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] configure $mode hooks in $scope scope"
    return
  fi

  python3 - "$mode" "$scope" "$INSTALL_DIR" "$LEDGER_PATH" "$WITH_GITNEXUS" <<'PY'
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

mode, scope, root, ledger, with_gitnexus = sys.argv[1], sys.argv[2], Path(sys.argv[3]), sys.argv[4], sys.argv[5]
hook = root / "hooks" / "aid-hook"
cwd = Path.cwd()
home = Path.home()


def backup(path: Path) -> None:
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(path, path.with_suffix(path.suffix + f".aid.bak.{stamp}"))


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON; refusing to edit: {exc}")


def remove_aid_hooks(hooks: dict) -> None:
    for event in list(hooks.keys()):
        groups = []
        for group in hooks.get(event) or []:
            kept = [
                h for h in group.get("hooks", [])
                if "aid-hook" not in str(h.get("command", ""))
            ]
            if kept:
                new_group = dict(group)
                new_group["hooks"] = kept
                groups.append(new_group)
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)


def add_group(hooks: dict, event: str, matcher: str | None, command_event: str, harness: str, status: str) -> None:
    command = (
        f'AID_LEDGER="{ledger}" AID_HARNESS={harness} '
        f'AID_STRICT_MISSING_READ=1 AID_GITNEXUS={with_gitnexus} '
        f'"{hook}" {command_event}'
    )
    group = {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 10,
                "statusMessage": status,
            }
        ]
    }
    if matcher:
        group["matcher"] = matcher
    hooks.setdefault(event, []).append(group)


def target_path(kind: str) -> Path:
    if kind == "codex":
        return (cwd / ".codex" / "hooks.json") if scope == "project" else (home / ".codex" / "hooks.json")
    return (cwd / ".claude" / "settings.json") if scope == "project" else (home / ".claude" / "settings.json")


def install_codex() -> None:
    path = target_path("codex")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_json(path)
    hooks = data.setdefault("hooks", {})
    remove_aid_hooks(hooks)
    add_group(hooks, "SessionStart", "startup|resume", "session-start", "codex", "Registering AID session")
    add_group(hooks, "UserPromptSubmit", None, "user-prompt-submit", "codex", "Recording AID goal")
    add_group(hooks, "PreToolUse", "Bash|apply_patch|Write|Edit|MultiEdit", "pre-tool-use", "codex", "Checking AID operation chain")
    add_group(hooks, "PostToolUse", "Bash|apply_patch|Read|Write|Edit|MultiEdit", "post-tool-use", "codex", "Recording AID trace")
    backup(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Configured Codex hooks: {path}")


def install_claude() -> None:
    path = target_path("claude")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_json(path)
    hooks = data.setdefault("hooks", {})
    remove_aid_hooks(hooks)
    add_group(hooks, "SessionStart", None, "session-start", "claude", "Registering AID session")
    add_group(hooks, "UserPromptSubmit", None, "user-prompt-submit", "claude", "Recording AID goal")
    add_group(hooks, "PreToolUse", "Write|Edit|MultiEdit|Bash", "pre-tool-use", "claude", "Checking AID operation chain")
    add_group(hooks, "PostToolUse", "Read|Write|Edit|MultiEdit|Bash", "post-tool-use", "claude", "Recording AID trace")
    backup(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Configured Claude Code hooks: {path}")


if mode in {"all", "codex"}:
    install_codex()
if mode in {"all", "claude"}:
    install_claude()
PY
}

configure_codex_plugin_marketplace() {
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] configure Codex personal marketplace for AID plugin"
    return
  fi

  python3 - "$INSTALL_DIR" <<'PY'
import json
from pathlib import Path
import sys

install_dir = Path(sys.argv[1])
market = Path.home() / ".agents" / "plugins" / "marketplace.json"
market.parent.mkdir(parents=True, exist_ok=True)
if market.exists():
    data = json.loads(market.read_text(encoding="utf-8"))
else:
    data = {"name": "personal", "interface": {"displayName": "Personal Plugins"}, "plugins": []}

plugins = data.setdefault("plugins", [])
plugins[:] = [p for p in plugins if p.get("name") != "aid"]
plugins.append({
    "name": "aid",
    "source": {
        "source": "local",
        "path": str(install_dir)
    },
    "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
    },
    "category": "Coding"
})
market.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Configured Codex marketplace: {market}")
PY
}

uninstall_direct_hooks() {
  local mode="$1"
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] remove $mode hooks"
    return
  fi

  python3 - "$mode" <<'PY'
import json
import sys
from pathlib import Path

mode = sys.argv[1]
paths = []
home = Path.home()
cwd = Path.cwd()
if mode in {"all", "codex"}:
    paths.extend([home / ".codex" / "hooks.json", cwd / ".codex" / "hooks.json"])
if mode in {"all", "claude"}:
    paths.extend([home / ".claude" / "settings.json", cwd / ".claude" / "settings.json"])

for path in paths:
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})
    for event in list(hooks.keys()):
        groups = []
        for group in hooks.get(event) or []:
            kept = [
                h for h in group.get("hooks", [])
                if "aid-hook" not in str(h.get("command", ""))
            ]
            if kept:
                new_group = dict(group)
                new_group["hooks"] = kept
                groups.append(new_group)
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Removed AID hooks from {path}")
PY
}

if [ "$UNINSTALL" = "1" ]; then
  say "Uninstalling AID hooks..."
  uninstall_direct_hooks "$TARGET"
  say "Removing AID CLI shims..."
  run rm -f "$BIN_PATH"
  say "Ledger kept at: $LEDGER_PATH"
  exit 0
fi

ensure_repo
ensure_gitnexus
write_cli_shims

if [ "$SCOPE" = "plugin" ]; then
  configure_codex_plugin_marketplace
  say "Codex plugin marketplace configured. Enable plugin_hooks in Codex if you want bundled hooks:"
  say "  [features]"
  say "  plugin_hooks = true"
  say "Claude Code plugin manifest is available at: $INSTALL_DIR/.claude-plugin/plugin.json"
else
  configure_direct_hooks "$TARGET" "$SCOPE"
fi

say ""
say "AID installed."
say "Name: AID (Agent Identity Daemon / Agent ID)"
say "CLI:"
say "  $BIN_PATH doctor"
say "  $BIN_PATH recent <file>"
say "Shared mixed-agent ledger:"
say "  $LEDGER_PATH"
say ""
say "One-line installer:"
say "  curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aid/main/install.sh | bash"
say ""
say "Notes:"
say "  Codex: run /hooks if it asks you to review/trust hooks."
say "  Claude Code: restart or let settings reload."
