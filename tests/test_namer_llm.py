"""
Tests the LLM-based naming tier added to app/organizer/namer.py: the local
Ollama model now writes document names (replacing pure yake keyword
extraction as the primary fallback, which produced awkward "keyword soup"
names). Mirrors tests/test_planner.py's approach -- what's testable without a
running Ollama server is the plumbing (parsing, fallback-on-failure), not
whether a real model produces good names, which can only be judged by
actually running it.
"""
from types import SimpleNamespace

import httpx
from openai import OpenAI

from app.organizer.extractor import DocumentContent
from app.organizer.namer import _generate_name_llm, generate_name


class _FakeClient:
    """Duck-types just enough of the OpenAI client shape for _generate_name_llm
    to work with: client.chat.completions.create(...) -> response with
    .choices[0].message.content."""

    def __init__(self, content: str):
        self._content = content
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        message = SimpleNamespace(content=self._content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


def test_generate_name_llm_returns_none_for_empty_text():
    # Short-circuits before ever touching the network -- no client needed.
    assert _generate_name_llm("") is None
    assert _generate_name_llm("   \n  ") is None


def test_generate_name_llm_falls_back_to_none_when_ollama_unreachable():
    """No Ollama server needed -- point at a closed port and confirm this
    returns None (so the caller falls back to keyword extraction) instead of
    raising and breaking the whole organizer task."""
    unreachable_client = OpenAI(
        base_url="http://127.0.0.1:1/v1",
        api_key="ollama",
        http_client=httpx.Client(trust_env=False, timeout=3.0),
    )
    result = _generate_name_llm("some document body text", client=unreachable_client)
    assert result is None


def test_generate_name_llm_returns_the_response_content():
    client = _FakeClient("Quarterly Budget Review")
    assert _generate_name_llm("body text", client=client) == "Quarterly Budget Review"


def test_generate_name_llm_takes_first_line_when_model_adds_commentary():
    client = _FakeClient("Quarterly Budget Review\nLet me know if you'd like changes!")
    assert _generate_name_llm("body text", client=client) == "Quarterly Budget Review"


def test_generate_name_llm_strips_quotes_and_docx_extension():
    client = _FakeClient('"Quarterly Budget Review.docx"')
    assert _generate_name_llm("body text", client=client) == "Quarterly Budget Review"


def test_generate_name_llm_returns_none_for_blank_response():
    client = _FakeClient("   ")
    assert _generate_name_llm("body text", client=client) is None


def test_generate_name_uses_llm_result_when_available(monkeypatch):
    import app.organizer.namer as namer_module
    monkeypatch.setattr(namer_module, "_generate_name_llm", lambda *a, **kw: "Quarterly Budget Review")

    content = DocumentContent(body_text="some content about a budget")
    assert generate_name(content) == "Quarterly Budget Review"


def test_generate_name_falls_back_to_keywords_when_llm_unavailable(monkeypatch):
    import app.organizer.namer as namer_module
    monkeypatch.setattr(namer_module, "_generate_name_llm", lambda *a, **kw: None)

    content = DocumentContent(body_text="annual budget review process finance quarterly report")
    name = generate_name(content)
    assert name  # some non-empty keyword-derived name
    assert not name.startswith("Untitled Document")


def test_generate_name_prefers_title_and_heading_over_llm(monkeypatch):
    """Title metadata and headings are author-written, so they should still
    win over an LLM call -- the LLM tier should not even be consulted."""
    import app.organizer.namer as namer_module
    called = []
    monkeypatch.setattr(namer_module, "_generate_name_llm", lambda *a, **kw: called.append(1) or "should not be used")

    content = DocumentContent(title_metadata="Real Author Title", body_text="irrelevant")
    assert generate_name(content) == "Real Author Title"
    assert called == [], "LLM naming should not be called when title metadata is present"
