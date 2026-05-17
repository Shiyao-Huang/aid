# Agent 工具自指实现探索

## 一句话压缩

先做一个跨 Codex / Claude 的本地痕迹账本，让 hooks 在读写前后把“谁、为什么、什么时候、对什么资源做了什么”暴露给 Agent，而不是替 Agent 规定怎么协作。

## 三句话压缩

并行 Agent 协作的核心不是更大的聊天室，而是共享环境里可观察、可查询、可追责的操作痕迹。  
实现上先用 hooks 做被动感知：读后记录、写前检查、写后入账、必要时把最近协作者和冲突风险注入上下文。  
再用 MCP / wrapper 工具做主动能力：让 Agent 主动查询文件、session、目标、最近修改者和资源关系，最终逐步替代原生工具调用。

## 五句话压缩

我们的系统叫“工具自指层”：它不生产代码，而是让工具知道自己正在被谁使用。  
最小闭环是 `SessionStart -> UserPromptSubmit -> Read/PostRead -> PreWrite -> PostWrite -> Query`。  
每个 session 有 ID，每个目标资源有最近读写历史，每次写入都连接到“人 / Agent / session / 当前目标 / 文件 diff”。  
如果没有其他人动同一个资源，工具保持安静；如果有别人最近看过、改过或正在改，它就浮出最短必要信息。  
这不是协作协议本身，而是一个 harness：文明、规则、配合方式会在可观察世界里自我涌现。

## 相关蓝图

这份文档聚焦 AID 的身份链、工具追溯链和 hook/MCP 实现。  
更高一层的系统融合见 [AID + GitNexus + Mermaid Architect 融合蓝图](aid-gitnexus-mermaid-conscious-architecture.md)：AID 负责“谁/为什么/最近痕迹”，GitNexus 负责“代码图谱/影响链”，Mermaid Architect 负责“任务 DAG/ready/claim”，三者合成 Agent 的运行时 awareness。

## 必须记住的故事

原始隐喻是“多人共用柜子”：

- 我打开柜子，先看到很多东西，然后找到我要的东西。
- 我看到自己之前放过什么，也看到别人留下了什么。
- Jane 放了蛋白粉，AC 放了扑克牌，因为物品有标签，所以我知道归属。
- 柜子里突然出现了危险物，上面写着 K，于是团队能追责、批评、制定规范。
- 抽象出来就是：所有操作都发生在同一个时空里，带标签，能被观测。

这个故事比任何 API 设计都重要。它说明我们要做的不是“日志”，而是一个共享世界的可见性系统。

## 公开项目和官方能力观察

### Claude Code

