from repo_atlas.index import build_units


class _Wiki:
    module_tree = {"Image Filters": {}}
    wiki_commit = "H"
    docs = {"image-filters.md": "## Image Filters\nhow filters work\n"}
    files_generated = ["image-filters.md"]


def test_build_units_makes_doc_and_symbol_units():
    symbol_rows = [{"qualified_name": "cge.brightness", "name": "brightness",
                    "label": "Class", "file_path": "f.cpp"}]
    units = build_units(_Wiki(), symbol_rows, repo="r1", repo_head="H")
    kinds = sorted({u.kind for u in units})
    assert kinds == ["doc", "symbol"]
    sym = [u for u in units if u.kind == "symbol"][0]
    assert sym.qualified_name == "cge.brightness" and sym.file == "f.cpp"
    assert "brightness" in sym.text and "Class" in sym.text
    doc = [u for u in units if u.kind == "doc"][0]
    assert doc.name == "Image Filters"


def test_build_units_enriches_symbol_text_via_reader():
    from repo_atlas.index import build_units
    rows = [{"name": "convert_to_clbuffer", "qualified_name": "ns.convert_to_clbuffer",
             "label": "Function", "file_path": "a.cpp", "start_line": 2, "end_line": 4}]
    src = {"a.cpp": ("// Convert a VideoBuffer to a CLBuffer.\n"
                     "SmartPtr<CLBuffer> convert_to_clbuffer(const SmartPtr<VideoBuffer>& b) {\n"
                     "    return unwrap(b);\n}\n")}
    units = build_units(_Wiki(), rows, repo="r", repo_head="H",
                        source_reader=lambda f: src.get(f, ""))
    sym = [u for u in units if u.kind == "symbol"][0]
    assert "convert_to_clbuffer" in sym.text           # name still present
    assert "Convert a VideoBuffer" in sym.text         # enriched with the doc comment
    assert "SmartPtr<CLBuffer>" in sym.text             # enriched with the signature


def test_build_units_without_reader_is_back_compat():
    from repo_atlas.index import build_units
    rows = [{"name": "foo", "qualified_name": "foo", "label": "Function", "file_path": "a.cpp"}]
    units = build_units(_Wiki(), rows, repo="r", repo_head="H")
    assert [u for u in units if u.kind == "symbol"][0].text == "foo Function foo a.cpp"
