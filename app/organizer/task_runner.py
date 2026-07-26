"""
Runs an organizer job (rename generically-named .docx files in a folder based
on their content) as a trackable task -- same add_log/add_action/
update_task_status calls the browser executor uses, so an organizer run shows
up in the dashboard's History/timeline exactly like a browser task does,
instead of being a silent side-effect only visible via the CLI script's
stdout.

Deliberately synchronous (unlike app/executor/executor.py's async loop) --
this is local file I/O, not network/browser work waiting on I/O concurrently
with anything else. routes.py runs it in its own background thread, same as
the browser path.

Folder resolution is intentionally conservative: an explicit path in the
prompt, or one of a small set of common folder aliases (Downloads, Documents,
Desktop). If neither is found, the task fails clearly with a message telling
the user to name a folder -- it does NOT guess (e.g. defaulting to the whole
home directory), since that's exactly the kind of surprising, hard-to-reverse
mistake safe_rename()'s design elsewhere in this module is built to avoid.

Routed-as-organizer tasks apply renames immediately -- they don't do the CLI
script's separate dry-run-first step, since arriving here already required
the user to say something like "rename the doc1 files in Downloads," which is
itself the explicit go-ahead. Two cases:

1. The prompt names one specific file (e.g. "rename bul.docx based on its
   content", or a full path to a .docx file). Naming the exact file IS the
   explicit go-ahead for that file -- it's renamed regardless of whether its
   current name looks auto-generated, since the user pointed at it directly
   rather than asking the agent to scan a folder and guess which files are
   safe to touch.
2. The prompt names a folder but not a specific file (e.g. "rename the doc1
   files in Downloads"). This scans that folder and only renames files that
   look auto-generated (doc1.docx, Untitled.docx, etc.) -- same as the CLI
   script's default (non---all) behavior, since here the agent IS the one
   choosing which files to touch, not the user.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.organizer.extractor import extract_docx, ExtractionError
from app.organizer.namer import generate_name
from app.organizer.renamer import safe_rename, is_generically_named
from app.database import add_log, add_action, update_task_status
from app.config import ROOT_DIR

DEFAULT_LOG_PATH = ROOT_DIR / "logs" / "organizer_renames.json"

# Maps a spoken alias to the actual Windows folder name -- resolved against
# multiple candidate root directories at call time (see _onedrive_roots),
# not baked in as a fixed path at import time.
FOLDER_ALIASES = {
    "downloads": "Downloads",
    "documents": "Documents",
    "my documents": "Documents",
    "desktop": "Desktop",
}

# Matches a Windows drive-letter path (C:\Users\...) or a quoted/unquoted
# Unix-style absolute path -- deliberately not matching relative paths, since
# a relative path from a prompt has no reliable "relative to what" answer.
_EXPLICIT_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"']+|/[^\s\"']+)"
)

# Matches a bare filename token ending in .docx (e.g. "bul.docx") -- requires
# a token boundary before it (not preceded by another non-space character) so
# it grabs just the filename, not a run-on chunk of the surrounding sentence.
_EXPLICIT_FILENAME_RE = re.compile(r'(?<!\S)([^\s"\']+\.docx)', re.IGNORECASE)


class FolderResolutionError(Exception):
    pass


def _onedrive_roots() -> list[Path]:
    """OneDrive's "Backup"/"Known Folder Move" feature silently redirects
    Desktop, Documents, and Pictures to live under the OneDrive folder
    instead of directly under the user's home directory -- so
    Path.home() / "Desktop" can be missing even though the user has a real,
    populated Desktop folder; it's just not where Windows normally puts it.
    Try the plain home directory first, then any OneDrive-ish folder under it
    (personal "OneDrive", or a work/school "OneDrive - <Org>")."""
    home = Path.home()
    roots = [home]
    try:
        roots.extend(sorted(p for p in home.glob("OneDrive*") if p.is_dir()))
    except OSError:
        pass
    return roots


def resolve_folder(prompt: str) -> Path:
    """Raises FolderResolutionError rather than guessing when no folder is
    identifiable in the prompt."""
    match = _EXPLICIT_PATH_RE.search(prompt or "")
    if match:
        candidate = Path(match.group(0).rstrip(".,;:'\""))
        if candidate.is_dir():
            return candidate
        raise FolderResolutionError(f"'{candidate}' looks like a path but isn't a folder I can find.")

    text = (prompt or "").lower()
    for alias, folder_name in FOLDER_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", text):
            tried = []
            for root in _onedrive_roots():
                candidate = root / folder_name
                tried.append(candidate)
                if candidate.is_dir():
                    return candidate
            tried_str = ", ".join(str(p) for p in tried)
            raise FolderResolutionError(
                f"Could not find your {folder_name} folder. Checked: {tried_str}. "
                f"If it's somewhere else, try naming the full path instead."
            )

    raise FolderResolutionError(
        "I couldn't tell which folder to organize. Try naming one explicitly "
        "(e.g. 'rename the doc1 files in Downloads' or a full path)."
    )


def _extract_explicit_docx_target(prompt: str) -> Path | None:
    """If the prompt gives a full/absolute path to a specific .docx file
    (e.g. 'C:\\Users\\reddy\\Desktop\\bul.docx'), returns that resolved Path.
    This has to be checked before resolve_folder() -- otherwise
    _EXPLICIT_PATH_RE would match the same text and resolve_folder would
    reject it with "looks like a path but isn't a folder", since a full file
    path isn't a directory."""
    match = _EXPLICIT_PATH_RE.search(prompt or "")
    if not match:
        return None
    candidate = Path(match.group(0).rstrip(".,;:'\""))
    if candidate.suffix.lower() == ".docx":
        return candidate
    return None


