"""Tests for tap-qualified vs. plain package names.

Configs store third-party-tap packages fully qualified
(forketyfork/tap/clawtunes) so they install on a fresh machine, but the
package manager lists them installed under their short name
(clawtunes). Comparing the two forms naively marks every tap package as
"missing" — that's the bug this module exists to prevent.
"""

from tui.core.pkg_names import installed_index, is_installed, short_name


def test_short_name_strips_a_tap_qualifier():
    assert short_name("forketyfork/tap/clawtunes") == "clawtunes"


def test_short_name_leaves_a_plain_name_alone():
    assert short_name("ripgrep") == "ripgrep"


def test_short_name_keeps_version_suffixes():
    assert short_name("python@3.12") == "python@3.12"
    assert short_name("oven-sh/bun/bun") == "bun"


def test_short_name_tolerates_blank():
    assert short_name("") == ""


def test_is_installed_matches_a_qualified_config_entry_to_a_short_listing():
    """The actual regression: config says forketyfork/tap/clawtunes,
    brew list says clawtunes."""
    installed = installed_index(["clawtunes", "git"])
    assert is_installed("forketyfork/tap/clawtunes", installed)


def test_is_installed_matches_a_plain_name():
    installed = installed_index(["ripgrep"])
    assert is_installed("ripgrep", installed)


def test_is_installed_matches_when_the_listing_is_the_qualified_one():
    """Some package managers/versions report the qualified name — match
    that too rather than assuming one direction."""
    installed = installed_index(["forketyfork/tap/clawtunes"])
    assert is_installed("clawtunes", installed)
    assert is_installed("forketyfork/tap/clawtunes", installed)


def test_is_installed_false_for_something_absent():
    installed = installed_index(["git", "clawtunes"])
    assert not is_installed("ripgrep", installed)
    assert not is_installed("some/tap/ripgrep", installed)


def test_is_installed_does_not_match_a_different_package_from_another_tap():
    """Only the last path segment is the package name — a tap whose name
    coincides with some package must not produce a false match."""
    installed = installed_index(["clawtunes"])
    assert not is_installed("clawtunes/tap/something-else", installed)


def test_installed_index_holds_both_forms():
    index = installed_index(["clawtunes", "forketyfork/tap/other"])
    assert "clawtunes" in index
    assert "other" in index
    assert "forketyfork/tap/other" in index


def test_installed_index_ignores_blanks():
    assert installed_index(["git", "", "  "]) == installed_index(["git"])
