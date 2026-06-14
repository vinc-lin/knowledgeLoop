"""Wiki loader reads ONLY codewiki-generated files (manifest-anchored)."""

import json
import os

from repo_memory.wiki.loader import load_wiki


def _write(d, rel, text):
    path = os.path.join(d, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _make_wiki(d):
    _write(d, "module_tree.json", json.dumps({"m": {"path": "p", "components": [], "children": {}}}))
    _write(d, "metadata.json", json.dumps({
        "generation_info": {"commit_id": "abc123"},
        "files_generated": ["overview.md", "m.md"],
    }))
    _write(d, "overview.md", "# Overview\n")
    _write(d, "m.md", "# Module m\n")
    # NON-generated noise that MUST be excluded:
    _write(d, "findings-and-practices.md", "hand notes\n")
    _write(d, "superpowers/specs/x-design.md", "a spec\n")


def test_loads_only_generated(tmp_path):
    _make_wiki(str(tmp_path))
    wiki = load_wiki(str(tmp_path))
    assert wiki.wiki_commit == "abc123"
    assert set(wiki.docs) == {"overview.md", "m.md"}
    assert "findings-and-practices.md" not in wiki.docs
    assert "superpowers/specs/x-design.md" not in wiki.docs
    assert wiki.module_tree["m"]["path"] == "p"


def test_missing_dir_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_wiki(str(tmp_path / "nope"))
