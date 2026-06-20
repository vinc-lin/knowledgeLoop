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
