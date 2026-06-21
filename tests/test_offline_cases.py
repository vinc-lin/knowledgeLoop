import pytest
from repo_atlas.eval.offline.cases import (GroundingCase,
                                           load_retrieval_cases, load_grounding_cases)

RET_SINGLE = """
id = "c1"
repo = "r"
query = "find the filter base"
gold_files = ["a/b.h"]
gold_symbols = ["Base"]
"""

RET_ARRAY = """
[[case]]
id = "c2"
repo = "r"
query = "q2"
gold_files = ["x.cpp"]

[[case]]
id = "c3"
repo = "r"
query = "q3"
gold_files = ["y.cpp"]
"""

GND = """
id = "g1"
repo = "r"
real_symbols = ["Real1", "Real2"]
fake_symbols = ["FakeX"]
"""


def test_load_retrieval_single_and_array(tmp_path):
    (tmp_path / "a.toml").write_text(RET_SINGLE)
    (tmp_path / "b.toml").write_text(RET_ARRAY)
    cases = load_retrieval_cases(str(tmp_path))
    by_id = {c.id: c for c in cases}
    assert set(by_id) == {"c1", "c2", "c3"}
    assert by_id["c1"].gold_files == ("a/b.h",)
    assert by_id["c1"].gold_symbols == ("Base",)
    assert by_id["c2"].gold_symbols == ()           # default
    assert by_id["c2"].source == "curated"          # default


def test_load_grounding(tmp_path):
    (tmp_path / "g.toml").write_text(GND)
    cases = load_grounding_cases(str(tmp_path))
    assert len(cases) == 1 and isinstance(cases[0], GroundingCase)
    assert cases[0].real_symbols == ("Real1", "Real2")


def test_retrieval_missing_gold_files_errors(tmp_path):
    (tmp_path / "bad.toml").write_text('id="x"\nrepo="r"\nquery="q"\n')
    with pytest.raises(ValueError):
        load_retrieval_cases(str(tmp_path))


def test_duplicate_id_errors(tmp_path):
    # the same case id appears in two files -> loader must reject it
    (tmp_path / "e.toml").write_text(RET_SINGLE)
    (tmp_path / "f.toml").write_text(RET_SINGLE)
    with pytest.raises(ValueError):
        load_retrieval_cases(str(tmp_path))
