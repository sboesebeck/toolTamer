"""Scope policy and migration helpers for secrets.

`tui.core.secrets` is the pure crypto layer; this module adds the pieces
that need the config hierarchy and are shared by the CLI (`tui.secrets`)
and the TUI: who is a member of a scope, how a machine joins, and how a
single plaintext entry becomes an encrypted one.
"""

from __future__ import annotations

from pathlib import Path

from tui.core.config import TTConfig, _resolve_effective_target
from tui.core.ignore import append_ignore, remove_ignore
from tui.core.secrets import SecretStore, SecretsError, is_ciphertext


def members_for(cfg: TTConfig, store: SecretStore, scope: str) -> list[str]:
    """Registered machines whose include chain names `scope`.

    `resolve_chain` always starts with `common`, so `common` has every
    registered machine as a member and a host scope only its own host."""
    return [
        m for m in store.registered_machines()
        if scope in cfg.resolve_chain(m)
    ]


def join_scopes(
    cfg: TTConfig, store: SecretStore, machine_id: str, admin_key: Path | None
) -> list[str]:
    """Ensure every scope in this machine's chain exists and is wrapped to
    its current member set (plus this machine). Returns the scopes."""
    done: list[str] = []
    for scope in cfg.resolve_chain(machine_id):
        members = members_for(cfg, store, scope)
        if machine_id not in members:
            members.append(machine_id)
        store.ensure_scope(scope, members, admin_key=admin_key)
        done.append(scope)
    return done


def ensure_scope_for(
    cfg: TTConfig, store: SecretStore, machine_id: str, scope: str,
    admin_key: Path | None = None,
) -> str:
    """Ensure `scope` exists and includes this machine, then return its
    public key. Used before encrypting a new secret into it."""
    members = members_for(cfg, store, scope)
    if machine_id not in members:
        members.append(machine_id)
    return store.ensure_scope(scope, members, admin_key=admin_key)


def migrate_entry(
    cfg: TTConfig,
    store: SecretStore,
    machine_id: str,
    config: str,
    stored: str,
    target: str,
    scope: str,
    admin_key: Path | None = None,
) -> None:
    """Turn one plaintext store file into a secret entry.

    Encrypts `configs/<config>/files/<stored>` in place to `scope`, records
    it in secrets.conf and drops the files.conf line (so the entry is not
    listed twice). Raises SecretsError when the file is missing or the
    scope cannot be reached."""
    path = cfg.configs_dir / config / "files" / stored
    if not path.is_file():
        raise SecretsError(f"{config}:{stored} does not exist as a file")
    ensure_scope_for(cfg, store, machine_id, scope, admin_key)
    store.encrypt_to_scope(scope, path, path)
    cfg.add_secret_mapping(config, stored, target, scope)
    cfg.remove_file_mapping(config, stored, target)


def _dir_effective_target(cfg: TTConfig, config: str, dir_stored: str) -> str:
    for stored, target in cfg.get_file_mappings(config):
        if stored == dir_stored:
            return _resolve_effective_target(stored, target)
    raise SecretsError(f"no files.conf entry for directory '{dir_stored}' in '{config}'")


def mark_inner_secret(
    cfg: TTConfig,
    store: SecretStore,
    machine_id: str,
    config: str,
    dir_stored: str,
    inner_rel: str,
    scope: str,
    admin_key: Path | None = None,
    home: Path | None = None,
) -> None:
    """Encrypt one file *inside* a tracked directory, as its own secret entry.

    The directory itself stays a plain mirror, but the file is carved out of
    it: an anchored `.ttignore` rule on both sides hides it from the mirror,
    and a normal secret entry (`<dir_stored>/<inner_rel>`) manages it. That
    way only the sensitive file is ciphertext — the rest of the tree keeps
    syncing (and diffing) as plaintext, no mirror changes needed."""
    files_root = cfg.configs_dir / config / "files"
    dir_store = files_root / dir_stored
    store_path = dir_store / inner_rel
    if not store_path.is_file() or store_path.is_symlink():
        raise SecretsError(f"{config}:{dir_stored}/{inner_rel} is not a stored file")
    dir_eff = _dir_effective_target(cfg, config, dir_stored)
    inner_target = f"{dir_eff}/{inner_rel}"
    ensure_scope_for(cfg, store, machine_id, scope, admin_key)
    store.encrypt_to_scope(scope, store_path, store_path)
    cfg.add_secret_mapping(config, f"{dir_stored}/{inner_rel}", inner_target, scope)
    # Hide it from the directory mirror on both sides: otherwise the mirror
    # would copy the plaintext store file over the system file (or delete it
    # as "extra"), fighting the secret entry that owns it now.
    append_ignore(dir_store, inner_rel, is_dir=False)
    sys_dir = (home or Path.home()) / dir_eff
    if sys_dir.is_dir():
        append_ignore(sys_dir, inner_rel, is_dir=False)


def unmark_inner_secret(
    cfg: TTConfig,
    store: SecretStore,
    config: str,
    dir_stored: str,
    inner_rel: str,
    scope: str,
    admin_key: Path | None = None,
    home: Path | None = None,
) -> None:
    """Reverse mark_inner_secret: decrypt in place, drop the mapping and the
    ignore rules, so the directory mirror manages the file again."""
    files_root = cfg.configs_dir / config / "files"
    dir_store = files_root / dir_stored
    store_path = dir_store / inner_rel
    dir_eff = _dir_effective_target(cfg, config, dir_stored)
    inner_target = f"{dir_eff}/{inner_rel}"
    if store_path.is_file() and is_ciphertext(store_path):
        store.decrypt_in_place(scope, store_path, admin_key=admin_key)
    cfg.remove_secret_mapping(config, f"{dir_stored}/{inner_rel}", inner_target)
    remove_ignore(dir_store, inner_rel, is_dir=False)
    sys_dir = (home or Path.home()) / dir_eff
    if sys_dir.is_dir():
        remove_ignore(sys_dir, inner_rel, is_dir=False)
