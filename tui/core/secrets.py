"""Per-machine secret encryption with age and per-scope keys.

The ToolTamer store is one git repository that every machine clones in
full. Anything committed to it — including `configs/<host>/files/` — is
therefore present on every machine, in the working tree *and* in `.git`.
Storing secrets there in plaintext hands every machine every other
machine's ssh keys and tokens.

This module keeps secrets as ciphertext in the shared repo and gives the
plaintext only to entitled machines:

- Every machine has a **personal** age keypair. The private key lives
  locally (`keys/<machine-id>.key`, gitignored) and never leaves it.
- Secrets are encrypted to a **scope**, which is a config name (`common`,
  `common_mac`, `<host>`, ...). Each scope owns an age keypair: its public
  key sits in the repo, its private key is stored wrapped to the scope's
  members (plus the admin key) in `secrets/scopes/<scope>.key.age`.
- A secret file is encrypted directly to its scope's public key. Adding a
  member only re-wraps the small scope private key — the secret files are
  untouched.

Membership is *derived*, not stored: a registered machine belongs to every
scope named anywhere in its include chain (see the CLI layer, which knows
the config hierarchy). The admin/recovery key is always an extra recipient
of every scope, so a new machine can bootstrap with it and a lost machine
can be locked out by rotating.

No private key is ever copied between machines — only public keys travel
through the repo. See the design doc
`docs/superpowers/specs/2026-09-25-secrets-scopes-design.md`.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

AGE_BINARY_HEADER = b"age-encryption.org/v1"
AGE_ARMOR_HEADER = b"-----BEGIN AGE ENCRYPTED FILE-----"
AGE_PUBKEY_PREFIX = "age1"


class SecretsError(RuntimeError):
    """A secret operation could not be completed (missing age, bad key,
    undecryptable file, ...). Callers surface the message to the user."""


def age_binary() -> str | None:
    """Path to the `age` binary, or None when it is not installed."""
    return shutil.which("age")


def require_age() -> str:
    exe = age_binary()
    if exe is None:
        raise SecretsError(
            "age is not installed — install it (brew install age / apt install age)"
        )
    return exe


def _keygen_binary() -> str:
    exe = shutil.which("age-keygen")
    if exe is None:
        raise SecretsError(
            "age-keygen is not installed — it ships with age; check your installation"
        )
    return exe


def _run(args: list[str], input_bytes: bytes | None = None) -> tuple[int, bytes, bytes]:
    try:
        proc = subprocess.run(args, input=input_bytes, capture_output=True)
    except (FileNotFoundError, OSError) as exc:
        return 127, b"", str(exc).encode()
    return proc.returncode, proc.stdout, proc.stderr


def is_ciphertext(path: Path) -> bool:
    """True when `path` starts with an age header (binary or armored).

    Used as the plaintext-leak guard: a `secrets.conf` entry whose store
    file is not ciphertext means something wrote plaintext into the repo.
    """
    try:
        with path.open("rb") as f:
            head = f.read(len(AGE_ARMOR_HEADER))
    except OSError:
        return False
    return head.startswith(AGE_BINARY_HEADER) or head.startswith(AGE_ARMOR_HEADER)


def generate_identity(path: Path) -> str:
    """Write a fresh age identity to `path` (mode 0600) and return its
    public key. Fails when the file already exists, so a mis-click can
    never overwrite a key that still guards committed ciphertext."""
    path = Path(path)
    if path.exists():
        raise SecretsError(f"refusing to overwrite existing key {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    rc, _out, err = _run([_keygen_binary(), "-o", str(path)])
    if rc != 0:
        raise SecretsError(f"age-keygen failed: {err.decode(errors='replace').strip()}")
    os.chmod(path, 0o600)
    return public_from_identity(path)


def public_from_identity(path: Path) -> str:
    """The public key belonging to the identity at `path`."""
    rc, out, err = _run([_keygen_binary(), "-y", str(path)])
    if rc != 0 or not out:
        raise SecretsError(
            f"cannot read public key from {path}: {err.decode(errors='replace').strip()}"
        )
    pub = out.decode().strip().splitlines()[-1].strip()
    if not pub.startswith(AGE_PUBKEY_PREFIX):
        raise SecretsError(f"{path} does not look like an age identity")
    return pub


def encrypt_file(recipients: list[str], src: Path, dest: Path) -> None:
    """Encrypt `src` to every key in `recipients`, writing `dest`.

    Handles `src == dest` (the migrate/rotate in-place case) by encrypting
    to a sibling temp file and replacing atomically: age refuses to read
    and write the same file."""
    if not recipients:
        raise SecretsError("no recipients — refusing to encrypt to nobody")
    exe = require_age()
    src = Path(src)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    in_place = src.exists() and dest.exists() and src.resolve() == dest.resolve()
    target = dest
    tmp: Path | None = None
    if in_place:
        import tempfile as _tempfile

        fd, name = _tempfile.mkstemp(dir=str(dest.parent), prefix=".ttenc-")
        os.close(fd)
        tmp = Path(name)
        target = tmp
    args = [exe]
    for r in recipients:
        args += ["-r", r]
    args += ["-o", str(target), str(src)]
    rc, _out, err = _run(args)
    if rc != 0:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        raise SecretsError(f"age encryption failed: {err.decode(errors='replace').strip()}")
    if tmp is not None:
        os.replace(tmp, dest)



def decrypt_file(identity: Path, src: Path, dest: Path) -> None:
    """Decrypt `src` with `identity`, writing `dest`.

    Handles `src == dest` (decrypt-in-place) via a sibling temp file: age
    refuses to read and write the same file."""
    exe = require_age()
    src = Path(src)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    in_place = src.exists() and dest.exists() and src.resolve() == dest.resolve()
    target = dest
    tmp: Path | None = None
    if in_place:
        import tempfile as _tempfile

        fd, name = _tempfile.mkstemp(dir=str(dest.parent), prefix=".ttdec-")
        os.close(fd)
        tmp = Path(name)
        target = tmp
    args = [exe, "-d", "-i", str(identity), "-o", str(target), str(src)]
    rc, _out, err = _run(args)
    if rc != 0:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        raise SecretsError(f"age decryption failed: {err.decode(errors='replace').strip()}")
    if tmp is not None:
        os.replace(tmp, dest)


def decrypt_bytes(identity: Path, src: Path) -> bytes:
    """Decrypt `src` in memory with `identity`."""
    exe = require_age()
    rc, out, err = _run([exe, "-d", "-i", str(identity), str(src)])
    if rc != 0:
        raise SecretsError(f"age decryption failed: {err.decode(errors='replace').strip()}")
    return out


def encrypt_bytes(recipients: list[str], data: bytes) -> bytes:
    """Encrypt `data` in memory to `recipients`."""
    if not recipients:
        raise SecretsError("no recipients — refusing to encrypt to nobody")
    exe = require_age()
    args = [exe]
    for r in recipients:
        args += ["-r", r]
    rc, out, err = _run(args, input_bytes=data)
    if rc != 0:
        raise SecretsError(f"age encryption failed: {err.decode(errors='replace').strip()}")
    return out


@dataclass
class ScopeInfo:
    name: str
    public_key: str | None
    has_key: bool


class SecretStore:
    """Key material and scope keys under a ToolTamer base directory.

    Pure key/crypto layer — it knows nothing about the config hierarchy.
    Membership lists arrive from the caller (the CLI derives them from the
    include chain); every recipient is resolved through `recipients/`."""

    def __init__(self, base: Path, machine_id: str):
        self.base = Path(base)
        self.machine_id = machine_id
        self.secrets_dir = self.base / "secrets"
        self.recipients_dir = self.secrets_dir / "recipients"
        self.scopes_dir = self.secrets_dir / "scopes"
        self.admin_pub_path = self.secrets_dir / "admin.pub"
        self.keys_dir = self.base / "keys"
        self.personal_key_path = self.keys_dir / f"{machine_id}.key"
        self.personal_pub_path = self.keys_dir / f"{machine_id}.pub"
        self.admin_key_path = self.keys_dir / "admin.key"

    # --- personal key ---------------------------------------------------

    def has_personal_key(self) -> bool:
        return self.personal_key_path.is_file()

    def personal_public_key(self) -> str:
        if not self.has_personal_key():
            raise SecretsError(
                f"no personal key for {self.machine_id} — run 'tt secrets init' first"
            )
        if self.personal_pub_path.is_file():
            pub = self.personal_pub_path.read_text().strip()
            if pub:
                return pub
        pub = public_from_identity(self.personal_key_path)
        self.personal_pub_path.write_text(pub + "\n")
        return pub

    def init_personal_key(self) -> str:
        """Create the personal keypair if missing and register the public
        key in the repo. Idempotent. Returns the public key."""
        if not self.has_personal_key():
            pub = generate_identity(self.personal_key_path)
            self.personal_pub_path.write_text(pub + "\n")
        pub = self.personal_public_key()
        self.recipients_dir.mkdir(parents=True, exist_ok=True)
        (self.recipients_dir / f"{self.machine_id}.pub").write_text(pub + "\n")
        self.ensure_gitignored()
        return pub

    def ensure_gitignored(self) -> None:
        """Add `keys/` to the store's .gitignore, like machine-id. The private
        keys are machine-local and must never be committed."""
        if not (self.base / ".git").exists():
            return
        gitignore = self.base / ".gitignore"
        existing = gitignore.read_text() if gitignore.exists() else ""
        if "keys/" in existing.splitlines():
            return
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with gitignore.open("a") as fh:
            fh.write(
                f"{prefix}# Secret private keys (machine-local, never shared)\n"
                f"keys/\n"
            )

    # --- admin / recovery key ------------------------------------------

    def admin_public_key(self) -> str | None:
        if not self.admin_pub_path.is_file():
            return None
        pub = self.admin_pub_path.read_text().strip()
        return pub or None

    def ensure_admin_key(self) -> tuple[str, bool]:
        """Ensure an admin public key exists. Returns (pubkey, created).

        The private key is written to `keys/admin.key` (local, gitignored)
        so `join` can use it without a paste; it is the *recovery* key and
        should be stored in a password manager."""
        existing = self.admin_public_key()
        if existing:
            return existing, False
        pub = generate_identity(self.admin_key_path)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.admin_pub_path.write_text(pub + "\n")
        return pub, True

    def find_admin_key(self, override: Path | None = None) -> Path | None:
        if override is not None:
            return override if override.is_file() else None
        return self.admin_key_path if self.admin_key_path.is_file() else None

    # --- recipient registry --------------------------------------------

    def recipient_public_key(self, machine_id: str) -> str | None:
        p = self.recipients_dir / f"{machine_id}.pub"
        if not p.is_file():
            return None
        pub = p.read_text().strip()
        return pub or None

    def registered_machines(self) -> list[str]:
        if not self.recipients_dir.is_dir():
            return []
        return sorted(
            p.stem for p in self.recipients_dir.glob("*.pub") if p.is_file()
        )

    # --- scope keys -----------------------------------------------------

    def scope_public_key(self, scope: str) -> str | None:
        p = self.scopes_dir / f"{scope}.pub"
        if not p.is_file():
            return None
        pub = p.read_text().strip()
        return pub or None

    def has_scope_key(self, scope: str) -> bool:
        return (self.scopes_dir / f"{scope}.key.age").is_file()

    def list_scopes(self) -> list[str]:
        if not self.scopes_dir.is_dir():
            return []
        return sorted(
            p.name[: -len(".pub")] for p in self.scopes_dir.glob("*.pub") if p.is_file()
        )

    def scope_members(self, scope: str) -> list[str] | None:
        """The machine ids recorded as members of `scope`, or None when the
        file is absent. The file is a cache of the last wrap, not the source
        of truth — membership is derived from the include chain — and exists
        so `ensure_scope` can skip a needless (non-deterministic) re-wrap."""
        p = self.scopes_dir / f"{scope}.members"
        if not p.is_file():
            return None
        return [ln.strip() for ln in p.read_text().splitlines() if ln.strip()]

    def _write_scope_members(self, scope: str, member_ids: list[str]) -> None:
        self.scopes_dir.mkdir(parents=True, exist_ok=True)
        (self.scopes_dir / f"{scope}.members").write_text(
            "".join(f"{m}\n" for m in sorted(set(member_ids)))
        )

    def included_members(self, member_ids: list[str]) -> list[str]:
        """The subset of `member_ids` that have a registered public key."""
        return [m for m in member_ids if self.recipient_public_key(m) is not None]

    def _recipients_for(self, member_ids: list[str]) -> list[str]:
        """Public keys of the registered `member_ids` plus the admin key."""
        recipients: list[str] = []
        for mid in self.included_members(member_ids):
            pub = self.recipient_public_key(mid)
            if pub and pub not in recipients:
                recipients.append(pub)
        admin = self.admin_public_key()
        if admin and admin not in recipients:
            recipients.append(admin)
        return recipients

    def _write_scope_public(self, scope: str, pub: str) -> None:
        self.scopes_dir.mkdir(parents=True, exist_ok=True)
        (self.scopes_dir / f"{scope}.pub").write_text(pub + "\n")

    def wrap_scope_key(self, scope: str, identity_path: Path, member_ids: list[str]) -> None:
        """(Re-)wrap the scope private key at `identity_path` to the members
        plus admin. Overwrites `scopes/<scope>.key.age` and records the
        members it was wrapped to."""
        recipients = self._recipients_for(member_ids)
        if not recipients:
            raise SecretsError(
                f"scope '{scope}' has no recipients (no registered machine, no admin key)"
            )
        self.scopes_dir.mkdir(parents=True, exist_ok=True)
        encrypt_file(recipients, identity_path, self.scopes_dir / f"{scope}.key.age")
        self._write_scope_members(scope, self.included_members(member_ids))

    def create_scope(self, scope: str, member_ids: list[str]) -> str:
        """Create a new scope keypair wrapped to `member_ids` + admin.
        Returns the scope public key."""
        with tempfile.TemporaryDirectory() as td:
            identity = Path(td) / f"{scope}.key"
            pub = generate_identity(identity)
            self._write_scope_public(scope, pub)
            self.wrap_scope_key(scope, identity, member_ids)
        return pub

    def _unwrap_scope_key(self, scope: str, identities: list[Path]) -> Path:
        """Decrypt `scopes/<scope>.key.age` with the first working identity.
        Returns a path inside a new temp dir the caller owns (use
        `_scope_identity` for the managed variant)."""
        wrapped = self.scopes_dir / f"{scope}.key.age"
        if not wrapped.is_file():
            raise SecretsError(f"scope '{scope}' has no key in the store")
        last_err = "no usable identity"
        for ident in identities:
            if ident is None or not Path(ident).is_file():
                continue
            td = tempfile.mkdtemp(prefix="tt-scope-")
            out = Path(td) / f"{scope}.key"
            try:
                decrypt_file(Path(ident), wrapped, out)
                return out
            except SecretsError as exc:
                last_err = str(exc)
                shutil.rmtree(td, ignore_errors=True)
        raise SecretsError(
            f"cannot unlock scope '{scope}' — not a member and no admin key ({last_err})"
        )

    def scope_identity_candidates(
        self, scope: str, member_ids: list[str], admin_key: Path | None = None
    ) -> list[Path]:
        """Identities that may unlock the scope key, in preference order:
        the personal key when this machine is a member, then the admin key."""
        candidates: list[Path] = []
        personal_pub = None
        if self.has_personal_key():
            try:
                personal_pub = self.personal_public_key()
            except SecretsError:
                personal_pub = None
        member_pubs = [self.recipient_public_key(m) for m in member_ids]
        if personal_pub and personal_pub in member_pubs:
            candidates.append(self.personal_key_path)
        if admin_key is not None:
            candidates.append(admin_key)
        # Even when membership was not obvious (e.g. a recipient file the
        # caller did not list), trying the personal key is free and safe.
        if personal_pub and self.personal_key_path not in candidates:
            candidates.append(self.personal_key_path)
        return candidates

    def ensure_scope(
        self, scope: str, member_ids: list[str], admin_key: Path | None = None
    ) -> str:
        """Make sure scope `scope` can be decrypted by `member_ids` + admin.

        Creates the keypair when missing; otherwise re-wraps it when the
        recorded member set differs from `member_ids`. The ciphertext is
        non-deterministic, so the member cache is what keeps a repeated
        `join`/sync from producing a spurious git diff. Returns the scope
        public key."""
        desired = sorted(set(self.included_members(member_ids)))
        if self.has_scope_key(scope) and self.scope_members(scope) == desired:
            pub = self.scope_public_key(scope)
            if pub is not None:
                return pub
        admin = self.find_admin_key(admin_key)
        if not self.has_scope_key(scope):
            return self.create_scope(scope, member_ids)
        candidates = self.scope_identity_candidates(scope, member_ids, admin)
        with tempfile.TemporaryDirectory() as td:
            identity = self._unwrap_scope_key(scope, candidates)
            try:
                self.wrap_scope_key(scope, identity, member_ids)
            finally:
                shutil.rmtree(identity.parent, ignore_errors=True)
        pub = self.scope_public_key(scope)
        if pub is None:
            raise SecretsError(f"scope '{scope}' lost its public key")
        return pub

    def rotate_scope(
        self,
        scope: str,
        member_ids: list[str],
        secret_files: list[Path],
        admin_key: Path | None = None,
    ) -> int:
        """Issue a fresh scope key and re-encrypt every `secret_files` entry
        to it. Use after a member leaves or a key is lost. Returns the number
        of files re-encrypted."""
        if not secret_files:
            raise SecretsError(f"scope '{scope}' has no files to rotate")
        admin = self.find_admin_key(admin_key)
        candidates = self.scope_identity_candidates(scope, member_ids, admin)
        with tempfile.TemporaryDirectory() as td:
            old_identity = self._unwrap_scope_key(scope, candidates)
            plaintexts: list[tuple[Path, bytes]] = []
            for f in secret_files:
                if not f.is_file():
                    continue
                plaintexts.append((f, decrypt_bytes(old_identity, f)))
            shutil.rmtree(old_identity.parent, ignore_errors=True)
            identity = Path(td) / f"{scope}.key"
            pub = generate_identity(identity)
            self._write_scope_public(scope, pub)
            self.wrap_scope_key(scope, identity, member_ids)
            for f, data in plaintexts:
                f.write_bytes(encrypt_bytes([pub], data))
        return len(plaintexts)

    # --- encrypt / decrypt a secret file -------------------------------

    def encrypt_to_scope(self, scope: str, src: Path, dest: Path) -> None:
        """Encrypt `src` to the scope's public key, writing `dest`."""
        pub = self.scope_public_key(scope)
        if pub is None:
            raise SecretsError(f"scope '{scope}' does not exist in this store")
        encrypt_file([pub], src, dest)

    def decrypt_from_scope(
        self,
        scope: str,
        src: Path,
        dest: Path,
        member_ids: list[str] | None = None,
        admin_key: Path | None = None,
    ) -> None:
        """Decrypt the scope-encrypted `src` into `dest`."""
        admin = self.find_admin_key(admin_key)
        candidates = self.scope_identity_candidates(scope, member_ids or [], admin)
        with tempfile.TemporaryDirectory() as td:
            identity = self._unwrap_scope_key(scope, candidates)
            try:
                decrypt_file(identity, src, dest)
            finally:
                shutil.rmtree(identity.parent, ignore_errors=True)

    def decrypt_in_place(
        self,
        scope: str,
        path: Path,
        member_ids: list[str] | None = None,
        admin_key: Path | None = None,
    ) -> None:
        """Decrypt the scope-encrypted `path` back to plaintext in place."""
        admin = self.find_admin_key(admin_key)
        candidates = self.scope_identity_candidates(scope, member_ids or [], admin)
        with tempfile.TemporaryDirectory() as td:
            identity = self._unwrap_scope_key(scope, candidates)
            try:
                decrypt_file(identity, path, path)
            finally:
                shutil.rmtree(identity.parent, ignore_errors=True)

    def read_secret(
        self,
        scope: str,
        src: Path,
        member_ids: list[str] | None = None,
        admin_key: Path | None = None,
    ) -> bytes:
        """Decrypt the scope-encrypted `src` and return the plaintext."""
        admin = self.find_admin_key(admin_key)
        candidates = self.scope_identity_candidates(scope, member_ids or [], admin)
        with tempfile.TemporaryDirectory() as td:
            identity = self._unwrap_scope_key(scope, candidates)
            try:
                return decrypt_bytes(identity, src)
            finally:
                shutil.rmtree(identity.parent, ignore_errors=True)


def secret_file_status(
    store: "SecretStore", scope: str, store_path: Path, system_path: Path
) -> str:
    """ok | modified | missing_system | missing_repo for one secret file.

    Compares the *decrypted* plaintext with the system file; age output is
    non-deterministic, so a ciphertext comparison would always differ. Shared
    by the file manager and the dashboard so both agree."""
    if not store_path.exists():
        return "missing_repo"
    if not system_path.exists():
        return "missing_system"
    try:
        data = store.read_secret(scope, store_path)
    except SecretsError:
        # No key yet / undecryptable: surface as missing rather than claiming
        # a sync we cannot verify.
        return "missing_repo"
    if hashlib.sha1(data).hexdigest() == hashlib.sha1(system_path.read_bytes()).hexdigest():
        return "ok"
    return "modified"
