"""Lightweight case-insensitive substring search over generated docs."""

from repo_memory.wiki.loader import WikiData
from repo_memory.wiki.search import WikiIndex


def _wiki():
    return WikiData(
        module_tree={}, metadata={},
        docs={"a.md": "# Ingestion\nThe chunker splits documents.",
              "b.md": "# Config\nSettings and flags."},
        wiki_commit=None, files_generated=["a.md", "b.md"],
    )


def test_search_finds_matching_doc():
    hits = WikiIndex(_wiki()).search("chunker")
    assert len(hits) == 1
    assert hits[0]["doc"] == "a.md"
    assert "chunker" in hits[0]["snippet"].lower()


def test_search_is_case_insensitive_and_limited():
    hits = WikiIndex(_wiki()).search("CONFIG", limit=5)
    assert hits and hits[0]["doc"] == "b.md"


def test_search_no_match_empty():
    assert WikiIndex(_wiki()).search("nonexistent") == []
