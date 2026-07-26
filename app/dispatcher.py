"""
Coarse routing between the two kinds of task this agent can run: a browser
task (open websites, search, extract data) or an organizer task (rename
generically-named documents in a local folder).

This is deliberately a keyword heuristic, not another LLM call. It only has to
answer one binary question -- "does this prompt want me touching local files,
or the browser?" -- and an extra model round-trip isn't worth it for a
decision this coarse. Contrast with app/planner/planner.py, which needs real
reasoning to plan *which* browser action to take next.

If this ever misroutes something, the fix is almost always to widen
ORGANIZER_VERBS/ORGANIZER_NOUNS below, not to reach for a model.
"""
from __future__ import annotations

import re

ORGANIZER_VERBS = {
    "organize", "organise", "rename", "clean up", "cleanup", "tidy", "tidy up",
    "sort", "auto-name", "autoname", "auto name", "declutter",
}

ORGANIZER_NOUNS = {
    "file", "files", "document", "documents", "docx", "folder", "folders",
    "desktop", "downloads", "doc1",
}


def _contains_any(text: str, phrases: set[str]) -> bool:
    return any(re.search(r"\b" + re.escape(phrase) + r"\b", text) for phrase in phrases)


def classify_task(prompt: str) -> str:
    """Returns "organizer" or "browser". Requires at least one verb AND one
    noun from the organizer vocabulary to route away from the browser --
    a lone noun ("find me a folder of recipes online") shouldn't be enough,
    since that's still a browsing task."""
    text = (prompt or "").lower()

    has_verb = _contains_any(text, ORGANIZER_VERBS)
    has_noun = _contains_any(text, ORGANIZER_NOUNS)

    if has_verb and has_noun:
        return "organizer"
    return "browser"