def _extract_explicit_filename(prompt: str) -> str | None:
    """If the prompt names a specific file by its bare filename (e.g. 'rename
    bul.docx based on its content'), returns that filename. Only called after
    _extract_explicit_docx_target() finds nothing, so this only fires for a
    bare name, not a full path."""
    match = _EXPLICIT_FILENAME_RE.search(prompt or "")
    return match.group(1) if match else None


def _log_if_fallback_name(task_id: str, target: Path, content, new_stem: str):
    """generate_name() falls back to a timestamped placeholder silently when
    it found no title metadata, no headings, and neither the local LLM nor
    keyword extraction could produce anything from the body text -- which
    otherwise shows up in the dashboard as "renamed, but not based on the
    content" with no explanation. Surface why, so the next time this happens
    it's diagnosable from the task log instead of a guessing game. (If only
    the LLM step failed -- e.g. Ollama isn't running -- that's already logged
    separately as a warning by app.organizer.namer at the point it happened.)"""
    if new_stem.startswith("Untitled Document"):
        add_log(
            task_id,
            f"Could not find a title, heading, or usable content to name "
            f"{target.name} from (title metadata: {'yes' if content.title_metadata else 'no'}, "
            f"headings found: {len(content.headings)}, body text extracted: "
            f"{len(content.body_text)} characters) -- used a timestamped "
            f"placeholder name instead of one based on content.",
            "warning",
        )


def _rename_single_file(task_id: str, target: Path):
    """Renames one explicitly-named file based on its content, regardless of
    whether its current name looks auto-generated -- naming the exact file is
    itself the user's go-ahead, unlike the folder-scan path below."""
    if not target.is_file():
        summary = f"Could not find '{target.name}' in {target.parent}."
        add_log(task_id, summary, "error")
        update_task_status(task_id, "failed", error=summary)
        return

    try:
        content = extract_docx(target)
    except ExtractionError as e:
        err = f"Could not read {target.name}: {e}"
        add_log(task_id, err, "error")
        update_task_status(task_id, "failed", error=err)
        return

    new_stem = generate_name(content)
    _log_if_fallback_name(task_id, target, content, new_stem)
    result = safe_rename(target, new_stem, DEFAULT_LOG_PATH, only_if_generic=False)

    if result.status == "renamed":
        desc = f"Renamed '{target.name}' -> '{result.new_path.name}'"
        add_log(task_id, desc, "info")
        add_action(task_id=task_id, step=1, action_type="rename", description=desc)
        update_task_status(task_id, "completed", result_summary=desc)
    else:
        desc = f"Could not rename {target.name}: {result.detail}"
        add_log(task_id, desc, "warning")
        add_action(task_id=task_id, step=1, action_type="skip", description=desc)
        update_task_status(task_id, "failed", error=desc)


