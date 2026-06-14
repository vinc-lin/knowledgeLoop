#!/usr/bin/env python
"""Stand up bridge->consume for a target repo and drive the repo_memory tools.

Defaults target the ndk-samples corpus (a hello-jni smoke wiki). It is a
repeatable, production-faithful harness: it builds AppState exactly like
`repo_memory.server.main()` (same repo_head derivation, same
`resolve_launch_spec` CBM launch), then exercises the wiki -> bridge -> graph ->
hybrid tool surface and prints each envelope's freshness/provenance so you can
see the MVP working end-to-end.

It does NOT run `codewiki generate` (the LLM "produce" step) -- generate the wiki
bundle first; this script tells you how if REPO_MEMORY_WIKI_DIR has no
module_tree.json.

Override any path/profile via env (same vars the server reads):
  REPO_MEMORY_REPO_PATH   target repo CBM indexes      (default: ndk-samples corpus)
  REPO_MEMORY_WIKI_DIR    codewiki wiki bundle dir      (default: _wiki/ndk-hello-jni)
  REPO_MEMORY_ENTITY_MAP  bridge artifact path          (default: <wiki>/entity_map.json)
  REPO_MEMORY_CBM_PROFILE dev|ephemeral|shared|ci       (default: dev)
  CBM_CACHE_DIR           CBM SQLite cache (LOCAL fs!)  (default: ~/cbm-cache/<repo>)

Usage:  /home/vinc/code/knowledgeLoop/.venv/bin/python scripts/ndk_mvp_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys

from repo_memory.state import load_app_state
from repo_memory.server import _resolve_repo_head
from repo_memory.deploy import resolve_launch_spec
from repo_memory.graph.client import CBMClient
from repo_memory.grounding import compute_freshness, graph_is_current
from repo_memory.tools import wiki_tools, graph_tools, hybrid_tools
from repo_memory.refresh import refresh

CORPUS = "/mnt/x/code/corpora/ndk-samples"
WIKI = "/mnt/x/code/corpora/_wiki/ndk-hello-jni"

# Apply harness defaults BEFORE resolve_launch_spec reads os.environ.
os.environ.setdefault("REPO_MEMORY_REPO_PATH", CORPUS)
os.environ.setdefault("REPO_MEMORY_WIKI_DIR", WIKI)
os.environ.setdefault(
    "REPO_MEMORY_ENTITY_MAP",
    os.path.join(os.environ["REPO_MEMORY_WIKI_DIR"], "entity_map.json"),
)
# CBM cache MUST live on a local (non-v9fs) fs; ~ is local here, /mnt/x is 9p.
os.environ.setdefault(
    "CBM_CACHE_DIR",
    os.path.expanduser("~/cbm-cache/" + os.path.basename(os.environ["REPO_MEMORY_REPO_PATH"])),
)


def hr(title: str) -> None:
    print("\n" + "=" * 72 + "\n" + title + "\n" + "=" * 72)


def show(label: str, env: dict) -> None:
    """Print one tool envelope compactly: freshness, provenance, warnings, result head."""
    fresh = env.get("freshness")
    prov = env.get("provenance", {})
    warns = env.get("warnings") or []
    result = env.get("result")
    head = json.dumps(result, default=str)
    if head and len(head) > 600:
        head = head[:600] + " ...(truncated)"
    print(f"\n[{label}]  freshness={fresh}")
    print(f"  provenance: repo_head={prov.get('repo_head')} "
          f"wiki_commit={prov.get('wiki_commit')} graph_commit={prov.get('graph_commit')}")
    if warns:
        print(f"  warnings: {warns}")
    print(f"  result: {head if result is not None else 'None (degraded/blocked)'}")


async def call(label: str, coro):
    try:
        env = await coro
        show(label, env)
        return env
    except Exception as exc:  # noqa: BLE001 - harness: never abort on one tool
        print(f"\n[{label}]  EXCEPTION: {type(exc).__name__}: {exc}")
        return None


async def main() -> int:
    repo_path = os.environ["REPO_MEMORY_REPO_PATH"]
    wiki_dir = os.environ["REPO_MEMORY_WIKI_DIR"]
    entity_map_path = os.environ["REPO_MEMORY_ENTITY_MAP"]
    cache_dir = os.environ.get("CBM_CACHE_DIR")
    profile = os.environ.get("REPO_MEMORY_CBM_PROFILE", "dev")

    hr("CONFIG")
    print(f"  repo_path     : {repo_path}")
    print(f"  wiki_dir      : {wiki_dir}")
    print(f"  entity_map    : {entity_map_path}")
    print(f"  cbm_profile   : {profile}")
    print(f"  cbm_cache_dir : {cache_dir}")
    os.makedirs(cache_dir, exist_ok=True)

    repo_head = _resolve_repo_head(repo_path, os.environ)
    print(f"  repo_head     : {repo_head}  "
          f"({'OK' if repo_head else 'None -> freshness will cap at unverified'})")

    if not os.path.isfile(os.path.join(wiki_dir, "module_tree.json")):
        hr("MISSING WIKI BUNDLE")
        print(f"  No module_tree.json under {wiki_dir}.")
        print("  Generate it first (LLM 'produce' step), e.g.:")
        print(f"    cd {repo_path} && CODEWIKI_NO_KEYRING=1 codewiki generate \\")
        print(f"      --output {wiki_dir} --include 'hello-jni/*' --github-pages --verbose")
        return 2

    state = load_app_state(
        wiki_dir=wiki_dir, entity_map_path=entity_map_path,
        repo_head=repo_head, repo_path=repo_path,
        project=os.environ.get("REPO_MEMORY_CBM_PROJECT"),
    )
    n_mods = len((state.wiki.module_tree or {})) if state.wiki else 0
    print(f"  wiki loaded   : {state.wiki is not None} (top-level keys={n_mods}, "
          f"wiki_commit={state.wiki.wiki_commit if state.wiki else None})")
    print(f"  entity_map    : {'present' if state.entity_map else 'absent (build via refresh_index)'}")
    print(f"  freshness pre-CBM: {compute_freshness(state)}")

    hr("LAUNCH CBM (uvx, pinned via resolve_launch_spec)")
    if shutil.which("uvx") is None:
        print("  uvx NOT on PATH -> cannot spawn CBM. Wiki tools only.")
    else:
        spec = resolve_launch_spec(environ=os.environ)
        print(f"  command: {' '.join(spec.command)}")
        client = CBMClient(spec.command, env=spec.env, cwd=spec.cwd)
        try:
            await client.start()
            state.cbm = client
            print("  CBM started.")
        except Exception as exc:  # noqa: BLE001
            print(f"  CBM start FAILED ({type(exc).__name__}: {exc}) -> degrade to wiki-only.")
            state.cbm = None

    try:
        hr("WIKI TOOLS (work without CBM)")
        await call("get_repo_overview", _maybe(wiki_tools.get_repo_overview(state)))
        await call("list_modules", _maybe(wiki_tools.list_modules(state)))

        hr("BRIDGE BOOTSTRAP: refresh_index (indexes corpus -> writes entity_map.json)")
        print(f"  graph_is_current BEFORE refresh: {graph_is_current(state)}")
        await call("refresh_index", refresh(state))
        print(f"  graph_is_current AFTER refresh : {graph_is_current(state)}")
        print(f"  entity_map.json written outside corpus? "
              f"{os.path.isfile(entity_map_path)} -> {entity_map_path}")

        hr("GRAPH TOOLS (post-refresh)")
        await call("get_architecture", graph_tools.get_architecture(state))
        await call("search_code_graph(limit=5)",
                   graph_tools.search_code_graph(state, limit=5))

        hr("HYBRID TOOLS")
        await call("explain_with_sources",
                   hybrid_tools.explain_with_sources(state, "how does the app call native JNI code"))
        await call("assess_impact (FAIL-CLOSED)", hybrid_tools.assess_impact(state))
    finally:
        if state.cbm is not None:
            await state.cbm.aclose()

    hr("READ-ONLY INVARIANT CHECK")
    # core.fileMode=false suppresses v9fs filemode noise (every file shows 100644->100755
    # on the 9p mount); we only care about real content/untracked changes from our run.
    porcelain = subprocess.run(
        ["git", "-C", repo_path, "-c", "core.fileMode=false", "status", "--porcelain"],
        capture_output=True, text=True,
    ).stdout.splitlines()
    tracked = [ln for ln in porcelain if not ln.startswith("??")]
    untracked = [ln for ln in porcelain if ln.startswith("??")]
    print(f"  tracked content changes (filemode-ignored): "
          f"{'CLEAN' if not tracked else 'DIRTY: ' + repr(tracked)}")
    print(f"  untracked files present: {untracked or 'none'} "
          f"(pre-existing docs pollution is expected; our run adds none)")
    leaked = [p for p in ("entity_map.json", "wiki-docs", ".cbm")
              if os.path.exists(os.path.join(repo_path, p))]
    print(f"  stray MVP artifacts inside corpus: {leaked or 'none'}")
    return 0


async def _maybe(value):
    """Wrap a sync tool result as an awaitable so call() can treat all tools uniformly."""
    return value


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
