---
name: delegate-codex
description: "Delegate a scoped implementation, investigation, analysis, or code review to Codex CLI and verify its result. Use when an agent needs Codex as a worker or second opinion, or the user asks to delegate to Codex."
---

# Delegate to Codex

Use `codex exec` for non-interactive delegation. The calling agent owns the task definition, execution monitoring, and acceptance of the result. Starting a worker is not task completion.

## Check the installed interface

Run `codex --version`, `codex --help`, and `codex exec --help` before the first delegation in a session. Read `codex exec resume --help` or `codex exec review --help` when using those modes. Treat local help as authoritative for flags; do not copy unsupported options from older examples.

Check authentication with `codex login status` if it is not already established. Use the existing configured account/provider. If authentication is missing, report the required login step instead of reading or copying credential files.

Current versions reject `--full-auto`, which older documentation still shows; use explicit `--sandbox` settings.

## Define a bounded assignment

Provide a self-contained prompt: the child session does not automatically inherit the calling agent's conversation.

- State the objective, relevant facts, absolute workspace path, and useful files or symbols.
- Select analysis or implementation explicitly. List editable paths and exclusions for implementation; require no edits for analysis.
- Include applicable project instructions, acceptance criteria, relevant validation commands, and any user-specified limits.
- Request evidence: file/line references for findings; changed files and actual check results for implementation. Distinguish observed facts, hypotheses, and unresolved questions.
- Preserve the user's authorization. Include restrictions on commits, publishing, external messages, or other side effects when those actions are outside the assignment.
- Tell the worker to perform the assignment itself, without recursively invoking this skill or spawning further workers unless that delegation was explicitly requested.

Inspect the working state first. In Git projects, record `git status --short` and relevant diffs, including staged changes and untracked files. Do not erase existing work to prepare a delegation.

For simultaneous writers, use distinct worktrees/checkouts or strictly disjoint ownership. A fresh worktree may lack uncommitted context; arrange the required inputs deliberately. The caller must also avoid editing the worker's owned files while it runs. Do not introduce parallel workers unless permitted by the current task and agent instructions.

## Choose the execution mode

| Assignment | Command family | Sandbox |
| --- | --- | --- |
| Investigation, explanation, plan, second opinion | `codex exec` | `read-only` |
| Authorized implementation or fix | `codex exec` | `workspace-write` |
| Review of a Git change set | `codex exec review` | `read-only` |
| Follow-up in a known session | `codex exec resume SESSION_ID` | Explicitly match the follow-up scope |

Use `codex -a never exec ...` for unattended runs so the child returns permission failures instead of waiting for approval. `never` does not grant broader access. If a required operation is denied, report the concrete blocker or use an already-authorized alternative; do not silently retry with bypass flags.

Keep the configured model and profile unless the user or project selects another. Apply `--model MODEL` or `--profile PROFILE` only when needed, and use the exact requested value. Do not invent model names or alter global configuration.

Use an absolute `-C` path. Add `--skip-git-repo-check` only for a deliberately selected non-Git workspace. Use `--add-dir` only for additional directories the assignment actually needs to modify. Do not default to `danger-full-access`, `--dangerously-bypass-approvals-and-sandbox`, `--ignore-rules`, or `--dangerously-bypass-hook-trust`.

## Run an analysis

The examples below use Bash. Replace the example workspace and assignment before executing. Store each run's artifacts in a unique directory outside the target project. Pass a prompt file through stdin to avoid shell expansion of prompt text.

```bash
delegate_workspace='/absolute/path/to/project'
delegate_run_dir=$(mktemp -d "${TMPDIR:-/tmp}/delegate-codex.XXXXXX")

cat > "$delegate_run_dir/prompt.md" <<'PROMPT'
Investigate why the request retry path can exceed its configured deadline.
Mode: analysis only. Do not modify files or perform external mutations.
Read applicable project instructions. Inspect the retry implementation and its
callers. Cite concrete file/line evidence, distinguish confirmed behavior from
hypotheses, and recommend a minimal fix and relevant validation.
Perform this assignment yourself; do not delegate it again.
Return findings, evidence, proposed next steps, and unresolved limitations.
PROMPT

delegate_exit=0
codex -a never exec -C "$delegate_workspace" \
  --sandbox read-only --json \
  --output-last-message "$delegate_run_dir/result.md" \
  - < "$delegate_run_dir/prompt.md" \
  > "$delegate_run_dir/events.jsonl" \
  2> "$delegate_run_dir/stderr.log" || delegate_exit=$?

printf '%s\n' "$delegate_exit" > "$delegate_run_dir/exit-code.txt"
printf 'Exit code: %s\nArtifacts: %s\n' "$delegate_exit" "$delegate_run_dir"
```

The quoted heredoc preserves literal `$`, backticks, and other shell syntax in the prompt. When generating prompts programmatically, write them through a file API or pass an argument array; do not interpolate untrusted text into a shell command.

With `--json`, stdout contains JSONL events, not just the answer. Keep stderr separate and use `--output-last-message` for the final response. Inspect all three artifacts; an empty or missing result is not success.

## Delegate implementation

Use the same execution pattern with `--sandbox workspace-write` and a task-specific implementation prompt. For example:

