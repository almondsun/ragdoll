"""Private atomic writes that refuse symlink traversal."""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path


def ensure_no_symlink(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink():
            raise OSError(f"refusing to use symlinked path component: {current}")


def private_directory(path: Path, *, protect_existing: bool = False) -> None:
    ensure_no_symlink(path.parent)
    if path.is_symlink():
        raise OSError(f"refusing to use symlinked directory: {path}")
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if not existed or protect_existing:
            os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, content: bytes) -> None:
    private_directory(path.parent)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = f".{path.name}-{secrets.token_hex(12)}"
    descriptor = -1
    try:
        try:
            target = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(target.st_mode):
                raise OSError(f"refusing to replace symlinked file: {path}")
        except FileNotFoundError:
            pass
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent)
        raise
    finally:
        os.close(parent)
