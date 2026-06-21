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


def test_make_fakes_are_absent():
    real = ["CGEImageFilterInterface", "CLImageHandler"]
    corpus_text = "\n".join(real)
    fakes = make_fakes(real, corpus_text, n=2)
    assert len(fakes) == 2
    for f in fakes:
        assert f not in corpus_text                 # guaranteed absent
        assert f not in real
