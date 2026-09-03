"""Tests for warmDepCache() in bin/tt.

The function's whole value depends on it picking *exactly* the packages
the sync loop right below it runs depCount() on: warming a different set
leaves the real lookups uncached and the run is slow again, silently.
That coupling is invisible at a glance (two copies of the same filter,
40 lines apart), so it gets pinned here.

bin/tt cannot be sourced — it runs the sync when executed — so the
function is extracted from it and run against stubs, which also keeps
the real package manager and the real cache out of the test.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TT = REPO_ROOT / "bin" / "tt"


def _warm_dep_cache_source() -> str:
    """The warmDepCache() definition, lifted out of bin/tt."""
    body = re.search(
        r"^function warmDepCache\(\) \{.*?^\}$",
        TT.read_text(encoding="utf-8"),
        re.MULTILINE | re.DOTALL,
    )
    assert body, "warmDepCache() not found in bin/tt — was it renamed?"
    return body.group(0)


def run_warm(
    tmp: Path, installed: str, tracked_short: str, tool_rc: int = 0
) -> subprocess.CompletedProcess:
    """Run warmDepCache() with run_python_tool stubbed out. The stub
    copies the candidate file it was handed to `candidates.seen` and
    prints the TT_BASE it saw, so the test can assert on both."""
    tt_tmp = tmp / "tt-tmp"
    tt_tmp.mkdir(parents=True, exist_ok=True)
    (tt_tmp / "local_installed").write_text(installed)
    (tt_tmp / "to_install.short").write_text(tracked_short)

    script = f"""
    TMP="{tt_tmp}"
    BASE="{tmp}/base/"
    GN=""; RESET=""
    function log() {{ echo "LOG: $1"; }}
    function warn() {{ echo "WARN: $1"; }}
    function run_python_tool() {{
      echo "TT_BASE=$TT_BASE"
      while [ $# -gt 0 ]; do
        [ "$1" = "--candidates" ] && cp "$2" "{tmp}/candidates.seen"
        [ "$1" = "--installed" ] && cp "$2" "{tmp}/installed.seen"
        shift
      done
      return {tool_rc}
    }}
    {_warm_dep_cache_source()}
    warmDepCache
    echo "rc=$?"
    """
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, cwd=str(tmp)
    )


def _candidates(tmp: Path) -> list[str]:
    seen = tmp / "candidates.seen"
    return seen.read_text().split() if seen.exists() else []


class TestCandidateSelection:
    def test_only_untracked_packages_are_warmed(self, tmp_path):
        run_warm(tmp_path, "git\nfzf\njson-glib\nicu4c@77\n", "git\nfzf\n")
        assert _candidates(tmp_path) == ["json-glib", "icu4c@77"]

    def test_tap_qualified_tracked_package_is_not_a_candidate(self, tmp_path):
        """to_install.short holds short names; the installed list does
        too. Same normalization as the sync loop — otherwise every tap
        package gets a lookup the loop never asks for."""
        run_warm(tmp_path, "clawtunes\njson-glib\n", "clawtunes\n")
        assert _candidates(tmp_path) == ["json-glib"]

    def test_blank_comment_and_assignment_lines_are_skipped(self, tmp_path):
        run_warm(tmp_path, "\n# a comment\nSOME=VALUE\njson-glib\n\n", "")
        assert _candidates(tmp_path) == ["json-glib"]

    def test_substring_matches_do_not_count_as_tracked(self, tmp_path):
        """The sync loop matches whole lines (grep -qxF): a tracked
        "neovim" must not make an installed "vim" look tracked."""
        run_warm(tmp_path, "vim\n", "neovim\n")
        assert _candidates(tmp_path) == ["vim"]

    def test_nothing_untracked_skips_the_tool_entirely(self, tmp_path):
        result = run_warm(tmp_path, "git\nfzf\n", "git\nfzf\n")
        assert not (tmp_path / "candidates.seen").exists()
        assert "rc=0" in result.stdout

    def test_empty_installed_list_is_not_an_error(self, tmp_path):
        result = run_warm(tmp_path, "", "git\n")
        assert "rc=0" in result.stdout


class TestHandover:
    def test_installed_list_is_passed_through_unfiltered(self, tmp_path):
        """It keys the cache fingerprint, which bin/tt computes from the
        raw file — the candidate filter must not touch it."""
        run_warm(tmp_path, "git\nweird=name\njson-glib\n", "git\n")
        assert (tmp_path / "installed.seen").read_text() == "git\nweird=name\njson-glib\n"

    def test_tt_base_is_pinned_to_the_bash_side_base(self, tmp_path):
        result = run_warm(tmp_path, "json-glib\n", "")
        assert f"TT_BASE={tmp_path}/base/" in result.stdout

    def test_failing_warm_up_warns_but_succeeds(self, tmp_path):
        """A failed pre-computation only means the slow path — it must
        never abort the sync."""
        result = run_warm(tmp_path, "json-glib\n", "", tool_rc=1)
        assert "WARN:" in result.stdout
        assert "rc=0" in result.stdout
