"""
Turns extracted document content into a filesystem-safe, descriptive filename.

Falls back through signals in order of reliability:
1. Title metadata, if the author ever set one -- most reliable, it's literally
   what the author called the document.
2. First heading -- also author-written, second most reliable.
3. The local LLM (via Ollama, same model the browser agent already uses)
   reads the body text and writes a real, meaningful title. This replaced
   pure statistical keyword extraction (yake) as the primary fallback because
   yake picks frequently-occurring words/phrases without understanding what
   the document is actually about, which produced accurate-sounding but
   often awkward "keyword soup" names (e.g. "Annual Budget Review Process"
   instead of something that actually captures the document's point).
4. If the LLM is unreachable or fails (Ollama not running, timeout, etc.),
   falls back to yake keyword extraction -- worse names, but the task still
   completes instead of failing outright over a naming nicety.
5. A timestamped placeholder if there's truly nothing to work with (e.g. an
   empty document).

This is still a heuristic, not guaranteed-correct understanding -- it won't
be right 100% of the time, which is exactly why the renamer keeps an
old-name/new-name log and the CLI defaults to a dry-run preview rather than
silently committing renames.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx
import yake
from openai import OpenAI

from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from app.organizer.extractor import DocumentContent

logger = logging.getLogger(__name__)

MAX_FILENAME_LENGTH = 80
KEYWORD_COUNT = 5

# Only need enough of the document to identify its topic, not the whole
# thing -- keeps latency and token usage bounded on long documents.
LLM_EXCERPT_LENGTH = 4000

_NAMING_SYSTEM_PROMPT = """You are naming a Word document based on its content.
Respond with ONLY a short, descriptive filename for the document -- no file
extension, no quotes, no explanation, nothing else. Just the name.

Rules:
- 3 to 8 words, Title Case
- Must actually describe what the document is about, not generic words like "Document" or "Notes" unless nothing more specific fits
- No punctuation other than spaces and hyphens
- Do not include a file extension (no ".docx")
"""


def _slugify(text: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Filesystem-safe and still readable: strips characters that are illegal
    or awkward in filenames (/ \\ : * ? " < > | and other punctuation), collapses
    whitespace, and truncates on a word boundary rather than mid-word."""
    cleaned = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rsplit(" ", 1)[0]
    return cleaned


def _extract_keywords(text: str, count: int = KEYWORD_COUNT) -> list[str]:
    if not text.strip():
        return []
    try:
        # top is intentionally larger than `count`: yake's bigrams overlap
        # (e.g. "annual budget" + "budget review" both score well on a doc
        # about an annual budget review), and word-level dedup below needs
        # more raw candidates than the final word count to have anything left
        # to pick from after collapsing the overlap.
        extractor = yake.KeywordExtractor(lan="en", n=2, top=count * 3, dedupLim=0.7)
        keywords = extractor.extract_keywords(text)
    except Exception as e:
        logger.warning(f"Keyword extraction failed: {e}")
        return []

    # yake returns (keyword, score) pairs where LOWER score = more relevant --
    # easy to get backwards, so this is covered by a test against a real doc.
    keywords.sort(key=lambda pair: pair[1])
    return [kw for kw, _score in keywords]


def _dedupe_words_preserve_order(phrases: list[str], max_words: int = KEYWORD_COUNT) -> list[str]:
    """Collapses overlapping keyword phrases into a flat, word-deduplicated list.

    Without this, "annual budget" + "budget review" (both legitimately
    high-scoring on a doc about an annual budget review) concatenate into
    "Annual Budget Budget Review" -- technically not wrong, but reads as
    broken. Keeps first-occurrence casing and order rather than sorting
    alphabetically, since extraction order roughly reflects relevance."""
    seen = set()
    words: list[str] = []
    for phrase in phrases:
        for word in phrase.split():
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            words.append(word)
            if len(words) >= max_words:
                return words
    return words


def _generate_name_llm(body_text: str, client=None) -> str | None:
    """Asks the local Ollama model to write a name from the document's body
    text. Returns None on any failure (Ollama not running, timeout, bad
    response, empty text) rather than raising -- naming is a nicety, and the
    caller falls back to keyword extraction rather than failing the whole
    organizer task over it.

    `client` is accepted for testing -- pass a fake with a
    `.chat.completions.create(...)` method to test without a real Ollama
    server."""
    if not body_text.strip():
        return None

    try:
        if client is None:
            # trust_env=False: this always talks to a local/user-configured
            # endpoint, never a third party, so system proxy env vars
            # shouldn't apply -- same reasoning as app/planner/planner.py.
            client = OpenAI(
                base_url=OLLAMA_BASE_URL,
                api_key="ollama",
                http_client=httpx.Client(trust_env=False, timeout=30.0),
            )

        excerpt = body_text[:LLM_EXCERPT_LENGTH]
        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": _NAMING_SYSTEM_PROMPT},
                {"role": "user", "content": excerpt},
            ],
            temperature=0.2,
            max_tokens=32,
        )
        raw = (response.choices[0].message.content or "").strip()

        # Small local models sometimes add commentary despite instructions --
        # take only the first non-empty line as the actual name.
        first_line = next((line.strip() for line in raw.splitlines() if line.strip()), "")
        first_line = first_line.strip("\"'` ")
        if first_line.lower().endswith(".docx"):
            first_line = first_line[:-5].rstrip()

        return first_line or None

    except Exception as e:
        logger.warning(f"LLM naming failed, will fall back to keyword extraction: {e}")
        return None


def generate_name(content: DocumentContent) -> str:
    """Returns a filename WITHOUT extension -- the caller appends .docx (or
    whatever the source format was)."""
    if content.title_metadata:
        name = _slugify(content.title_metadata)
        if name:
            return name

    if content.headings:
        name = _slugify(content.headings[0])
        if name:
            return name

    llm_name = _generate_name_llm(content.body_text)
    if llm_name:
        name = _slugify(llm_name)
        if name:
            return name

    keywords = _extract_keywords(content.body_text)
    words = _dedupe_words_preserve_order(keywords)
    if words:
        name = _slugify(" ".join(w.title() for w in words))
        if name:
            return name

    return f"Untitled Document {datetime.now().strftime('%Y-%m-%d %H%M%S')}"
