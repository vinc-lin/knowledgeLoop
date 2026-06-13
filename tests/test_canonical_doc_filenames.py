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
