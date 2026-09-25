"""CLI and orchestration for ToolTamer secret scopes.

Split of responsibilities:

- `tui.core.secrets` is the pure key/crypto layer (age, scope keys,
  wrapping) and knows nothing about the config hierarchy.
- This module supplies the policy: which machines belong to a scope. A
  scope is a config name, and a registered machine is a member of every
  scope named in its include chain — so `common` reaches every machine and
  a host scope only its host, exactly like the file hierarchy.

Bash must never grow a second crypto implementation. `tt` calls the
`encrypt` / `decrypt` subcommands here, the same way it calls
`tui.ttignore` for ignore rules.

Usage:
    python -m tui.secrets init
    python -m tui.secrets join [--admin-key PATH]
    python -m tui.secrets status
    python -m tui.secrets check
    python -m tui.secrets migrate [--apply] [--all] [--scope S] [PATH ...]
    python -m tui.secrets rotate SCOPE [--admin-key PATH]
    python -m tui.secrets encrypt --scope S --in F --out G
    python -m tui.secrets decrypt --scope S --in F --out G
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

from tui.core.machine_id import read_machine_id
from tui.core.secrets import (
    SecretStore,
    SecretsError,
    age_binary,
    is_ciphertext,
)

# NOTE: tui.core.config / tui.core.secret_ops are imported lazily inside the
# commands that need the config hierarchy. The `encrypt` / `decrypt` path —
# the one Bash calls on every secret during a sync — must run on a machine
# that has neither the repo venv nor `pathspec` (tui.core.config pulls in the
# ignore engine). Keeping them out of the top level keeps that path stdlib +
# age only.

# Path fragments that are secrets in the overwhelming majority of setups.
# Only a hint for `migrate` — explicit paths and --all always win.
SECRET_HINTS = (
    ".ssh/id_",
    ".ssh/identity",
    ".aws/credentials",
    ".netrc",
    ".git-credentials",
    ".docker/config.json",
    ".kube/config",
    ".gnupg/",
    ".password-store/",
    "token",
    "secret",
    "credentials",
    ".env",
)


def default_base() -> Path:
    env = os.environ.get("TT_BASE")
    if env:
        return Path(env)
    return Path.home() / ".config" / "toolTamer"


def current_machine_id(base: Path) -> str:
    return read_machine_id(base) or socket.gethostname()


def _store_context(base: Path | None = None) -> tuple[Path, str, SecretStore]:
    base = Path(base) if base is not None else default_base()
    machine_id = current_machine_id(base)
    return base, machine_id, SecretStore(base, machine_id)


def _context(base: Path | None = None):
    from tui.core.config import TTConfig

    base, machine_id, store = _store_context(base)
    return base, machine_id, TTConfig(base), store


def _is_secret_hint(target: str) -> bool:
    t = target.lower()
    return any(hint in t for hint in SECRET_HINTS)


# --- commands -----------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    from tui.core.secret_ops import join_scopes

    base, machine_id, cfg, store = _context(args.base)
    if age_binary() is None:
        print("age is not installed — install it first (brew/apt install age)", file=sys.stderr)
        return 2
    pub = store.init_personal_key()
    admin_pub, created = store.ensure_admin_key()
    admin_key = store.find_admin_key()
    print(f"Personal key for '{machine_id}': {pub}")
    print(f"  private: {store.personal_key_path} (local, gitignored)")
    print(f"  public:  secrets/recipients/{machine_id}.pub (committed)")
    if created:
        print()
        print("Created a NEW admin/recovery key:")
        print(f"  public:  secrets/admin.pub (committed)")
        print(f"  private: {store.admin_key_path} (LOCAL)")
        print("Store that private key in your password manager. It is the only")
        print("way to add a lost machine or rotate keys. Keep it off the repo.")
    try:
        scopes = join_scopes(cfg, store, machine_id, admin_key)
    except SecretsError:
        # A new machine usually has no admin key locally yet; registering the
        # personal key is still the important half of init. `join` does the
        # membership step with the recovery key from the password manager.
        print()
        print(f"Scopes for '{machine_id}' not joined yet — run:")
        print("  tt secrets join --admin-key <your recovery key>")
        return 0
    print(f"Scopes ready: {', '.join(scopes)}")
    return 0


def cmd_join(args: argparse.Namespace) -> int:
    from tui.core.secret_ops import join_scopes

    base, machine_id, cfg, store = _context(args.base)
    if not store.has_personal_key():
        print("No personal key — run 'tt secrets init' first.", file=sys.stderr)
        return 2
    admin_key = store.find_admin_key(Path(args.admin_key) if args.admin_key else None)
    if admin_key is None:
        print(
            "No admin key available. Pass --admin-key PATH (the recovery key you "
            "stored in your password manager), or place it at "
            f"{store.admin_key_path}.",
            file=sys.stderr,
        )
        return 2
    scopes = join_scopes(cfg, store, machine_id, admin_key)
    print(f"Joined scopes: {', '.join(scopes)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from tui.core.secret_ops import members_for

    _base, machine_id, cfg, store = _context(args.base)
    print(f"machine id : {machine_id}")
    print(f"personal   : {'yes' if store.has_personal_key() else 'NO'}")
    admin = store.admin_public_key()
    print(f"admin key  : {admin or 'none'}")
    print(f"machines   : {', '.join(store.registered_machines()) or 'none'}")
    scopes = store.list_scopes()
    print(f"scopes     : {', '.join(scopes) or 'none'}")
    for scope in scopes:
        members = store.scope_members(scope) or []
        derived = members_for(cfg, store, scope)
        stale = " (stale: recompute via join)" if sorted(members) != sorted(derived) else ""
        print(f"  {scope}: members={', '.join(members) or '-'}{stale}")
    for config in cfg.list_configs():
        secrets = cfg.get_secrets(config)
        if secrets:
            print(f"secrets in '{config}':")
            for stored, target, scope in secrets:
                print(f"  {stored} -> ~/{target}  [{scope}]")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Refuse when a secrets.conf entry is not ciphertext (plaintext leak)."""
    _base, _machine_id, cfg, store = _context(args.base)
    problems = 0
    for config in cfg.list_configs():
        for stored, target, scope in cfg.get_secrets(config):
            path = cfg.configs_dir / config / "files" / stored
            if not path.exists():
                print(f"MISSING  {config}:{stored} -> ~/{target}", file=sys.stderr)
                problems += 1
            elif not is_ciphertext(path):
                print(
                    f"PLAINTEXT {config}:{stored} -> ~/{target} is not age ciphertext "
                    f"— run 'tt secrets migrate'",
                    file=sys.stderr,
                )
                problems += 1
            elif not store.has_scope_key(scope):
                print(f"NO KEY   {config}:{stored} scope '{scope}' has no key", file=sys.stderr)
                problems += 1
    if problems:
        print(f"{problems} secret problem(s).", file=sys.stderr)
        return 1
    print("All secrets are encrypted and have a scope key.")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from tui.core.config import _resolve_effective_target
    from tui.core.secret_ops import ensure_scope_for, migrate_entry

    base, machine_id, cfg, store = _context(args.base)
    if age_binary() is None:
        print("age is not installed — install it first.", file=sys.stderr)
        return 2
    admin_key = store.find_admin_key()
    explicit = {_resolve_effective_target(p, p) for p in (args.paths or [])}

    plan: list[tuple[str, str, str, str]] = []  # config, stored, target, scope
    for mapping in cfg.get_effective_file_mappings(machine_id):
        if not mapping.is_effective:
            continue
        path = mapping.repo_path
        if not path.is_file() or path.is_symlink():
            continue  # v1: single regular files only
        already = {(s, t) for s, t, _sc in cfg.get_secrets(mapping.config)}
        if (mapping.stored, mapping.target) in already:
            continue
        eff = mapping.effective_target
        wanted = args.all or eff in explicit or _is_secret_hint(eff)
        if not wanted:
            continue
        scope = args.scope or mapping.config
        plan.append((mapping.config, mapping.stored, mapping.target, scope))

    if not plan:
        print("Nothing to migrate.")
        return 0

    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(plan)} file(s) to encrypt")
    for config, stored, target, scope in plan:
        print(f"  {config}:{stored} -> ~/{target}  [{scope}]")
    if not args.apply:
        print("\nRe-run with --apply to encrypt and rewrite the configs.")
        return 0

    # Ensure the scopes exist and include every entitled machine.
    for scope in sorted({scope for _c, _s, _t, scope in plan}):
        ensure_scope_for(cfg, store, machine_id, scope, admin_key)

    migrated = 0
    for config, stored, target, scope in plan:
        try:
            migrate_entry(cfg, store, machine_id, config, stored, target, scope, admin_key)
        except SecretsError as exc:
            print(f"  FAILED {config}:{stored}: {exc}", file=sys.stderr)
            return 1
        migrated += 1
        print(f"  encrypted {config}:{stored} [{scope}]")
    print(f"Migrated {migrated} file(s). Commit secrets/*.pub, *.key.age, *.members,")
    print("the rewritten *.conf and the encrypted files under configs/.")
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    from tui.core.secret_ops import members_for

    _base, machine_id, cfg, store = _context(args.base)
    scope = args.scope
    if not store.has_scope_key(scope):
        print(f"Scope '{scope}' has no key.", file=sys.stderr)
        return 2
    admin_key = store.find_admin_key(Path(args.admin_key) if args.admin_key else None)
    files: list[Path] = []
    for config in cfg.list_configs():
        for stored, _target, sc in cfg.get_secrets(config):
            if sc == scope:
                files.append(cfg.configs_dir / config / "files" / stored)
    members = members_for(cfg, store, scope)
    if machine_id not in members:
        members.append(machine_id)
    count = store.rotate_scope(scope, members, files, admin_key=admin_key)
    print(f"Rotated scope '{scope}': new key, {count} file(s) re-encrypted.")
    return 0


