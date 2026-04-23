# Repository Guidelines

## Project Structure & Module Organization
- `bin/tt` is the primary entry point; it sources `bin/include.sh` for shared helpers, inspects `$HOME/.config/toolTamer`, and runs the menu flow.
- `bin/admin.sh` houses maintenance helpers (moving files, deduping packages) and depends on the environment bootstrapped by `tt`.
- Configuration data never lives in this repo: scripts expect host-specific directories under `~/.config/toolTamer/configs/`.
- `README.md` documents onboarding; keep contributor-facing nuggets there and cross-reference this guide when updating flows.

## Build, Test, and Development Commands
- `./bin/tt` — run the tool end-to-end; pass `-sh` to print the PATH export snippet for shell integration.
- `./bin/admin.sh` — open the Admin menu for moving files, deduping package lists, or inspecting configs.
- `BASE=$HOME/.config/toolTamer ./bin/tt` — override `BASE` if you need to target a disposable sandbox.
- `shellcheck bin/*.sh` and `shfmt -i 2 -bn -ci bin/*.sh` keep the Bash scripts linted and consistently formatted.

## Coding Style & Naming Conventions
- All scripts are Bash (`#!/usr/bin/env bash`); stick with 2-space indentation and brace-delimited functions like `function cleanup() { ... }`.
- Use lowercase names for functions (`syncFile`, `updateTTFromInstallation`) and uppercase snake case for globals (`INSTALLER`, `BASE`, `GN`).
- Prefer `[[]]` tests and quote expansions touching paths or user data; match existing logging helpers (`log`, `warn`, `err`) instead of ad-hoc `echo`.
- External commands should be centralized next to other installer logic so the macOS/Linux switch in `checkSystem` stays obvious.

## Testing Guidelines
- There is no automated suite; exercise changes by driving `./bin/tt` against a throwaway config under `~/.config/toolTamer/configs/devhost`.
- For file sync work, populate `files.conf` entries and verify `syncFile` copies/backs up by comparing SHA sums shown in the log.
- For package management tweaks, pipe `LIST` and `USES` overrides through `BASE=/tmp/tt-test` to ensure sorting/dedup logic handles duplicates.
- Document manual test scenarios in PRs (e.g., “Ran `tt` on macOS 14 with brew taps and verified uninstall prompts.”).

## Commit & Pull Request Guidelines
- Follow the imperative, sentence-case style already in history (`fixing local install - adding common`, `moving / adding packages`); keep subjects under ~60 characters.
- Each PR should explain why the change is needed, how to test it, and list any risk to user environments (package removals, config migrations, etc.).
- Link issues when available, include screenshots or terminal excerpts for new menu flows, and mention OS versions/tools covered during testing.

## Python TUI (tui/)

- `tui/` contains the Textual-based TUI frontend; entry point is `bin/tt-tui` or `python -m tui.app`.
- Use Python 3.12+; dependencies managed via `pyproject.toml`; venv in `.venv/`.
- Run tests: `source .venv/bin/activate && pytest tests/ -v`
- Run TUI: `source .venv/bin/activate && python -m tui.app`
- Core logic lives in `tui/core/` (config reading, system detection); screens in `tui/screens/`.
- The classic Bash TUI remains available via `bin/tt` or `bin/tt-tui --classic`.
