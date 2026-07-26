"""
Decides which files are even candidates for auto-naming, and performs the
actual rename safely: collision-checked (never silently overwrites), logged
(every rename is recorded so it's traceable/reversible), and tolerant of
files that are currently open in another program (relies on the OS's own
file lock rather than trying to reimplement lock detection -- Windows raises
PermissionError renaming an open .docx, which is treated as "skip", not a
crash).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Matches the default names Word/Office (and common "New Document" patterns)
# actually produce: "Document1.docx", "doc1.docx", "New Microsoft Word Document.docx",
# "Untitled.docx", "Document (1).docx", etc. Deliberately conservative -- a file
# that doesn't match one of these is assumed to already have a name the user
# chose on purpose, and is left alone unless the caller opts into renaming
# everything.
_GENERIC_NAME_RE = re.compile(
    r"^(?:"
    r"doc(?:ument)?\s*\(?\d*\)?"          # doc1, document1, doc (2), Document (3)
    r"|new\s+microsoft\s+word\s+document(?:\s*\(?\d*\)?)?"
    r"|untitled(?:\s*document)?(?:\s*\(?\d*\)?)?"
    r")$",
    re.IGNORECASE,
)


def is_generically_named(filename_stem: str) -> bool:
    return bool(_GENERIC_NAME_RE.match(filename_stem.strip()))


@dataclass
class RenameResult:
    original_path: Path
    new_path: Optional[Path]
    status: str  # "renamed" | "skipped_not_generic" | "skipped_locked" | "skipped_collision_unresolved" | "error"
    detail: str = ""


def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """Never returns a path that already exists -- appends -2, -3, ... instead
    of silently overwriting an existing file with the same generated name."""
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = directory / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _append_log(log_path: Path, entry: dict):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    if log_path.exists():
        try:
            entries = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(f"Rename log at {log_path} was unreadable; starting a fresh one.")
            entries = []
    entries.append(entry)
    log_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def safe_rename(path: Path, new_stem: str, log_path: Path, only_if_generic: bool = True) -> RenameResult:
    if only_if_generic and not is_generically_named(path.stem):
        return RenameResult(path, None, "skipped_not_generic", f"'{path.stem}' doesn't look auto-generated")

    new_stem = new_stem.strip()
    if not new_stem:
        return RenameResult(path, None, "error", "generated name was empty after sanitizing")

    target = _unique_path(path.parent, new_stem, path.suffix)

    try:
        path.rename(target)
    except PermissionError as e:
        return RenameResult(path, None, "skipped_locked", f"file appears to be open elsewhere: {e}")
    except OSError as e:
        return RenameResult(path, None, "error", str(e))

    _append_log(log_path, {
        "old_path": str(path),
        "new_path": str(target),
        "timestamp": datetime.now().isoformat(),
    })

    return RenameResult(path, target, "renamed")
