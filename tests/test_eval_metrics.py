from repo_atlas.eval.metrics import hallucination_rate, reuse_recall


def test_hallucination_rate():
    real = {"cgeImageFilter", "cgeBrightnessAdjust"}
    refs = ["cgeImageFilter", "cgeApplyBrightness", "SepiaFilter"]
    # 2 of 3 are not in the graph (cgeApplyBrightness, SepiaFilter)
    assert hallucination_rate(refs, lambda s: s in real) == 2 / 3
    assert hallucination_rate([], lambda s: True) == 0.0


def test_reuse_recall():
    # solution referenced cgeImageFilter (a key symbol) + the key file
    rec = reuse_recall(["cgeImageFilter", "X"], ["a/b.cpp"],
                       expected_symbols=["cgeImageFilter"], expected_files=["a/b.cpp"])
    assert rec == 1.0
    # missed everything
    assert reuse_recall(["Y"], ["z.cpp"], expected_symbols=["cgeImageFilter"],
                        expected_files=["a/b.cpp"]) == 0.0
    # no key defined -> recall is 1.0 (nothing to miss)
    assert reuse_recall(["Y"], ["z.cpp"], expected_symbols=[], expected_files=[]) == 1.0