```text
Implement the agreed fix for the request retry deadline.
Editable scope: src/client/retry.py and tests/test_retry.py.
Read applicable project instructions and preserve unrelated existing changes.
Acceptance: retries share the original total deadline; add a regression test
using the existing test framework; run the focused tests and report outcomes.
Do not commit, push, publish, or modify files outside the editable scope.
Perform this assignment yourself; do not delegate it again.
Return changed files, behavior changes, checks run with results, and blockers.
```

Replace all example paths and criteria with facts from the actual project. Local `exec` writes directly into its selected workspace. Inspect those edits there; do not run `codex apply` as a routine follow-up or apply the same changes twice.

If using `--worktree`, confirm the resulting worktree path and inspect its actual diff before integrating it. Worktree isolation does not itself authorize commits, merges, or pushes.

## Review a Git change set

Prefer `codex exec review` when you need the same JSONL and final-message capture as other delegated work. Choose one target: `--uncommitted` (staged, unstaged, and untracked), `--base BRANCH`, or `--commit SHA`. Verify the target exists; do not assume the base is named `main`.

Using the workspace from the earlier example, create a new artifact directory:

```bash
delegate_run_dir=$(mktemp -d "${TMPDIR:-/tmp}/delegate-codex.XXXXXX")
delegate_exit=0
codex -a never exec -C "$delegate_workspace" --sandbox read-only \
  review --uncommitted --json \
  --output-last-message "$delegate_run_dir/result.md" \
  > "$delegate_run_dir/events.jsonl" \
  2> "$delegate_run_dir/stderr.log" || delegate_exit=$?
printf '%s\n' "$delegate_exit" > "$delegate_run_dir/exit-code.txt"
```

Keep target-selector examples free of positional custom prompts; compatibility varies across versions. For custom review instructions with an exact scope, use ordinary `codex exec --sandbox read-only` and describe both the target and review criteria in the prompt. Plain `codex review` is another non-interactive entrypoint, but its options differ from `exec review`; check its help before using it.

## Monitor and continue

If the calling environment returns a process/session handle while the command is still running, retain it and wait or poll through that environment's process API. An empty output interval is not a failure. Keep the user informed during long runs and use a task-appropriate time limit if one is required. Do not start a duplicate run merely because the first has not finished. Recent activity is visible in the event log:

```bash
jq -r 'select(.type == "item.started") | "\(.item.type) \(.item.command // "")"' \
  "$delegate_run_dir/events.jsonl" | tail -n 5
```

Record the Codex thread ID from a `thread.started` JSON event. This is different from the shell/process handle. With `jq` available:

```bash
delegate_session_id=$(jq -r \
  'select(.type == "thread.started") | .thread_id' \
  "$delegate_run_dir/events.jsonl" | head -n 1)
```

Resume only after the previous run finishes, using that exact ID. Avoid `--last` in orchestration: concurrent or unrelated work can change which session it selects. The following example assumes the ID is nonempty and a follow-up prompt has been written to a new artifact directory:

```bash
codex -a never exec -C "$delegate_workspace" --sandbox read-only \
  resume "$delegate_session_id" --json \
  --output-last-message "$delegate_followup_dir/result.md" \
  - < "$delegate_followup_dir/prompt.md" \
  > "$delegate_followup_dir/events.jsonl" \
  2> "$delegate_followup_dir/stderr.log"
```

Capture the exit code as in the first example. Keep parent `exec` options such as `-C` and `--sandbox` before `resume` or `review`; these subcommands do not expose identical option sets. Reassert the workspace and sandbox on follow-ups. Use `--ephemeral` only for disposable runs that will not need session resumption.

For automated consumption, add `--output-schema /absolute/path/schema.json` to request a structured final answer, then validate the saved result against that schema. `--json` alone only structures the event stream.

## Accept or repair the result

Before reporting completion:

1. Wait for process termination and inspect its exit code, final response, stderr, and any failure events (`turn.failed` or `error`). Intermediate errors may be recovered; determine the final outcome from the full run.
2. For analysis, verify material findings against the cited source and preserve uncertainty. For implementation, compare the working state with the recorded baseline, inspect all changed and newly created files, and confirm scope was respected.
3. Check the requested validation evidence. Run missing or independently necessary checks; do not treat an exit code of zero or the worker's claim as proof that acceptance criteria were met.
4. If a correctable issue remains, send a focused follow-up to the same session or finish locally. Before retrying an interrupted write task, inspect partial changes so work is not duplicated or overwritten. Stop retrying the same failure without new evidence or a changed condition.
5. Report the outcome, important evidence/checks, remaining limitations, and useful artifact paths. Mark failures or partial completion honestly.

For missing authentication, unavailable models, quota limits, invalid flags, or required tools that fail to start, inspect the actual error and resolve only within the existing authorization. Never print credentials in diagnostics.

## Sources

Primary command reference: the installed `codex --help`, `codex exec --help`, `codex exec resume --help`, `codex exec review --help`, and `codex review --help`.

The official [non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode) supplements local help for event handling and automation behavior. The examples target `codex-cli 0.163.0`; recheck installed help when versions differ.
