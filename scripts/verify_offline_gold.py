"""Assert every gold_files entry in the offline retrieval cases exists under its repo's
repo_path (from the registry). Exit non-zero on any missing file. Usage:
  REPO_ATLAS_REGISTRY=/path/atlas.toml python scripts/verify_offline_gold.py [CASES_DIR]
"""
import os
import sys

from repo_atlas.eval.offline.cases import load_retrieval_cases
from repo_atlas.registry import load_registry


def main() -> int:
    cases_dir = sys.argv[1] if len(sys.argv) > 1 else "repo_atlas/eval/offline/cases/retrieval"
    reg = {e.name: e.repo_path
           for e in load_registry(os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))}
    missing = []
    for c in load_retrieval_cases(cases_dir):
        base = reg.get(c.repo)
        if not base:
            missing.append(f"{c.id}: repo {c.repo!r} not in registry")
            continue
        for gf in c.gold_files:
            if not os.path.exists(os.path.join(base, gf)):
                missing.append(f"{c.id}: missing {gf}")
    if missing:
        print("GOLD FILE PROBLEMS:")
        for m in missing:
            print("  -", m)
        return 1
    print(f"OK: all gold files exist across the cases in {cases_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