def cmd_encrypt(args: argparse.Namespace) -> int:
    _base, _machine_id, store = _store_context(args.base)
    store.encrypt_to_scope(args.scope, Path(args.input), Path(args.output))
    return 0


def cmd_decrypt(args: argparse.Namespace) -> int:
    _base, _machine_id, store = _store_context(args.base)
    store.decrypt_from_scope(args.scope, Path(args.input), Path(args.output))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tui.secrets")
    parser.add_argument("--base", type=Path, default=None, help="override TT_BASE")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create this machine's key and register it")
    p_join = sub.add_parser("join", help="become a member of your chain's scopes")
    p_join.add_argument("--admin-key", default=None)
    sub.add_parser("status", help="show keys, machines and scope membership")
    sub.add_parser("check", help="fail if a secret entry is not encrypted")

    p_mig = sub.add_parser("migrate", help="encrypt existing plaintext entries")
    p_mig.add_argument("paths", nargs="*", help="explicit ~/relative targets")
    p_mig.add_argument("--apply", action="store_true", help="write changes")
    p_mig.add_argument("--all", action="store_true", help="migrate every file entry")
    p_mig.add_argument("--scope", default=None, help="force one scope for all")

    p_rot = sub.add_parser("rotate", help="re-key a scope and re-encrypt its files")
    p_rot.add_argument("scope")
    p_rot.add_argument("--admin-key", default=None)

    p_enc = sub.add_parser("encrypt", help="encrypt a file to a scope")
    p_enc.add_argument("--scope", required=True)
    p_enc.add_argument("--in", dest="input", required=True)
    p_enc.add_argument("--out", dest="output", required=True)

    p_dec = sub.add_parser("decrypt", help="decrypt a scope-encrypted file")
    p_dec.add_argument("--scope", required=True)
    p_dec.add_argument("--in", dest="input", required=True)
    p_dec.add_argument("--out", dest="output", required=True)

    return parser


COMMANDS = {
    "init": cmd_init,
    "join": cmd_join,
    "status": cmd_status,
    "check": cmd_check,
    "migrate": cmd_migrate,
    "rotate": cmd_rotate,
    "encrypt": cmd_encrypt,
    "decrypt": cmd_decrypt,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except SecretsError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
