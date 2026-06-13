"""Canonical doc filenames + the canonicalization pass."""

from codewiki.src.be.documentation_generator import canonical_doc_name


def test_canonical_plain_name():
    assert canonical_doc_name("Core Infrastructure") == "Core Infrastructure.md"


def test_canonical_keeps_hash():
    assert canonical_doc_name("C# Resolver") == "C# Resolver.md"


def test_canonical_sanitizes_forward_slash():
    assert canonical_doc_name("TypeScript/JavaScript Resolver") == "TypeScript_JavaScript Resolver.md"


def test_canonical_sanitizes_backslash():
    assert canonical_doc_name("A\\B") == "A_B.md"


import os

from codewiki.src.be.documentation_generator import canonicalize_doc_filenames


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
