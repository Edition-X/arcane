"""Portable vault paths, including absolute paths written by older releases."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


def vault_path(home: str, stored_path: str) -> Path:
    """Resolve a stored path inside this home's vault, never an old source vault.

    Legacy databases stored absolute paths. The suffix after ``vault`` is
    portable across restores and operating systems; everything else is rejected.
    Resolution also rejects symlinks which escape the current vault.
    """
    root = (Path(home).resolve() / "vault").resolve()
    portable = PurePosixPath(stored_path.replace("\\", "/"))
    if portable.is_absolute() or PureWindowsPath(stored_path).is_absolute():
        parts = portable.parts
        if "vault" not in parts:
            raise ValueError("Memory path does not identify a vault file")
        portable = PurePosixPath(*parts[parts.index("vault") + 1 :])
    elif portable.parts and portable.parts[0] == "vault":
        portable = PurePosixPath(*portable.parts[1:])
    else:
        raise ValueError("Memory path must be relative to the vault")
    candidate = root.joinpath(*portable.parts).resolve()
    if not candidate.is_relative_to(root) or candidate == root or candidate.suffix != ".md":
        raise ValueError("Memory path escapes the vault or is not a Markdown file")
    return candidate


def relative_vault_path(home: str, path: Path) -> str:
    """Return the portable home-relative form after checking containment."""
    checked = vault_path(home, str(path))
    return (PurePosixPath("vault") / checked.relative_to((Path(home).resolve() / "vault").resolve())).as_posix()
