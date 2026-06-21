from repo_atlas.eval.offline.gen_grounding import extract_symbols, make_fakes


def test_extract_symbols_cpp():
    src = ("class CGEImageFilterInterface {};\n"
           "struct CLImageHandler { };\n"
           "typedef const char* CGEConstString;\n"
           "#define CGE_SHADER_STRING_PRECISION_M 1\n"
           "int plain_function() { return 0; }\n")
    syms = extract_symbols(src)
    assert "CGEImageFilterInterface" in syms
    assert "CLImageHandler" in syms
    assert "CGEConstString" in syms                 # typedef name (the under-indexing target)
    assert "CGE_SHADER_STRING_PRECISION_M" in syms  # macro


def test_extract_symbols_ignores_prose_in_comments():
    # The bare keyword 'class'/'struct'/'interface' appearing in prose/comments must NOT
    # cause the following word to be captured as a symbol (regression: yielded 'and', 'used',
    # 'that', 'supports', 'for', 'must', 'will').
    src = (
        "// the renderer used in this class    and is the default that supports\n"
        "/* for the user this struct must will be created for retrieval */\n"
        "the framework used in this class and that interface for must will\n"
        "class RealClass {};\n"
        "struct RealStruct : public Base {};\n"
    )
    syms = extract_symbols(src)
    assert "RealClass" in syms
    assert "RealStruct" in syms
    for prose in ("and", "used", "that", "supports", "for", "must", "will", "created", "retrieval"):
        assert prose not in syms


def test_extract_symbols_anchors_to_definitions():
    # Forward declarations, base clauses, and `final` are real declarations and are captured;
    # the bare keyword followed by a non-definition token (a prose word) is not.
    src = (
        "class FwdDecl;\n"
        "class FinalClass final {};\n"
        "struct WithBase:public Base{};\n"
        "// note: this class describes the overall design and intent\n"
    )
    syms = extract_symbols(src)
    assert set(syms) == {"FwdDecl", "FinalClass", "WithBase"}


def test_make_fakes_are_absent():
    real = ["CGEImageFilterInterface", "CLImageHandler"]
    corpus_text = "\n".join(real)
    fakes = make_fakes(real, corpus_text, n=2)
    assert len(fakes) == 2
    for f in fakes:
        assert f not in corpus_text                 # guaranteed absent
        assert f not in real