def run_organizer_task(task_id: str, prompt: str):
    """Synchronous -- run in a background thread by the caller, same pattern
    as run_agent_task_in_thread() wraps the async browser executor."""
    add_log(task_id, f"Initializing organizer for task: '{prompt}'", "info")
    step = 0

    try:
        explicit_target = _extract_explicit_docx_target(prompt)
        if explicit_target:
            add_log(task_id, f"Prompt names a specific file: {explicit_target}", "info")
            _rename_single_file(task_id, explicit_target)
            return

        folder = resolve_folder(prompt)
        add_log(task_id, f"Resolved target folder: {folder}", "info")

        explicit_name = _extract_explicit_filename(prompt)
        if explicit_name:
            target = folder / explicit_name
            add_log(task_id, f"Prompt names a specific file: {target.name}", "info")
            _rename_single_file(task_id, target)
            return

        docx_files = sorted(folder.glob("*.docx"))
        candidates = [f for f in docx_files if is_generically_named(f.stem)]

        if not candidates:
            summary = (
                f"Found {len(docx_files)} .docx file(s) in {folder}, but none looked "
                f"auto-generated (doc1.docx, Untitled.docx, etc.) -- nothing to rename."
            )
            add_log(task_id, summary, "info")
            update_task_status(task_id, "completed", result_summary=summary)
            return

        add_log(task_id, f"Found {len(candidates)} candidate file(s) to rename.", "info")

        renamed, skipped, errors = [], [], []

        for path in candidates:
            step += 1
            try:
                content = extract_docx(path)
            except ExtractionError as e:
                errors.append(f"{path.name}: {e}")
                add_log(task_id, f"Could not read {path.name}: {e}", "warning")
                add_action(task_id=task_id, step=step, action_type="error",
                           description=f"Could not read {path.name}: {e}")
                continue

            new_stem = generate_name(content)
            _log_if_fallback_name(task_id, path, content, new_stem)
            result = safe_rename(path, new_stem, DEFAULT_LOG_PATH, only_if_generic=True)

            if result.status == "renamed":
                renamed.append((path.name, result.new_path.name))
                desc = f"Renamed '{path.name}' -> '{result.new_path.name}'"
                add_log(task_id, desc, "info")
                add_action(task_id=task_id, step=step, action_type="rename", description=desc)
            else:
                skipped.append(f"{path.name}: {result.detail}")
                add_log(task_id, f"Skipped {path.name}: {result.detail}", "warning")
                add_action(task_id=task_id, step=step, action_type="skip",
                           description=f"Skipped {path.name}: {result.detail}")

        summary_lines = [f"Renamed {len(renamed)} of {len(candidates)} candidate file(s) in {folder}."]
        for old, new in renamed:
            summary_lines.append(f"  {old} -> {new}")
        if skipped:
            summary_lines.append(f"{len(skipped)} skipped.")
        if errors:
            summary_lines.append(f"{len(errors)} could not be read.")

        summary = "\n".join(summary_lines)
        add_log(task_id, summary, "info")
        update_task_status(task_id, "completed", result_summary=summary)

    except FolderResolutionError as e:
        add_log(task_id, str(e), "error")
        update_task_status(task_id, "failed", error=str(e))
    except Exception as e:
        err_msg = f"Organizer task failed: {e}"
        add_log(task_id, err_msg, "error")
        update_task_status(task_id, "failed", error=err_msg)
