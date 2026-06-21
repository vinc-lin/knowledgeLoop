"""Assert every required_apis symbol exists in its task's prior_art_files (grep). Usage:
  REPO_ATLAS_REGISTRY=/path/atlas.toml python scripts/verify_grounding_tasks.py [CASES_DIR]
"""
import os
import sys

from repo_atlas.eval.tasks import load_tasks
from repo_atlas.registry import load_registry


def main() -> int:
    cases = sys.argv[1] if len(sys.argv) > 1 else "repo_atlas/eval/tasks-grounding"
    reg = {e.name: e.repo_path
           for e in load_registry(os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))}
    bad = []
    tasks = load_tasks(cases)
    for t in tasks:
        base = reg.get(t.repo)
        if not base:
            bad.append(f"{t.id}: repo {t.repo!r} not in registry")
            continue
        if not t.required_apis:
            bad.append(f"{t.id}: no required_apis")
        for api in t.required_apis:
            bare = api.split("::")[-1]
            found = any(os.path.exists(os.path.join(base, pf))
                        and bare in open(os.path.join(base, pf), errors="ignore").read()
                        for pf in t.prior_art_files)
            if not found:
                bad.append(f"{t.id}: {api} not found in prior_art_files")
    if bad:
        print("PROBLEMS:")
        for b in bad:
            print("  -", b)
        return 1
    print(f"OK: {len(tasks)} tasks, all required_apis exist in their prior-art files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
