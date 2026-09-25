"""Tests for per-machine secret scopes (age) and secrets.conf handling.

Skipped entirely when the `age` binary is unavailable, since the whole
feature is built on it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tui.core import secrets as S
from tui.core.config import TTConfig

pytestmark = pytest.mark.skipif(
    S.age_binary() is None, reason="age is not installed"
)


def _store(base: Path, machine_id: str) -> S.SecretStore:
    store = S.SecretStore(base, machine_id)
    store.init_personal_key()
    return store


def _scope_fixture(base: Path) -> S.SecretStore:
    store = _store(base, "hostA")
    store.ensure_admin_key()
    store.create_scope("common", ["hostA"])
    return store


def test_roundtrip_encrypt_decrypt(tmp_path: Path):
    store = _scope_fixture(tmp_path)
    src = tmp_path / "plain"
    src.write_text("TOPSECRET\n")
    cipher = tmp_path / "cipher.age"
    store.encrypt_to_scope("common", src, cipher)
    assert S.is_ciphertext(cipher)
    assert store.read_secret("common", cipher, ["hostA"]) == b"TOPSECRET\n"


def test_non_member_cannot_decrypt(tmp_path: Path):
    a = _scope_fixture(tmp_path)
    src = tmp_path / "plain"
    src.write_text("ONLY-A\n")
    cipher = tmp_path / "cipher.age"
    a.encrypt_to_scope("common", src, cipher)

    b = _store(tmp_path, "hostB")
    # hostB is registered but not a member of 'common' here and has no admin
    # key: it must not be able to unlock the scope. (The admin key would
    # legitimately open it, so it is removed — in reality it never lands on a
    # second machine.)
    a.admin_key_path.unlink()
    with pytest.raises(S.SecretsError):
        b.read_secret("common", cipher, ["hostA"])


def test_join_adds_member_existing_still_decrypt(tmp_path: Path):
    a = _scope_fixture(tmp_path)
    src = tmp_path / "plain"
    src.write_text("SHARED\n")
    cipher = tmp_path / "cipher.age"
    a.encrypt_to_scope("common", src, cipher)

    b = _store(tmp_path, "hostB")
    b.ensure_scope("common", ["hostA", "hostB"], admin_key=a.admin_key_path)
    assert b.read_secret("common", cipher, ["hostA", "hostB"]) == b"SHARED\n"
    assert a.read_secret("common", cipher, ["hostA", "hostB"]) == b"SHARED\n"


def test_ensure_scope_is_idempotent(tmp_path: Path):
    a = _scope_fixture(tmp_path)
    key_file = tmp_path / "secrets" / "scopes" / "common.key.age"
    before = key_file.read_bytes()
    a.ensure_scope("common", ["hostA"])
    # Same member set: the non-deterministic ciphertext must not be rewritten.
    assert key_file.read_bytes() == before


def test_ensure_scope_rewraps_on_new_member(tmp_path: Path):
    a = _scope_fixture(tmp_path)
    key_file = tmp_path / "secrets" / "scopes" / "common.key.age"
    before = key_file.read_bytes()
    b = _store(tmp_path, "hostB")
    a.ensure_scope("common", ["hostA", "hostB"])
    assert key_file.read_bytes() != before
    assert a.scope_members("common") == ["hostA", "hostB"]
    # b can now unlock without the admin key.
    src = tmp_path / "plain"
    src.write_text("X\n")
    cipher = tmp_path / "c.age"
    a.encrypt_to_scope("common", src, cipher)
    assert b.read_secret("common", cipher, []) == b"X\n"


def test_rotate_reencrypts_and_locks_out_old_member(tmp_path: Path):
    a = _scope_fixture(tmp_path)
    src = tmp_path / "plain"
    src.write_text("ROTATE-ME\n")
    secret = tmp_path / "secret.age"
    a.encrypt_to_scope("common", src, secret)

    b = _store(tmp_path, "hostB")
    a.ensure_scope("common", ["hostA", "hostB"])
    b.read_secret("common", secret, [])  # b is a member now

    # Drop the local admin key so the lockout assertion is about membership,
    # not about the recovery key (which by design opens every scope).
    a.admin_key_path.unlink()

    # Remove hostB and rotate: new key, file re-encrypted.
    a.rotate_scope("common", ["hostA"], [secret])
    assert a.read_secret("common", secret, []) == b"ROTATE-ME\n"
    with pytest.raises(S.SecretsError):
        b.read_secret("common", secret, [])
    assert a.scope_members("common") == ["hostA"]


def test_is_ciphertext(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.write_text("hello")
    assert not S.is_ciphertext(plain)
    store = _scope_fixture(tmp_path)
    cipher = tmp_path / "c"
    store.encrypt_to_scope("common", plain, cipher)
    assert S.is_ciphertext(cipher)


def test_generate_identity_refuses_overwrite(tmp_path: Path):
    key = tmp_path / "k.key"
    S.generate_identity(key)
    with pytest.raises(S.SecretsError):
        S.generate_identity(key)


# --- secrets.conf / config integration ----------------------------------


def _base_with_configs(tmp_path: Path) -> Path:
    base = tmp_path / "tt"
    for name in ("common", "hostA", "hostB"):
        (base / "configs" / name / "files").mkdir(parents=True)
    (base / "configs" / "hostA" / "includes.conf").write_text("")
    (base / "configs" / "hostB" / "includes.conf").write_text("")
    (base / "configs" / "common" / "files.conf").write_text("zshrc;.zshrc\n")
    return base


def test_get_secrets_default_scope(tmp_path: Path):
    base = _base_with_configs(tmp_path)
    (base / "configs" / "common" / "secrets.conf").write_text(
        "id_rsa;.ssh/id_rsa\n"
        "explicit;.token;hostA\n"
    )
    cfg = TTConfig(base)
    assert cfg.get_secrets("common") == [
        ("id_rsa", ".ssh/id_rsa", "common"),
        ("explicit", ".token", "hostA"),
    ]


def test_effective_secrets_last_wins(tmp_path: Path):
    base = _base_with_configs(tmp_path)
    (base / "configs" / "common" / "secrets.conf").write_text("tok;.token\n")
    (base / "configs" / "hostA" / "secrets.conf").write_text("tok2;.token\n")
    cfg = TTConfig(base)
    eff = {m.effective_target: m for m in cfg.get_effective_secrets("hostA")}
    assert eff[".token"].stored == "tok2"
    assert eff[".token"].config == "hostA"
    assert eff[".token"].scope == "hostA"


def test_add_remove_secret_mapping(tmp_path: Path):
    base = _base_with_configs(tmp_path)
    cfg = TTConfig(base)
    cfg.add_secret_mapping("hostA", "id_ed", ".ssh/id_ed25519", "common")
    assert (base / "configs" / "hostA" / "secrets.conf").read_text() == (
        "id_ed;.ssh/id_ed25519;common\n"
    )
    # Same-scope entry stays implicit (two fields).
    cfg.add_secret_mapping("hostA", "tok", ".token", "hostA")
    assert "tok;.token\n" in (base / "configs" / "hostA" / "secrets.conf").read_text()
    cfg.remove_secret_mapping("hostA", "id_ed", ".ssh/id_ed25519")
    assert "id_ed" not in (base / "configs" / "hostA" / "secrets.conf").read_text()


# --- scope policy (secret_ops) ------------------------------------------


def test_members_for_derives_from_include_chain(tmp_path: Path):
    from tui.core.secret_ops import members_for

    base = _base_with_configs(tmp_path)
    (base / "configs" / "common_mac" / "files").mkdir(parents=True)
    (base / "configs" / "common_mac" / "includes.conf").write_text("")
    (base / "configs" / "hostA" / "includes.conf").write_text("common_mac\n")
    store = _store(base, "hostA")
    _store(base, "hostB")  # registered, plain common only

    assert members_for(TTConfig(base), store, "common") == ["hostA", "hostB"]
    assert members_for(TTConfig(base), store, "common_mac") == ["hostA"]
    assert members_for(TTConfig(base), store, "hostA") == ["hostA"]


def test_migrate_entry_encrypts_and_moves_mapping(tmp_path: Path):
    from tui.core.secret_ops import migrate_entry

    base = _base_with_configs(tmp_path)
    store = _store(base, "hostA")
    store.ensure_admin_key()
    (base / "configs" / "common" / "files.conf").write_text("id;.ssh/id\n")
    target = base / "configs" / "common" / "files" / "id"
    target.write_text("KEY\n")

    migrate_entry(TTConfig(base), store, "hostA", "common", "id", ".ssh/id", "common")
    assert S.is_ciphertext(target)
    assert TTConfig(base).get_secrets("common") == [("id", ".ssh/id", "common")]
    assert "id;.ssh/id" not in (base / "configs" / "common" / "files.conf").read_text()



def test_mark_and_unmark_inner_secret(tmp_path: Path):
    """A file inside a tracked directory can be carved out: ciphertext in the
    store, an anchored .ttignore rule on both sides, and its own secret
    entry. Unmarking reverses all of it."""
    from tui.core.secret_ops import mark_inner_secret, unmark_inner_secret

    base = _base_with_configs(tmp_path)
    store = _store(base, "hostA")
    store.ensure_admin_key()
    (base / "configs" / "common" / "files.conf").write_text("app;.config/app\n")
    store_dir = base / "configs" / "common" / "files" / "app"
    store_dir.mkdir(parents=True)
    (store_dir / "public.txt").write_text("public\n")
    (store_dir / "secret.json").write_text("KEY=sekret\n")

    home = tmp_path / "home"
    sys_dir = home / ".config" / "app"
    sys_dir.mkdir(parents=True)
    (sys_dir / "public.txt").write_text("public\n")
    (sys_dir / "secret.json").write_text("KEY=sekret\n")

    cfg = TTConfig(base)
    mark_inner_secret(
        cfg, store, "hostA", "common", "app", "secret.json", "common",
        home=home,
    )

    assert S.is_ciphertext(store_dir / "secret.json")
    assert not S.is_ciphertext(store_dir / "public.txt")
    assert cfg.get_secrets("common") == [
        ("app/secret.json", ".config/app/secret.json", "common")
    ]
    assert (store_dir / ".ttignore").read_text().strip() == "/secret.json"
    assert (sys_dir / ".ttignore").read_text().strip() == "/secret.json"
    assert cfg.is_secret("common", "app/secret.json", ".config/app/secret.json")

    unmark_inner_secret(cfg, store, "common", "app", "secret.json", "common", home=home)
    assert (store_dir / "secret.json").read_text() == "KEY=sekret\n"
    assert cfg.get_secrets("common") == []
    assert (store_dir / ".ttignore").read_text() == ""
    assert (sys_dir / ".ttignore").read_text() == ""
