# tests/test_ra_symbol_ratio.py
from repo_atlas.config import load_config

_BASE = {"REPO_ATLAS_BASE_URL": "x", "REPO_ATLAS_API_KEY": "y"}   # avoid codewiki fallback


def test_symbol_ratio_default():
    assert load_config(_BASE).symbol_ratio == 0.5


def test_symbol_ratio_parsed_and_clamped():
    assert load_config({**_BASE, "REPO_ATLAS_SYMBOL_RATIO": "0.7"}).symbol_ratio == 0.7
    assert load_config({**_BASE, "REPO_ATLAS_SYMBOL_RATIO": "1.5"}).symbol_ratio == 1.0
    assert load_config({**_BASE, "REPO_ATLAS_SYMBOL_RATIO": "-0.2"}).symbol_ratio == 0.0
    assert load_config({**_BASE, "REPO_ATLAS_SYMBOL_RATIO": "abc"}).symbol_ratio == 0.5