Claude Code 的 hooks 已经非常接近我们需要的入口。官方文档说明 hooks 会在 Claude Code 生命周期的特定点自动执行，并且 hook 输入里包含 `session_id`、`transcript_path`、`cwd`、`tool_name`、`tool_input` 等字段；`PreToolUse` 可以阻止动作，`PostToolUse` 可以在工具执行后给 Claude 反馈。[Claude Code hooks reference](https://code.claude.com/docs/en/hooks)

Claude Code 还支持把 hook 输出作为 `additionalContext` 注入给模型。也就是说，我们可以在写文件之前告诉 Agent：“这个文件刚被另一个 session 改过，对方目标是什么，建议先读 diff。”[Claude Code hooks reference](https://code.claude.com/docs/en/hooks)

Claude Code 的插件系统也适合分发。插件可以包含 skills、agents、hooks、MCP servers，并且官方建议先在 `.claude/` 里快速实验，成熟后再转成 plugin。[Claude Code plugins](https://code.claude.com/docs/en/plugins)

### Codex

Codex 也有 hooks。官方文档说明 `PreToolUse` 可以拦截 Bash、通过 `apply_patch` 做的文件编辑、以及 MCP tool calls；但文档也明确提醒它更像 guardrail，不是完整 enforcement boundary，因为同一行为可能通过其他工具路径完成。[Codex hooks](https://developers.openai.com/codex/hooks)

Codex 的 hooks 可以通过 JSON 输出提供 `additionalContext`，让模型看到额外开发上下文；也可以 block 某次工具调用。[Codex hooks](https://developers.openai.com/codex/hooks)

Codex 插件可以打包 skills、MCP servers、apps 和 hooks。官方 build plugins 文档写明 `.codex-plugin/plugin.json` 是入口，`skills`、`mcpServers`、`apps`、`hooks` 都可以作为 manifest 字段；但当前版本里 plugin hooks 默认关闭，需要 `[features].plugin_hooks = true`。[Codex build plugins](https://developers.openai.com/codex/plugins/build)

### Superpowers

Superpowers 是跨 harness 分发方式的好参考。它同一个仓库里同时有 `.claude-plugin`、`.codex-plugin`、`.cursor-plugin`、`.opencode`、`skills/`、`hooks/` 等结构，并且针对 Claude Code、Codex CLI、Codex App、Gemini CLI、OpenCode、Cursor、GitHub Copilot CLI 给出不同安装路径。[obra/superpowers](https://github.com/obra/superpowers)

它的关键启发不是某个具体 hook，而是“同一套方法论，多套 harness adapter”。我们也应该这样做：核心 ledger 一份，Codex / Claude / 其他 Agent 只写薄适配层。

### claude-for-codex

`claude-for-codex` 的一行安装体验值得参考：`curl -sfL .../install.sh | bash`。它的脚本会自动定位 `CODEX_HOME`，clone 或更新仓库，检查 Node/npm/git，安装依赖，复制 skills，修改 `~/.codex/config.toml` 注册 MCP server，并提供 `--uninstall`。[Shiyao-Huang/claude-for-codex](https://github.com/Shiyao-Huang/claude-for-codex)

我们的安装器可以借这个形状，但要更谨慎：默认支持 `--dry-run`、备份配置、显示将写入哪些文件、支持单独安装 Claude / Codex adapter。

## 核心判断

### Agent 必须带身份

核心不是“记录文件变化”，而是“带身份的 Agent 在共享世界里行动”。  
每个操作都必须能追到：

```text
actor -> session -> goal -> claim/node -> tool call -> resource -> diff/result -> later evaluation
```

这样当前 Agent 再次操作时，看到的不是一条死日志，而是一条有作者、有目的、有结果、有评价的行为链。它会因此自适应：避开别人的 claim，先读最新状态，复用被好评的路径，警惕被差评的操作模式。

### 不要一开始替代所有工具

“完全替代 Claude 和 Codex 的整个工具集”是最终形态，不是第一步。第一步应该做一个旁路自指层：

```text
原生工具调用仍然存在
hooks 在旁边观察
ledger 记录痕迹
hook 在关键时刻返回最短上下文
Agent 自己决定如何协作
```

这样阻力最小，也最接近人类社会的 harness：先让行为可见，再让规范涌现。

### 写前必读是最小规则

最小规则不是“你必须怎么协作”，而是：

> 如果你要写一个文件，而这个文件在你上次读取后被别人改过，工具应该阻止或提醒你先读取最新状态。

它对应柜子故事里的动作：伸手拿东西前，先看一眼柜子现在是什么状态。

### 目标链比作者链更重要

“谁改了文件”不够。Agent 真正需要知道的是：

```text
谁 -> 哪个 session -> 当前目标是什么 -> 为什么碰这个文件 -> 改了什么 -> 结果如何 -> 后来被怎么评价 -> 这和我的目标是否冲突
```

所以 ledger 不能只存 file history，还要存 session intent。

### 评价链不是评分系统

这里的评价不是给操作打一个数字分。数字会丢失因果。  
我们需要的是语义评价：

```text
good: 提前做了 impact，避开了并发 claim，后续验证通过。
bad: 没读最新文件，覆盖了别人刚改的 schema，导致测试失败。
uncertain: 操作事实已记录，但结果还没有被验证。
```

评价链让后来的 Agent 能看到“这个操作为什么后来被认为好/坏”，从而改变当前行为。

## 主动与被动两条路径

### 被动路径：hooks

被动路径的特点是：Agent 不需要主动记得调用我们的工具。系统在关键生命周期自动介入。

Hook 点：

- `SessionStart`：注册 session，记录 harness、cwd、时间、父子关系。
- `UserPromptSubmit`：记录用户当前目标，生成短 goal digest。
- `PreToolUse`：在写入、patch、危险 Bash、MCP 写操作前检查冲突。
- `PostToolUse`：记录读写结果、diff 摘要、资源状态。
- `PostToolBatch`：把一组工具调用压缩成一次上下文注入，减少噪音。
- `Stop` / `SessionEnd`：收尾，记录任务结果、未完成事项、可评价操作。
- `PostVerification` / 自定义验证入口：把测试、review、CI、用户反馈写成 outcome / evaluation。
- `FileChanged` / filesystem watcher：补足非 Agent 或外部编辑器造成的变化。

被动路径适合做：

- 写前必读。
- 最近修改者提醒。
- 最近阅读者提醒。
- 危险操作提示。
- session 目标记录。
- diff 入账。
- 冲突风险注入。

### 主动路径：MCP / wrapper tools

主动路径的特点是：Agent 可以明确查询世界。

可以暴露这些工具：

- `AID.session.current`：我是谁，我的 session ID 是什么。
- `AID.session.goal`：设置或更新当前目标。
- `AID.resource.recent(path)`：这个文件最近谁看过、谁改过、为什么。
- `AID.resource.claim(path, intent)`：声明我准备处理这个资源。
- `AID.resource.diff(path, since)`：查看某个 session 对这个文件做了什么。
- `AID.event.evaluate(event_id, verdict, reason)`：给某个操作追加语义评价。
- `AID.event.outcome(event_id)`：查询某个操作后来产生了什么结果。
- `AID.conflicts.mine()`：列出我的潜在冲突。
- `AID.timeline(path|session|cwd)`：查询时间线。

主动路径适合做：

- Agent 自己判断协作策略。
- 多 Agent 之间形成礼貌和分工。
- 人类查询“刚才谁动了这个东西”。
- 人类或 Agent 给某个操作追加好评、差评、原因和后果。
- 后续做可视化面板。

## 最小闭环

### 1. Session 注册

每个 harness 启动时生成或读取 session ID：

```text
session_id = harness-native-session-id || AID-generated-id
actor_id = user-configured-name || machine-user || anonymous-agent
harness = codex | claude | cursor | opencode | unknown
cwd = current working directory
started_at = now
```

Claude Code hooks 输入本身有 `session_id`，Codex hooks 也需要从 hook 输入、环境或 fallback 生成稳定 ID。不要把 session ID 只藏在日志里，要让 Agent 能查询。

### 2. 目标记录

在 `UserPromptSubmit` 或第一条用户任务里记录目标：

```text
session_id
raw_prompt_hash
goal_summary
goal_source = user_prompt | manual | inferred
created_at
```

隐私默认值：不存完整 prompt，只存 hash 和本地短摘要。可以加配置允许本机明文存储。

### 3. 读后记录

当 Agent 读文件时记录：

```text
event = read
resource = file path
content_hash = hash(file content)
mtime = filesystem mtime
session_id
goal_id
tool = Read | Bash(cat/sed/rg) | MCP | other
observed_at
```

关键点：写前检查不是看“你是否读过这个文件”，而是看“你读到的是不是当前状态”。

### 4. 写前检查

伪代码：

```text
pre_write(session, path):
  current = stat_and_hash(path)
  my_last_read = ledger.last_read(session, path)
  recent_other_writes = ledger.recent_writes(path, exclude=session)

  if my_last_read is missing:
    return warn_or_block("你还没有读过这个文件")

  if my_last_read.content_hash != current.content_hash:
    return block("文件在你读后变化了，先读取最新状态")

  if recent_other_writes within window:
    return additional_context(compact_recent_activity)

  return allow
```

策略可以分级：

- `observe`：只记录，不提醒。
- `warn`：注入上下文，但不阻止。
- `block-stale-write`：读后文件变了就阻止。
- `strict`：没有 claim 或没有最新 read 就阻止。

默认建议：`block-stale-write`。

### 5. 写后入账

写后记录：

```text
event = write | patch | delete | move
resource = path
session_id
goal_id
before_hash
after_hash
diff_summary
line_ranges
tool
success
created_at
```

如果在 git 仓库里，可以额外记录：

```text
git_repo_root
git_head_before
git_head_after
git_diff_name_only
```

### 6. 上下文返回

hook 返回给 Agent 的信息要非常短。推荐格式：

```text
AID context for /path/to/file:
- Last write: Jane/session-123, 4 minutes ago, goal: refactor auth retry.
- Prior similar outcome: bad, stale schema read caused overwritten field.
- Your last read: before that write.
- Action: read the latest file or diff before editing.
```

中文格式：

```text
AID 观察：
- 这个文件 4 分钟前被 Jane/session-123 改过，目标是“重构 auth retry”。
- 相似历史操作曾收到差评：未读最新 schema，覆盖了迁移字段。
- 你上次读取发生在这次修改之前。
- 建议：先读取最新文件或查看对方 diff，再决定是否继续。
```

## 数据模型草案

### `actors`

```sql
actor_id TEXT PRIMARY KEY,
display_name TEXT,
kind TEXT,              -- human | agent | unknown
home_harness TEXT,
created_at TEXT
```

### `sessions`

```sql
session_id TEXT PRIMARY KEY,
actor_id TEXT,
harness TEXT,           -- codex | claude | cursor | opencode
cwd TEXT,
transcript_path TEXT,
parent_session_id TEXT,
started_at TEXT,
ended_at TEXT,
metadata_json TEXT
```

### `goals`

```sql
goal_id TEXT PRIMARY KEY,
session_id TEXT,
summary TEXT,
raw_prompt_hash TEXT,
source TEXT,            -- user_prompt | manual | inferred
created_at TEXT,
updated_at TEXT
```

### `resources`

```sql
resource_id TEXT PRIMARY KEY,
uri TEXT,               -- file://...
repo_root TEXT,
kind TEXT,              -- file | directory | mcp-resource | url
created_at TEXT
```

### `events`

```sql
event_id TEXT PRIMARY KEY,
session_id TEXT,
goal_id TEXT,
resource_id TEXT,
event_type TEXT,        -- read | write | patch | delete | move | run | claim
tool_name TEXT,
status TEXT,            -- allow | warn | block | success | failure
before_hash TEXT,
after_hash TEXT,
diff_summary TEXT,
line_ranges_json TEXT,
created_at TEXT,
metadata_json TEXT
```

### `evaluations`

评价不是数字评分，而是对操作结果的语义反馈。它可以来自人类、另一个 Agent、测试结果、GitNexus impact/detect_changes、CI、或后续复盘。

```sql
evaluation_id TEXT PRIMARY KEY,
event_id TEXT,
reviewer_session_id TEXT,
reviewer_actor_id TEXT,
verdict TEXT,           -- good | bad | mixed | uncertain
reason TEXT,
evidence_uri TEXT,      -- test log, CI URL, diff, issue, local file
created_at TEXT,
metadata_json TEXT
```

### `outcomes`

`events` 记录“做了什么”，`evaluations` 记录“别人怎么看”，`outcomes` 记录“后来发生了什么”。

```sql
outcome_id TEXT PRIMARY KEY,
event_id TEXT,
kind TEXT,              -- test-pass | test-fail | conflict | revert | merge | user-accepted
summary TEXT,
evidence_uri TEXT,
created_at TEXT,
metadata_json TEXT
```

### `adaptation_hints`

把评价链压缩成未来 Agent 能直接使用的行为提示。

```sql
hint_id TEXT PRIMARY KEY,
source_event_id TEXT,
pattern TEXT,           -- stale-write | skipped-impact | respected-claim
recommendation TEXT,
confidence TEXT,        -- low | medium | high
created_at TEXT,
metadata_json TEXT
```

### `claims`

```sql
claim_id TEXT PRIMARY KEY,
session_id TEXT,
resource_id TEXT,
intent TEXT,
status TEXT,            -- active | released | expired
created_at TEXT,
expires_at TEXT
```

### `hazards`

```sql
hazard_id TEXT PRIMARY KEY,
session_id TEXT,
resource_id TEXT,
hazard_type TEXT,       -- stale-read | concurrent-write | dangerous-command
severity TEXT,          -- info | warn | block
message TEXT,
created_at TEXT,
resolved_at TEXT
```

## Hook adapter 设计

### Claude adapter

优先做 Claude，因为 Claude Code 的工具事件覆盖更完整。

需要的文件：

```text
plugins/aid-claude/
  .claude-plugin/plugin.json
  hooks/hooks.json
  hooks/aid-hook
  skills/aid-status/SKILL.md
```

`hooks/hooks.json`：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/aid-hook session-start"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/aid-hook user-prompt-submit"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/aid-hook pre-tool-use"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Read|Write|Edit|MultiEdit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/aid-hook post-tool-use"
          }
        ]
      }
    ]
  }
}
```

### Codex adapter

Codex 的限制是：文件写入主要走 `apply_patch`，`PreToolUse` 不是完整 enforcement boundary。第一版不追求完全封锁，只做高价值提醒和 stale-write block。

需要的文件：

```text
plugins/aid-codex/
  .codex-plugin/plugin.json
  hooks/hooks.json
  skills/aid-status/SKILL.md
  mcp/aid-mcp-server
```

Codex plugin hooks 当前需要配置：

```toml
[features]
plugin_hooks = true
```

如果用户不想打开 plugin hooks，则安装器可以写入用户级或项目级 hooks 配置。这个动作必须备份原文件并支持卸载。

### 通用 hook 命令

所有 adapter 最终调用同一个二进制：

```text
aid hook session-start
aid hook user-prompt-submit
aid hook pre-tool-use
aid hook post-tool-use
aid query recent <path>
aid session current
aid claim <path> --intent "..."
```

hook 输入通过 stdin 接收 JSON，输出严格遵守当前 harness 的 schema。

## 安装器设计

目标体验：

```bash
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aid/main/install.sh | bash
```

推荐选项：

```bash
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aid/main/install.sh | bash -s -- --target all
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aid/main/install.sh | bash -s -- --target claude
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aid/main/install.sh | bash -s -- --target codex
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aid/main/install.sh | bash -s -- --dry-run
curl -sfL https://raw.githubusercontent.com/Shiyao-Huang/aid/main/install.sh | bash -s -- --uninstall
```

安装步骤：

1. 检测系统：macOS/Linux、shell、sqlite、node/python/rust runtime。
2. 定位 homes：`CODEX_HOME`、`~/.codex`、`~/.claude`。
3. 安装核心：`~/.aid/bin/aid`、`~/.aid/lib/`、`~/.aid/ledger.sqlite`。
4. 安装 Claude adapter：plugin 或 standalone `.claude/settings.json` hook。
5. 安装 Codex adapter：plugin 或 `.codex/hooks.json` / `.codex/config.toml` hook。
6. 注册 MCP server：Claude 和 Codex 都能查询同一份 ledger。
7. 备份所有被修改配置：`*.aid.bak.<timestamp>`。
8. 输出验证命令：`aid doctor`。

卸载步骤：

- 删除 hook entries。
- 删除 plugin entries。
- 删除 MCP server entries。
- 可选保留 ledger。
- 默认不删历史账本，除非用户传 `--purge-ledger`。

## 最小原型路线

### P0：只做文档和手动 CLI

命令：

```bash
aid session start
aid goal set "..."
aid read path
aid write-check path
aid write-record path
aid recent path
```

目标：证明 ledger 模型成立。

### P1：Claude hooks

实现：

- `SessionStart` 注册 session。
- `UserPromptSubmit` 记录 goal。
- `PostToolUse(Read)` 记录读。
- `PreToolUse(Write/Edit/MultiEdit)` 做写前检查。
- `PostToolUse(Write/Edit/MultiEdit)` 记录 diff。

目标：完成真正的写前必读。

### P2：Codex hooks

实现：

- `PreToolUse(apply_patch)` 检查 patch 目标文件。
- `PostToolUse(apply_patch)` 记录 patch。
- `PreToolUse(Bash)` 识别高风险写操作，比如 `cat > file`、`sed -i`、`python -c` 写文件、`rm`。
- `PostToolUse(Bash)` 记录可能影响的路径。

目标：在 Codex 上达到 70% 可见性，而不是假装 100% 可控。

### P3：MCP 查询层

实现：

- `recent_activity(path)`
- `current_session()`
- `set_goal(summary)`
- `claim_resource(path, intent)`
- `list_conflicts()`

目标：让 Agent 主动看世界。

### P4：可视化和团队规范

实现：

- `aid timeline`
- `aid dashboard`
- HTML / TUI 时间线。
- “危险物”规则：对 delete、secret、prod config、migration、lockfile 等高风险资源提高等级。

目标：让人类和 Agent 都能看见车间排班表。

## 核心算法：写前必读

### 输入

```json
{
  "session_id": "abc",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/repo/src/auth.ts"
  },
  "cwd": "/repo"
}
```

### 决策

```text
1. 解析目标路径。
2. 查询当前文件 hash。
3. 查询本 session 对该文件最后一次 read 的 hash。
4. 查询其他 session 对该文件最后一次 write。
5. 如果没有 read：warn 或 block。
6. 如果 read hash != current hash：block stale write。
7. 如果有人最近写过但 hash 一致：inject context。
8. 如果有人 active claim：inject context。
9. 允许写入。
```

### 输出

Claude / Codex 的 hook 输出需要分 adapter：

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "AID: /repo/src/auth.ts was modified by session Jane-123 4 minutes ago for goal 'refactor auth retry'. Read latest state before editing."
  }
}
```

如果阻止：

```json
{
  "decision": "block",
  "reason": "AID blocked stale write: this file changed after your last read. Read it again or inspect recent activity before editing."
}
```

## 关键设计原则

### 1. 最短必要显现

没有冲突就安静，有冲突才说话。  
这保证单人使用时不会变重。

### 2. 账本是事实，不是命令

ledger 只描述发生了什么，不规定 Agent 必须怎么协作。  
协作方式应该由 Agent 在共享现实里进化出来。

### 3. 身份链要能查

每个 session ID 都必须能查到：

```text
session -> actor -> harness -> cwd -> current goal -> recent events
```

### 4. 目标摘要要可控

不要默认存用户完整 prompt。  
第一版可以只存：

- prompt hash。
- 用户显式设置的 goal。
- 本地生成的短摘要。

### 5. 不假装全知

Bash、外部编辑器、IDE、脚本都可能绕过 hook。  
所以必须有 filesystem watcher 和 periodic reconciliation：

```text
git status / file mtime / content hash -> ledger reconcile -> mark external-change
```

## 风险与问题

### 噪音

如果每次读写都返回长上下文，Agent 会被淹没。  
解决：只在冲突、stale read、危险文件、active claim 时注入。

### 隐私

目标链如果存完整 prompt，会变成敏感日志。  
解决：默认 hash + summary，明文存储需要显式开启。

### 误判

Bash 命令解析很难百分百准确。  
解决：先覆盖常见写路径，把未知行为标记为 `possible-write`。

### 并发

两个 Agent 同时通过写前检查，然后同时写。  
解决：对写前检查使用短租约 claim，默认 TTL 2-5 分钟。

### 跨工具差异

Claude 和 Codex hooks schema 不完全相同。  
解决：核心只产出中间决策对象，再由 adapter 转成各自 schema。

中间对象：

```json
{
  "decision": "allow | warn | block",
  "context": "...",
  "reason": "...",
  "events_to_record": []
}
```

## 开放问题

第一轮问题不会是好问题，所以先问粗问题：

- 写前必读应该默认 block，还是先 warn？
- session goal 是用户显式给，还是系统从 prompt 自动摘要？
- 读事件是否要记录文件内容 hash，还是只记录 mtime？
- 多久算“最近修改”：5 分钟、30 分钟、当前任务内、当前 git branch 内？
- claim 是硬锁，还是只是礼貌标签？

第二轮问题更接近本质：

- 如何让 Agent 感知他人目标，但不把上下文塞满？
- 如何区分“危险物”与“正常物品”？
- 如何让工具显示世界，而不是控制世界？
- 如何让跨 harness 的 AID 协议保持小而稳定？

第三轮问题才是实现问题：

- 先写 Node、Python、Rust 还是 Bash？
- SQLite ledger 放在 `~/.aid/ledger.sqlite`，还是项目 `.aid/ledger.sqlite`？
- 安装器默认写用户级配置，还是项目级配置？
- MCP server 和 hook command 是否共用一个进程？
- 如何写 `aid doctor` 来验证 Claude/Codex adapter 是否真的生效？

## 当前推荐方案

先做一个小而真实的版本：

```text
AID core: SQLite ledger + CLI
AID claude adapter: hooks/hooks.json + hook command
AID codex adapter: hooks + plugin/MCP registration
AID install: one-line installer + dry-run + uninstall
```

默认策略：

```text
read: record
write before read: warn
stale read before write: block
recent other write: inject short context
active claim: inject short context
dangerous file: raise warn/block threshold
```

最终目标不是“让 Agent 遵守规则”，而是：

> 让每个 Agent 一伸手碰柜子，就能看到柜子里谁来过、为什么来、留下了什么、哪里危险。

这就是工具拥有身份意识和自指能力的第一版。
