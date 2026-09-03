# Repository Guidelines

## Project Structure & Module Organization
- `bin/tt` is the primary entry point; it sources `bin/include.sh` for shared helpers, inspects `$HOME/.config/toolTamer`, and runs the menu flow. It also bootstraps `.venv` and dispatches to the Python tools.
- `bin/admin.sh` houses maintenance helpers (moving files, deduping packages) and depends on the environment bootstrapped by `tt`.
- `tui/` is the Python/Textual half: the interactive TUI plus the helper tools (`tui/cleanup_deps.py`, `tui/fix_taps.py`, `tui/warm_deps.py`). Core logic in `tui/core/`, screens in `tui/screens/`, widgets in `tui/widgets/`.
- `tests/` holds the pytest suite covering the Python half.
- Configuration data never lives in this repo: scripts expect host-specific directories under `~/.config/toolTamer/configs/` (override with `TT_BASE`).
- `README.md` documents onboarding; keep contributor-facing nuggets there and cross-reference this guide when updating flows.

## Build, Test, and Development Commands
- `./bin/tt` — run the tool end-to-end; pass `-sh` to print the PATH export snippet for shell integration.
- `./bin/tt --fix-taps` / `--cleanup-deps` — config audit tools; both dry-run unless `--apply` is given, and pass further arguments through.
- `./bin/tt --warm-deps` — fill the reverse-dependency cache with the set a sync needs, in parallel. `--syncSys` runs this itself; the standalone command just pays the cost up front.
- `./bin/admin.sh` — open the Admin menu for moving files, deduping package lists, or inspecting configs.
- `TT_BASE=/tmp/tt-test ./bin/tt` — target a disposable config sandbox.
- `source .venv/bin/activate && python -m pytest -q` — run the test suite.
- `shellcheck -x bin/tt bin/include.sh` and `shfmt -i 2 -bn -ci bin/*.sh` keep the Bash scripts linted and consistently formatted.

## Coding Style & Naming Conventions
- Bash scripts (`#!/usr/bin/env bash`): 2-space indentation and brace-delimited functions like `function cleanup() { ... }`. Python: standard 4-space, snake_case, Python 3.12+.
- Use lowercase names for functions (`syncFile`, `updateTTFromInstallation`) and uppercase snake case for globals (`INSTALLER`, `BASE`, `GN`).
- Prefer `[[]]` tests and quote expansions touching paths or user data; match existing logging helpers (`log`, `warn`, `err`) instead of ad-hoc `echo`.
- External commands should be centralized next to other installer logic so the macOS/Linux switch in `checkSystem` stays obvious.

## Testing Guidelines
- The Python half has an automated suite (`python -m pytest -q`, ~190 tests). Add tests with changes; screens are driven through Textual's `run_test()` pilot, and `@work` methods are callable synchronously via `.__wrapped__`.
- `tests/conftest.py` points `TT_BASE` at a temp dir for every test. Any test using a real config must set `TT_BASE` to its own tmp dir — patching `TTConfig` alone is not enough, since paths like the dependency cache are derived from `TT_BASE` directly.
- Mock every `SystemInfo` method a screen can reach (`list_installed_packages`, `list_dependency_packages`, `get_required_by`, `get_package_info`, `get_package_tap`); mounting a screen auto-highlights a row and would otherwise fire real subprocess calls.
- `bin/` has no automated suite: verify with `bash -n`, `shellcheck -x`, and stub binaries on `PATH`. Note `include.sh` sets `BASE` itself when sourced, so set test overrides *after* sourcing.
- For file sync work, populate `files.conf` entries and verify `syncFile` copies/backs up by comparing SHA sums shown in the log.
- Document manual test scenarios in PRs (e.g., “Ran `tt` on macOS 14 with brew taps and verified uninstall prompts.”).

## Commit & Pull Request Guidelines
- Follow the imperative, sentence-case style already in history (`fixing local install - adding common`, `moving / adding packages`); keep subjects under ~60 characters.
- Each PR should explain why the change is needed, how to test it, and list any risk to user environments (package removals, config migrations, etc.).
- Link issues when available, include screenshots or terminal excerpts for new menu flows, and mention OS versions/tools covered during testing.

## Python TUI (tui/)

- `tui/` contains the Textual-based TUI frontend; entry point is `bin/tt-tui` or `python -m tui.app`.
- Use Python 3.12+; dependencies managed via `pyproject.toml`; venv in `.venv/`.
- Run tests: `source .venv/bin/activate && python -m pytest -q`
- Run TUI: `source .venv/bin/activate && python -m tui.app`
- Core logic lives in `tui/core/` (config reading, system detection); screens in `tui/screens/`.
- The classic Bash TUI remains available via `bin/tt` or `bin/tt-tui --classic`.

## Gotchas worth knowing before changing package logic

These are documented at length in `CLAUDE.md` and in code comments; the short version:

- **Two different dependency signals.** `list_dependency_packages()` = install *reason* (cheap, one call, can be stale). `get_required_by()` = structural, "is it needed right now" (slow, one call per package). Uninstall decisions use the structural one.
- **Don't replace `brew uses` with a bulk formula query.** It looks ~20x faster but is formula-based rather than receipt-based, and reports genuinely-required packages as removable. Verified against all installed formulae. The slow call is cached instead (`tui/core/dep_cache.py`, shared with `bin/tt`).
- **Tap packages are stored fully qualified** (`forketyfork/tap/clawtunes`) but *listed* installed under the short name. Compare via `tui/core/pkg_names.py`, never directly.
- **Textual `@work(exclusive=True)` shares one default group** — unrelated exclusive workers cancel each other unless given their own `group=`. `exclusive` also does not stop a running thread worker; check `worker.is_cancelled` yourself.
- **`on_<message>` handlers run for every class in the MRO** that defines one, not just the most-derived override.
