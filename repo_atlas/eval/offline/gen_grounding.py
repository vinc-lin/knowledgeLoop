"""Generate grounding cases: real symbols grep-extracted from repo source (so the grounding
metric measures the store against reality), plus perturbed fakes verified absent from source.

CLI:  REPO_ATLAS_REGISTRY=.../atlas.toml \\
      python -m repo_atlas.eval.offline.gen_grounding --out repo_atlas/eval/offline/cases/grounding \\
      [--per-repo 40]
"""
from __future__ import annotations

import argparse
import os
import re

_SRC_EXT = (".h", ".hpp", ".hxx", ".c", ".cc", ".cpp", ".cxx", ".java", ".kt")
# Definition-anchored: the class/struct/interface keyword must be followed by a name and then a
# definition/declaration token ('{' body, ':' base-clause/bitfield-free, or ';' forward-decl) —
# optionally with `final` or a base-clause in between. This rejects the bare word 'class' in
# prose (e.g. a comment "...used in this class and is...") capturing the following word.
_CLASS = re.compile(
    r"\b(?:class|struct|interface)\s+([A-Za-z_][A-Za-z0-9_]{2,})\b(?:\s+final\b)?\s*(?=[:{;])"
)
_TYPEDEF = re.compile(r"\btypedef\b[^;{]*?\b([A-Za-z_][A-Za-z0-9_]{2,})\s*;")
_MACRO = re.compile(r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]{2,})", re.M)
_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _strip_comments(src: str) -> str:
    """Remove // line comments and /* */ block comments so prose inside them can't be matched
    as code. Block comments are replaced by a single space to preserve line/token boundaries."""
    src = _BLOCK_COMMENT.sub(" ", src)
    return _LINE_COMMENT.sub("", src)


def extract_symbols(src: str) -> list:
    """Class/struct/interface names, typedef names, and macro names (order-preserving dedup).

    Comments are stripped first, and class/struct/interface matches are anchored to actual
    definitions/declarations (keyword + name + ``{``/``:``/``;``) so prose words after the
    bare keyword 'class'/'struct'/'interface' are not captured as symbols.
    """
    src = _strip_comments(src)
    found = {}
    for rx in (_CLASS, _TYPEDEF, _MACRO):
        for name in rx.findall(src):
            found[name] = None
    return list(found)


def make_fakes(real: list, corpus_text: str, n: int) -> list:
    """Perturb real names into plausible-but-absent symbols (verified not in corpus_text)."""
    fakes, i = [], 0
    suffixes = ("Xyz", "FooBar", "2", "Impl9", "Nonexistent")
    while len(fakes) < n and i < len(real) * len(suffixes):
        base = real[i % len(real)]
        suf = suffixes[(i // len(real)) % len(suffixes)]
        cand = base + suf
        if cand not in corpus_text and cand not in real and cand not in fakes:
            fakes.append(cand)
        i += 1
    return fakes


def _read_source(repo_path: str) -> str:
    chunks = []
    for root, _dirs, files in os.walk(repo_path):
        if "/.git" in root:
            continue
        for fn in files:
            if fn.endswith(_SRC_EXT):
                try:
                    with open(os.path.join(root, fn), errors="ignore") as fh:
                        chunks.append(fh.read())
                except OSError:
                    pass
    return "\n".join(chunks)


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def generate(name: str, repo_path: str, per_repo: int) -> str:
    src = _read_source(repo_path)
    real = extract_symbols(src)[:per_repo]
    fakes = make_fakes(real, src, n=min(per_repo, len(real)))
    rl = ", ".join(f'"{_toml_escape(s)}"' for s in real)
    fl = ", ".join(f'"{_toml_escape(s)}"' for s in fakes)
    return (f'id = "{name}-symbols"\nrepo = "{name}"\n'
            f"real_symbols = [{rl}]\nfake_symbols = [{fl}]\n")


def main(argv=None) -> int:
    from repo_atlas.registry import load_registry
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-repo", type=int, default=40)
    ap.add_argument("--registry", default=os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    for e in load_registry(args.registry):
        toml = generate(e.name, e.repo_path, args.per_repo)
        with open(os.path.join(args.out, f"{e.name}.toml"), "w") as fh:
            fh.write(toml)
        print(f"wrote {e.name}.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
