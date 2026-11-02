# delegate-codex — development notes

Not loaded by agents; `SKILL.md` holds the functional content.

## Verification history

- 2026-10-13, `codex-cli 0.162.1`: examples checked; explicit sandbox settings adopted instead of the `--full-auto` shortcut.
- 2026-10-21, `codex-cli 0.163.0` (Linux):
  - `codex -a never exec -C <ws> --sandbox read-only --json --output-last-message <file> - < prompt` ran a full read-only review: exit 0, empty stderr, `thread.started` carries `thread_id`.
  - Event types observed: `thread.started`, `turn.started`, `item.started`/`item.completed` (`command_execution`, `agent_message`), `turn.completed`.
  - `--full-auto` is now rejected (`unexpected argument`).
  - `exec resume` and `exec review` still lack `-C` and `--sandbox`, so those stay before the subcommand; both accept `--json`, `-o`, `--output-schema`, and `--ephemeral`.
  - `exec review` now documents a positional `[PROMPT]` (custom review instructions), but combining it with a target selector wasn't tested.
  - New flags not used by the skill: `exec fork`, `--approve-for-me`, `--ignore-user-config`, `--strict-config`.
  - The official docs URL `https://developers.openai.com/codex/noninteractive` redirects to the `learn.chatgpt.com` page cited in `SKILL.md`.
- 2026-10-25, user policy: never start the worker with a sandbox. Every example now passes `--sandbox danger-full-access`; analysis and review limits are prompt instructions. `codex -a never exec -C <ws> --sandbox danger-full-access --json` ran a task that created a file under `~/.cache` (outside the workspace and temporary areas): exit 0, file present.
