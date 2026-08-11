"""Matching package names across the two forms they appear in.

Third-party-tap packages are stored in configs fully qualified
(`forketyfork/tap/clawtunes`) because the short name only resolves on a
machine where the tap is already tapped — see tui/fix_taps.py. But the
package manager lists them installed under their short name
(`clawtunes`).

So a direct `pkg in installed` comparison reports every tap package as
missing. Everything that compares a config entry against the installed
set goes through here instead.
"""


def short_name(package: str) -> str:
    """Package name without its tap qualifier:
    `forketyfork/tap/clawtunes` -> `clawtunes`. Plain names and version
    suffixes (`python@3.12`) are returned unchanged."""
    return package.rsplit("/", 1)[-1]


def installed_index(installed) -> set[str]:
    """Lookup set for `is_installed`, holding every installed package
    under both the name it was listed as and its short form — so it
    matches whichever form a config happens to use."""
    index: set[str] = set()
    for name in installed:
        if not name or not name.strip():
            continue
        name = name.strip()
        index.add(name)
        index.add(short_name(name))
    return index


def is_installed(package: str, index: set[str]) -> bool:
    """Whether `package` (as written in a config, qualified or not) is
    present in an `installed_index`."""
    if not package:
        return False
    return package in index or short_name(package) in index
