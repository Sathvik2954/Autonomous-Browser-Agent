"""
Scans a folder for generically-named Word documents (doc1.docx, Untitled.docx,
"New Microsoft Word Document.docx", etc.) and renames them based on their
actual content -- title metadata, first heading, or local keyword extraction
(no LLM, no API key, fully offline).

DEFAULTS TO DRY-RUN: prints what it would rename without touching anything.
Pass --apply to actually perform the renames. This touches files outside the
project folder (wherever you point it), so it's deliberately not "fire and
forget" by default -- review the preview, then re-run with --apply once it
looks right.

Usage:
    python scripts/organize_documents.py <folder>                 # preview only
    python scripts/organize_documents.py <folder> --apply         # actually rename
    python scripts/organize_documents.py <folder> --apply --all   # rename even
                                                                    # files that don't
                                                                    # look auto-generated
                                                                    # (use with care)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.organizer.extractor import extract_docx, ExtractionError  # noqa: E402
from app.organizer.namer import generate_name  # noqa: E402
from app.organizer.renamer import safe_rename, is_generically_named  # noqa: E402
from app.config import ROOT_DIR  # noqa: E402

DEFAULT_LOG_PATH = ROOT_DIR / "logs" / "organizer_renames.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="Folder to scan for .docx files")
    parser.add_argument("--apply", action="store_true", help="Actually perform renames (default: preview only)")
    parser.add_argument("--all", action="store_true", help="Consider every .docx, not just generically-named ones")
    parser.add_argument("--recursive", action="store_true", help="Scan subfolders too")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"Not a folder: {args.folder}")
        sys.exit(1)

    pattern = "**/*.docx" if args.recursive else "*.docx"
    docx_files = sorted(args.folder.glob(pattern))

    if not docx_files:
        print(f"No .docx files found in {args.folder}")
        return

    candidates = [f for f in docx_files if args.all or is_generically_named(f.stem)]
    if not candidates:
        print(
            f"Found {len(docx_files)} .docx file(s), but none look auto-generated "
            f"(doc1.docx, Untitled.docx, etc.). Pass --all to consider every file."
        )
        return

    print(f"{'APPLYING' if args.apply else 'PREVIEW (pass --apply to actually rename)'} "
          f"-- {len(candidates)} of {len(docx_files)} file(s) are candidates:\n")

    for path in candidates:
        try:
            content = extract_docx(path)
        except ExtractionError as e:
            print(f"  [SKIP]  {path.name}  -- {e}")
            continue

        new_stem = generate_name(content)

        if not args.apply:
            print(f"  {path.name}  ->  {new_stem}{path.suffix}")
            continue

        result = safe_rename(path, new_stem, DEFAULT_LOG_PATH, only_if_generic=not args.all)
        if result.status == "renamed":
            print(f"  [OK]    {path.name}  ->  {result.new_path.name}")
        else:
            print(f"  [{result.status.upper()}]  {path.name}  -- {result.detail}")

    if args.apply:
        print(f"\nRename log: {DEFAULT_LOG_PATH}")


if __name__ == "__main__":
    main()
