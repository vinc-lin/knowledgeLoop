from repo_atlas.eval.extract import extract_refs

DIFF = """diff --git a/lib/sepia.cpp b/lib/sepia.cpp
new file mode 100644
--- /dev/null
+++ b/lib/sepia.cpp
@@ -0,0 +1,3 @@
+class SepiaFilter : public cgeImageFilter {
+    void apply() { cgeBrightnessAdjust(); }
+};
"""


def test_extract_files_and_symbols():
    symbols, files = extract_refs(DIFF)
    assert "lib/sepia.cpp" in files
    assert "cgeImageFilter" in symbols          # CamelCase
    assert "cgeBrightnessAdjust" in symbols     # CamelCase + call site
    assert "SepiaFilter" in symbols             # PascalCase
    # language keywords are NOT counted as symbol references
    assert "class" not in symbols and "public" not in symbols and "void" not in symbols


def test_extract_filters_keywords_and_locals():
    diff = ("--- /dev/null\n+++ b/a.c\n@@ -0,0 +1 @@\n"
            "+    int total = computeSum(items);\n")
    symbols, _ = extract_refs(diff)
    assert "computeSum" in symbols              # call site + CamelCase
    # primitives / plain lowercase locals are dropped
    assert "int" not in symbols
    assert "total" not in symbols and "items" not in symbols


def test_extract_empty_diff():
    assert extract_refs("") == ([], [])


def test_extract_dedups_files():
    # two diff chunks touching the same file -> file listed once
    two = ("--- /dev/null\n+++ b/foo.py\n@@ -0,0 +1 @@\n+aaa\n"
           "--- a/foo.py\n+++ b/foo.py\n@@ -0,0 +1 @@\n+bbb\n")
    symbols, files = extract_refs(two)
    assert files == ["foo.py"]
