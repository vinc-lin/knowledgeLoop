"""Load a codewiki-generated wiki, anchored on its generation manifest."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WikiData:
    module_tree: dict
    metadata: dict
    docs: dict          # filename -> markdown text (generated docs only)
    wiki_commit: Optional[str]
    files_generated: list = field(default_factory=list)


def load_wiki(wiki_dir: str) -> WikiData:
    """Read module_tree.json + metadata.json and ONLY the files metadata lists
    as generated. Non-generated markdown in the dir is ignored."""
    if not os.path.isdir(wiki_dir):
        raise FileNotFoundError(f"wiki dir not found: {wiki_dir}")
    with open(os.path.join(wiki_dir, "module_tree.json"), encoding="utf-8") as fh:
        module_tree = json.load(fh)
    with open(os.path.join(wiki_dir, "metadata.json"), encoding="utf-8") as fh:
        metadata = json.load(fh)
    files_generated = list(metadata.get("files_generated", []))
    commit = (metadata.get("generation_info") or {}).get("commit_id")
    docs: dict = {}
    for name in files_generated:
        if not name.endswith(".md"):
            continue
        path = os.path.join(wiki_dir, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                docs[name] = fh.read()
    return WikiData(module_tree=module_tree, metadata=metadata, docs=docs,
                    wiki_commit=commit, files_generated=files_generated)
