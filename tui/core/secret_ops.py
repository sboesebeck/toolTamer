"""Scope policy and migration helpers for secrets.

`tui.core.secrets` is the pure crypto layer; this module adds the pieces
that need the config hierarchy and are shared by the CLI (`tui.secrets`)
and the TUI: who is a member of a scope, how a machine joins, and how a
single plaintext entry becomes an encrypted one.
"""

from __future__ import annotations

from pathlib import Path

from tui.core.config import TTConfig
from tui.core.secrets import SecretStore, SecretsError


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
