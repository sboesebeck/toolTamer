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
    python -m tui.secrets join [--admin-key KEY|PATH|-]
    python -m tui.secrets status
    python -m tui.secrets check
    python -m tui.secrets migrate [--apply] [--all] [--scope S] [PATH ...]
    python -m tui.secrets rotate SCOPE [--admin-key KEY|PATH|-]
    python -m tui.secrets encrypt --scope S --in F --out G
    python -m tui.secrets decrypt --scope S --in F --out G
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import socket
import sys
import tempfile
from pathlib import Path

from tui.core.machine_id import read_machine_id
from tui.core.secrets import (
    SecretStore,
    SecretsError,
    age_binary,
    is_ciphertext,
)

AGE_SECRET_PREFIX = "AGE-SECRET-KEY-"

# NOTE: tui.core.config / tui.core.secret_ops are imported lazily inside the
# commands that need the config hierarchy. The `encrypt` / `decrypt` path —
# the one Bash calls on every secret during a sync — must run on a machine
# that has neither the repo venv nor `pathspec` (tui.core.config pulls in the
# ignore engine). Keeping them out of the top level keeps that path stdlib +
# age only.

# Path fragments that are secrets in the overwhelming majority of setups.
# Only a hint for `migrate` and `check` — explicit paths and --all always
# win, and `migrate` never writes without --apply.
SECRET_HINTS = (
    ".ssh/",
    ".ssh",
    ".gnupg/",
    ".aws/",
    ".kube/",
    ".netrc",
    ".git-credentials",
    ".docker/config.json",
    ".pem",
    "backupkey",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "token",
    "secret",
    "credential",
    "password",
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


def _extract_secret_key(text: str) -> str | None:
    """Pull the `AGE-SECRET-KEY-...` line out of pasted text.

    An age-keygen file has comment lines above the key, so a pasted file
    (or a whole `cat keys/admin.key`) must be accepted as-is."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(AGE_SECRET_PREFIX):
            return line
    return None


@contextlib.contextmanager
def admin_key_from(store: SecretStore, value: str | None):
    """Resolve how the recovery key is supplied, returning a Path or None.

    Accepts, in order of preference (most secure first):
      - nothing: the local `keys/admin.key`, else an interactive hidden prompt;
      - `-`: read the key text from stdin;
      - an inline `AGE-SECRET-KEY-...` value (visible in shell history and
        `ps`, so the prompt or stdin is better);
      - any other value: a path to a file holding the key.
    Inline/stdin keys live in a 0600 temp file for the duration of the call
    and are deleted afterwards."""
    text: str | None = None
    path: Path | None = None
    if value and value.strip() == "-":
        text = _extract_secret_key(sys.stdin.read())
    elif value:
        candidate = Path(value)
        if candidate.is_file():
            path = candidate
        else:
            # Not a file: accept an inline key, including a pasted age-keygen
            # file (comment lines included).
            text = _extract_secret_key(value)
            if text is not None:
                print(
                    "warning: an inline key is visible in your shell history and "
                    "process list. Prefer 'tt secrets join' (hidden prompt) or "
                    "--admin-key - (stdin).",
                    file=sys.stderr,
                )
    elif store.admin_key_path.is_file():
        path = store.admin_key_path
    elif sys.stdin.isatty():
        try:
            text = _extract_secret_key(getpass.getpass("Admin/recovery key: "))
        except (EOFError, KeyboardInterrupt):
            text = None
    if not text:
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="tt-adminkey-") as td:
        p = Path(td) / "admin.key"
        p.write_text(text + "\n")
        os.chmod(p, 0o600)
        yield p


def _is_secret_hint(target: str) -> bool:
    t = target.lower()
    # Public keys are not secrets — and `.ssh/*.pub` would otherwise be
    # proposed for every key. Explicit paths/--all still cover them.
    if t.endswith(".pub"):
        return False
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
        print("  tt secrets join          # paste the recovery key at the prompt")
        return 0
    print(f"Scopes ready: {', '.join(scopes)}")
    return 0


def cmd_join(args: argparse.Namespace) -> int:
    from tui.core.secret_ops import join_scopes

    base, machine_id, cfg, store = _context(args.base)
    if not store.has_personal_key():
        print("No personal key — run 'tt secrets init' first.", file=sys.stderr)
        return 2
    with admin_key_from(store, args.admin_key) as admin_key:
        if admin_key is None:
            print(
                "No admin key available. Provide the recovery key by:\n"
                "  tt secrets join                 # hidden prompt (recommended)\n"
                "  echo 'AGE-SECRET-KEY-...' | tt secrets join --admin-key -\n"
                f"  or place it at {store.admin_key_path}",
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

    # Entries that still live in files.conf but look like secrets. This is the
    # dangerous state: a private key committed in plaintext, which a
    # declared-secret-only check would not catch. Scanned across every config,
    # not just this machine's chain — the repo is shared with all of them.
    suspects = 0
    for config in cfg.list_configs():
        for stored, target in cfg.get_file_mappings(config):
            if cfg.is_secret(config, stored, target):
                continue
            if not _is_secret_hint(target):
                continue
            path = cfg.configs_dir / config / "files" / stored
            if path.is_dir() or not path.exists() or is_ciphertext(path):
                continue
            print(
                f"UNENCRYPTED {config}:{stored} -> ~/{target} looks like a secret "
                f"but is still in files.conf — run "
                f"'tt secrets migrate --match <part> --apply'",
                file=sys.stderr,
            )
            suspects += 1

    if problems or suspects:
        if suspects:
            print(
                f"{suspects} plaintext entry(ies) still in files.conf — "
                f"'tt secrets migrate' with --match/--all encrypts them.",
                file=sys.stderr,
            )
        print(f"{problems} declared-secret problem(s), {suspects} suspect(s).", file=sys.stderr)
        return 1
    print("All secrets are encrypted and have a scope key.")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from tui.core.config import _resolve_effective_target
    from tui.core.secret_ops import ensure_scope_for, mark_inner_secret, migrate_entry

    base, machine_id, cfg, store = _context(args.base)
    if age_binary() is None:
        print("age is not installed — install it first.", file=sys.stderr)
        return 2
    admin_key = store.find_admin_key()
    explicit = {_resolve_effective_target(p, p) for p in (args.paths or [])}
    matches = tuple(args.match or ())

    # (config, stored, target, scope, action, inner_rel): "encrypt" moves a
    # files.conf entry into secrets.conf; "reencrypt" fixes a secrets.conf
    # entry whose stored copy is still plaintext; "inner" carves a file out
    # of a tracked directory (inner_rel set).
    plan: list[tuple[str, str, str, str, str, str | None]] = []
    seen: set[tuple[str, str, str]] = set()
    mapping_targets: set[str] = set()

    for secret in cfg.get_effective_secrets(machine_id):
        if not secret.is_effective or not secret.repo_path.is_file():
            continue
        if is_ciphertext(secret.repo_path):
            continue
        plan.append((secret.config, secret.stored, secret.target, secret.scope, "reencrypt", None))
        seen.add((secret.config, secret.stored, secret.target))

    for mapping in cfg.get_effective_file_mappings(machine_id):
        if not mapping.is_effective:
            continue
        mapping_targets.add(mapping.effective_target)
        path = mapping.repo_path
        if not path.is_file() or path.is_symlink():
            continue  # v1: single regular files only
        if (mapping.config, mapping.stored, mapping.target) in seen:
            continue
        if cfg.is_secret(mapping.config, mapping.stored, mapping.target):
            continue
        eff = mapping.effective_target
        wanted = (
            args.all
            or eff in explicit
            or _is_secret_hint(eff)
            or any(sub in eff for sub in matches)
        )
        if not wanted:
            continue
        scope = args.scope or mapping.config
        plan.append((mapping.config, mapping.stored, mapping.target, scope, "encrypt", None))

    # Explicit paths that point *inside* a tracked directory: carve them out.
    chain = cfg.resolve_chain(machine_id)
    for target_path in sorted(explicit):
        if target_path in mapping_targets:
            continue
        covering = cfg.find_covering_dir(target_path, chain)
        if covering is None:
            continue
        base_eff = covering.effective_target.rstrip("/")
        if not target_path.startswith(base_eff + "/"):
            continue
        inner_rel = target_path[len(base_eff) + 1:]
        if not (covering.repo_path / inner_rel).is_file():
            continue
        scope = args.scope or covering.config
        plan.append((covering.config, covering.stored, covering.target, scope, "inner", inner_rel))

    if not plan:
        print("Nothing to migrate.")
        print("  Select entries with: --all, --match SUBSTR (e.g. --match .ssh/),")
        print("  explicit ~/paths (a file inside a tracked dir works too),")
        print("  or press 's' on an entry in the file manager.")
        return 0

    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(plan)} file(s) to encrypt")
    for config, stored, target, scope, action, inner_rel in plan:
        if action == "inner":
            eff = _resolve_effective_target(stored, target).rstrip("/")
            what = f"{config}:{stored}/{inner_rel}"
            target_disp = f"{eff}/{inner_rel}"
        else:
            what = f"{config}:{stored}"
            target_disp = target
        tag = " (re-encrypt)" if action == "reencrypt" else (" (inside dir)" if action == "inner" else "")
        print(f"  {what} -> ~/{target_disp}  [{scope}]{tag}")
    if not args.apply:
        print("\nRe-run with --apply to encrypt and rewrite the configs.")
        return 0

    # Ensure the scopes exist and include every entitled machine (only the
    # entries being moved into secrets.conf need a scope set up; a re-encrypt
    # targets a scope that already exists).
    for scope in sorted({e[3] for e in plan if e[4] in ("encrypt", "inner")}):
        ensure_scope_for(cfg, store, machine_id, scope, admin_key)

    migrated = 0
    for config, stored, target, scope, action, inner_rel in plan:
        path = cfg.configs_dir / config / "files" / stored
        try:
            if action == "encrypt":
                migrate_entry(cfg, store, machine_id, config, stored, target, scope, admin_key)
                print(f"  encrypted {config}:{stored} [{scope}]")
            elif action == "inner":
                mark_inner_secret(
                    cfg, store, machine_id, config, stored, inner_rel, scope, admin_key
                )
                print(f"  encrypted {config}:{stored}/{inner_rel} [{scope}] (carved out of dir)")
            else:
                if not store.has_scope_key(scope):
                    raise SecretsError(
                        f"scope '{scope}' has no key — run 'tt secrets join' first"
                    )
                store.encrypt_to_scope(scope, path, path)
                print(f"  re-encrypted {config}:{stored} [{scope}]")
        except SecretsError as exc:
            print(f"  FAILED {config}:{stored}: {exc}", file=sys.stderr)
            return 1
        migrated += 1
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
    files: list[Path] = []
    for config in cfg.list_configs():
        for stored, _target, sc in cfg.get_secrets(config):
            if sc == scope:
                files.append(cfg.configs_dir / config / "files" / stored)
    members = members_for(cfg, store, scope)
    if machine_id not in members:
        members.append(machine_id)
    with admin_key_from(store, args.admin_key) as admin_key:
        count = store.rotate_scope(scope, members, files, admin_key=admin_key)
    print(f"Rotated scope '{scope}': new key, {count} file(s) re-encrypted.")
    return 0


def cmd_unmark(args: argparse.Namespace) -> int:
    from tui.core.config import _resolve_effective_target
    from tui.core.secret_ops import unmark_inner_secret

    _base, machine_id, cfg, store = _context(args.base)
    target = _resolve_effective_target(args.path, args.path)
    chain = cfg.resolve_chain(machine_id)
    covering = cfg.find_covering_dir(target, chain)
    if covering is None:
        print(f"~/{target} does not lie inside a tracked directory.", file=sys.stderr)
        return 2
    base_eff = covering.effective_target.rstrip("/")
    if not target.startswith(base_eff + "/"):
        print(f"~/{target} is not inside tracked directory ~/{base_eff}.", file=sys.stderr)
        return 2
    inner_rel = target[len(base_eff) + 1:]
    stored = f"{covering.stored}/{inner_rel}"
    inner_target = f"{base_eff}/{inner_rel}"
    scope = next(
        (sc for s, t, sc in cfg.get_secrets(covering.config)
         if s == stored and t == inner_target),
        None,
    )
    if scope is None:
        print(f"~/{target} is not an inner secret entry.", file=sys.stderr)
        return 2
    try:
        unmark_inner_secret(
            cfg, store, covering.config, covering.stored, inner_rel, scope,
            store.find_admin_key(),
        )
    except SecretsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Decrypted ~/{target} back into the directory mirror.")
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
    p_join.add_argument(
        "--admin-key", default=None,
        help="recovery key: omitted = hidden prompt, '-' = stdin, else a "
             "path or an inline AGE-SECRET-KEY-... (inline leaks to history/ps)",
    )
    sub.add_parser("status", help="show keys, machines and scope membership")
    sub.add_parser("check", help="fail if a secret entry is not encrypted")

    p_mig = sub.add_parser("migrate", help="encrypt existing plaintext entries")
    p_mig.add_argument("paths", nargs="*", help="explicit ~/relative targets")
    p_mig.add_argument("--apply", action="store_true", help="write changes")
    p_mig.add_argument("--all", action="store_true", help="migrate every file entry")
    p_mig.add_argument(
        "--match", action="append", default=None, metavar="SUBSTR",
        help="select entries whose target contains SUBSTR (e.g. --match .ssh/); repeatable",
    )
    p_mig.add_argument("--scope", default=None, help="force one scope for all")

    p_rot = sub.add_parser("rotate", help="re-key a scope and re-encrypt its files")
    p_rot.add_argument("scope")
    p_rot.add_argument(
        "--admin-key", default=None,
        help="recovery key: omitted = hidden prompt, '-' = stdin, else a "
             "path or an inline AGE-SECRET-KEY-... (inline leaks to history/ps)",
    )

    p_unmark = sub.add_parser(
        "unmark", help="decrypt a file carved out of a tracked directory"
    )
    p_unmark.add_argument("path", help="~/relative target inside a tracked dir")

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
    "unmark": cmd_unmark,
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
