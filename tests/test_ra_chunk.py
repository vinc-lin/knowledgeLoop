from repo_atlas.chunk import chunk_markdown, doc_units


def test_chunk_markdown_splits_by_heading():
    md = "# Title\nintro\n## A\nbody a\n## B\nbody b\n"
    secs = chunk_markdown(md)
    heads = [h for h, _ in secs]
    assert heads == ["Title", "A", "B"]
    assert "body a" in dict(secs)["A"]


def test_doc_units_carry_repo_and_module():
    md = "## Filters\nhow filters work\n"
    units = doc_units(md, repo="r1", module="Image Filters", file="filters.md",
                      repo_head="H")
    assert len(units) == 1
    u = units[0]
    assert u.repo == "r1" and u.kind == "doc" and u.name == "Filters"
    assert u.meta["module"] == "Image Filters"
    assert "how filters work" in u.text
