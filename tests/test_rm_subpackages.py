"""M2 subpackages are importable."""


def test_m2_subpackages_import():
    import repo_memory.graph  # noqa: F401
    import repo_memory.wiki  # noqa: F401
    import repo_memory.tools  # noqa: F401
