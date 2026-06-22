from repo_atlas.symbol_source import extract_symbol_source

SRC = (
    "#include <x.h>\n"                                                       # 1
    "// Convert a VideoBuffer to the CLBuffer that backs it.\n"             # 2
    "SmartPtr<CLBuffer> convert_to_clbuffer(const SmartPtr<VideoBuffer>& b) {\n"  # 3
    "    CLBuffer *clbuf = unwrap(b);\n"                                    # 4
    "    return clbuf;\n"                                                   # 5
    "}\n"                                                                   # 6
    "int other() { return 0; }\n"                                          # 7
)


def test_uses_line_span_and_prepends_doc_comment():
    out = extract_symbol_source(SRC, "convert_to_clbuffer", start_line=3, end_line=6)
    assert "Convert a VideoBuffer" in out          # doc comment captured
    assert "convert_to_clbuffer(const SmartPtr" in out  # signature captured
    assert "unwrap(b)" in out                      # leading body captured
    assert "int other()" not in out                # stops at end_line


def test_fallback_finds_definition_without_line_range():
    out = extract_symbol_source(SRC, "convert_to_clbuffer", start_line=0, end_line=0)
    assert "convert_to_clbuffer(const SmartPtr" in out


def test_caps_to_max_chars():
    out = extract_symbol_source(SRC, "convert_to_clbuffer", 3, 6, max_chars=20)
    assert len(out) <= 20


def test_missing_symbol_and_empty_src():
    assert extract_symbol_source(SRC, "nope_not_here", 0, 0) == ""
    assert extract_symbol_source("", "x", 1, 2) == ""
