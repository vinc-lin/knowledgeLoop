"""Tests for canonical doc filenames + the canonicalization pass."""

import json
import os
import re
import subprocess

from codewiki.src.be.documentation_generator import (
    canonical_doc_name,
    canonicalize_doc_filenames,
)

# Anchor to the repo root (this file lives in <repo>/tests/) so the test works
# regardless of the pytest invocation CWD.
TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "codewiki", "templates", "github_pages", "viewer_template.html",
)


def test_canonical_plain_name():
    assert canonical_doc_name("Core Infrastructure") == "Core Infrastructure.md"


def test_canonical_keeps_hash():
    assert canonical_doc_name("C# Resolver") == "C# Resolver.md"


def test_canonical_sanitizes_forward_slash():
    assert canonical_doc_name("TypeScript/JavaScript Resolver") == "TypeScript_JavaScript Resolver.md"


def test_canonical_sanitizes_backslash():
    assert canonical_doc_name("A\\B") == "A_B.md"


def _write(d, name, body="# Doc\n"):
    with open(os.path.join(str(d), name), "w", encoding="utf-8") as fh:
        fh.write(body)


def test_pass_renames_variant_name(tmp_path):
    _write(tmp_path, "Rust_Resolver.md")
    tree = {"Rust Resolver": {"components": ["a::A"], "children": {}}}
    renames = canonicalize_doc_filenames(str(tmp_path), tree)
    assert renames == [("Rust_Resolver.md", "Rust Resolver.md")]
    assert os.path.exists(os.path.join(str(tmp_path), "Rust Resolver.md"))


def test_pass_h1_fallback_for_arbitrary_name(tmp_path):
    _write(tmp_path, "cs_lsp.md", "# C# Resolver (cs_lsp)\n\nbody\n")
    tree = {"C# Resolver": {"components": ["a::A"], "children": {}}}
    renames = canonicalize_doc_filenames(str(tmp_path), tree)
    assert renames == [("cs_lsp.md", "C# Resolver.md")]
    assert os.path.exists(os.path.join(str(tmp_path), "C# Resolver.md"))


def test_pass_noop_when_already_canonical(tmp_path):
    _write(tmp_path, "Core Infrastructure.md")
    tree = {"Core Infrastructure": {"components": ["a::A"], "children": {}}}
    assert canonicalize_doc_filenames(str(tmp_path), tree) == []
    assert os.path.exists(os.path.join(str(tmp_path), "Core Infrastructure.md"))


def test_pass_is_idempotent(tmp_path):
    _write(tmp_path, "Rust_Resolver.md")
    tree = {"Rust Resolver": {"components": ["a::A"], "children": {}}}
    canonicalize_doc_filenames(str(tmp_path), tree)
    assert canonicalize_doc_filenames(str(tmp_path), tree) == []


def test_pass_skips_collision_without_clobber(tmp_path):
    # Two nodes whose canonical names collide ("A/B" and "A_B" -> "A_B.md").
    _write(tmp_path, "A_B.md", "# A_B\n\noriginal A_B\n")        # already canonical for node "A_B"
    _write(tmp_path, "ab_doc.md", "# A/B\n\nnode A/B\n")          # node "A/B" doc, H1 names it
    tree = {
        "A_B": {"components": ["a::A"], "children": {}},
        "A/B": {"components": ["b::B"], "children": {}},
    }
    renames = canonicalize_doc_filenames(str(tmp_path), tree)
    assert ("ab_doc.md", "A_B.md") not in renames
    assert os.path.exists(os.path.join(str(tmp_path), "ab_doc.md"))
    with open(os.path.join(str(tmp_path), "A_B.md"), encoding="utf-8") as fh:
        assert "original A_B" in fh.read()


def test_pass_recurses_into_children(tmp_path):
    _write(tmp_path, "child_doc.md", "# Child Mod\n")
    tree = {"Parent": {"components": ["p::P"], "children": {
        "Child Mod": {"components": ["c::C"], "children": {}}}}}
    renames = canonicalize_doc_filenames(str(tmp_path), tree)
    assert ("child_doc.md", "Child Mod.md") in renames


def test_template_defines_slug_and_encodes():
    tmpl = open(TEMPLATE, encoding="utf-8").read()
    assert "function slug(" in tmpl, "slug() helper missing from template"
    assert "slug(key)" in tmpl, "buildNavItem should use slug(key)"
    assert "encodeURIComponent(" in tmpl, "loadDocument should URL-encode the filename"


def test_python_js_slug_parity():
    """Extract the template's slug() and run it via node; it must equal canonical_doc_name."""
    tmpl = open(TEMPLATE, encoding="utf-8").read()
    m = re.search(r"function slug\((\w+)\)\s*\{(.*?)\}", tmpl, re.DOTALL)
    assert m, "could not locate function slug(...) in template"
    arg, body = m.group(1), m.group(2).strip()
    keys = ["Plain", "C# Resolver", "TypeScript/JavaScript Resolver", "A\\B", "Rust Resolver"]
    js = (f"const slug=({arg})=>{{{body}}};"
          "const keys=JSON.parse(process.argv[1]);"
          "console.log(JSON.stringify(keys.map(slug)));")
    out = subprocess.run(["node", "-e", js, json.dumps(keys)],
                         capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [canonical_doc_name(k) for k in keys]
