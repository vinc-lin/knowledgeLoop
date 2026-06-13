"""Body-link canonicalization pass + loadDocument template fix."""

import os
import shutil
import subprocess

import pytest

from codewiki.src.be.documentation_generator import canonicalize_doc_links

TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "codewiki", "templates", "github_pages", "viewer_template.html",
)


def _w(d, name, body):
    with open(os.path.join(str(d), name), "w", encoding="utf-8") as fh:
        fh.write(body)


def _read(d, name):
    with open(os.path.join(str(d), name), encoding="utf-8") as fh:
        return fh.read()


def test_rewrites_rename_map_link(tmp_path):
    _w(tmp_path, "C# Resolver.md", "# C#\n")
    _w(tmp_path, "Java Resolver.md", "See [C#](cs_lsp.md).\n")
    result = canonicalize_doc_links(str(tmp_path), [("cs_lsp.md", "C# Resolver.md")])
    assert "](<C# Resolver.md>)" in _read(tmp_path, "Java Resolver.md")
    assert result == {"rewritten": 1, "unresolved": 0}


def test_rewrites_raw_space_link(tmp_path):
    _w(tmp_path, "C# Resolver.md", "# C#\n")
    _w(tmp_path, "Java Resolver.md", "See [C#](C# Resolver.md).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](<C# Resolver.md>)" in _read(tmp_path, "Java Resolver.md")


def test_rewrites_normalized_variant(tmp_path):
    _w(tmp_path, "Core Infrastructure.md", "# CI\n")
    _w(tmp_path, "a.md", "See [CI](Core_Infrastructure.md).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](<Core Infrastructure.md>)" in _read(tmp_path, "a.md")


def test_rewrites_percent_encoded(tmp_path):
    _w(tmp_path, "Cargo Manifest Parser.md", "# C\n")
    _w(tmp_path, "a.md", "See [C](Cargo%20Manifest%20Parser.md).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](<Cargo Manifest Parser.md>)" in _read(tmp_path, "a.md")


def test_extra_aliases(tmp_path):
    _w(tmp_path, "C# Resolver.md", "# C#\n")
    _w(tmp_path, "a.md", "See [x](C_Sharp_Resolver.md).\n")
    canonicalize_doc_links(str(tmp_path), [], {"csharpresolver": "C# Resolver.md"})
    assert "](<C# Resolver.md>)" in _read(tmp_path, "a.md")


def test_dead_link_untouched(tmp_path):
    _w(tmp_path, "a.md", "See [arena](arena.md).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](arena.md)" in _read(tmp_path, "a.md")


def test_anchor_preserved(tmp_path):
    _w(tmp_path, "Core Infrastructure.md", "# CI\n")
    _w(tmp_path, "a.md", "See [s](Core_Infrastructure.md#scope).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](<Core Infrastructure.md#scope>)" in _read(tmp_path, "a.md")


def test_idempotent(tmp_path):
    _w(tmp_path, "C# Resolver.md", "# C#\n")
    _w(tmp_path, "a.md", "See [x](cs_lsp.md).\n")
    canonicalize_doc_links(str(tmp_path), [("cs_lsp.md", "C# Resolver.md")])
    once = _read(tmp_path, "a.md")
    canonicalize_doc_links(str(tmp_path), [])  # second pass, empty rename map
    assert _read(tmp_path, "a.md") == once


def test_loaddocument_decodes_before_encoding():
    tmpl = open(TEMPLATE, encoding="utf-8").read()
    assert "decodeURIComponent" in tmpl, "loadDocument must decode before re-encoding"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_decode_then_encode_resolves_special_chars():
    # marked.js renders [x](<C# Resolver.md>) as href="C#%20Resolver.md";
    # decode-then-encode must yield a single-encoded, fetchable URL.
    js = "console.log(encodeURIComponent(decodeURIComponent('C#%20Resolver.md')));"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "C%23%20Resolver.md"
