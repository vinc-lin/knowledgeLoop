"""repo_atlas CLI: `repo-atlas index [--all|--repo NAME]` populates the store;
no subcommand (or `serve`) launches the MCP server (stdio).
"""
from __future__ import annotations

import argparse
import asyncio
import os
from typing import Optional

from repo_atlas.config import load_config
from repo_atlas.registry import load_registry
from repo_atlas.store import Store
from repo_atlas.embed import GatewayEmbedder
from repo_atlas import index as _index


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="repo-atlas",
                                description="Cross-repo knowledge base over existing per-repo knowledge.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the MCP server over stdio (default)")
    ix = sub.add_parser("index", help="index registered repos into the store")
    ix.add_argument("--all", action="store_true", help="index every registered repo")
    ix.add_argument("--repo", help="index a single registered repo by name")
    ix.add_argument("--registry",
                    help="path to atlas.toml (default: $REPO_ATLAS_REGISTRY or ./atlas.toml)")
    ev = sub.add_parser("eval", help="run the with/without eval harness")
    ev.add_argument("--tasks", required=True, help="dir of task .toml files")
    ev.add_argument("--out", default="eval-scorecard.md", help="scorecard output path")
    ev.add_argument("--limit", type=int, default=0, help="limit number of tasks (0 = all)")
    ev.add_argument("--mcp-config", help="MCP config json pointing at repo-atlas (treatment)")
    ev.add_argument("--scorer", choices=["judge", "grounding", "grounded-use"], default="judge",
                    help="grounding = diff references required_apis (no judge); grounded-use = the "
                         "API is CALLED on an added line inside the task's target files (genuine-gap)")
    eo = sub.add_parser("eval-offline",
                        help="deterministic retrieval+grounding eval (no agent)")
    eo.add_argument("--cases", default="repo_atlas/eval/offline/cases",
                    help="dir with retrieval/ and grounding/ subdirs of case .toml")
    eo.add_argument("--layer", choices=["retrieval", "grounding", "all"], default="all")
    eo.add_argument("--k", default="5,10,20", help="comma-separated cutoffs")
    eo.add_argument("--out", default="offline-scorecard.md")
    ea = sub.add_parser("eval-arms",
                        help="multi-arm agentic eval + proxy↔outcome correlation")
    ea.add_argument("--tasks", required=True, help="dir of task .toml files")
    ea.add_argument("--out", default="eval-arms-scorecard.md")
    ea.add_argument("--limit", type=int, default=0, help="limit number of tasks (0 = all)")
    ea.add_argument("--mcp-config", help="MCP config json (optional/mandatory-call arms)")
    ea.add_argument("--arms", default="control,optional,forced-inject,mandatory-call",
                    help="comma-separated arm names")
    ea.add_argument("--proxy-k", type=int, default=10, help="symbol-retrieval cutoff for the proxy")
    ea.add_argument("--scorer", choices=["grounding", "grounded-use"], default="grounding",
                    help="grounded-use = API called on an added line in the task's target files "
                         "(use with genuine-gap tasks); grounding = API referenced anywhere in the diff")
    ea.add_argument("--timeout", type=int, default=900,
                    help="per `claude -p` run wall-clock cap in seconds (default 900)")
    ea.add_argument("--inject-k", type=int, default=5,
                    help="forced-inject arm: how many retrieval units to pre-paste (default 5; "
                         "use ~20 for cross-repo so the ceiling sees what find_related returns)")
    return p


def _run_index(args) -> int:
    registry_path = args.registry or os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml")
    entries = load_registry(registry_path)
    if args.repo:
        entries = [e for e in entries if e.name == args.repo]
        if not entries:
            print(f"repo_atlas: no repo named {args.repo!r} in {registry_path}")
            return 2
    elif not args.all:
        print("repo_atlas index: specify --all or --repo NAME")
        return 2

    cfg = load_config(os.environ)
    store = Store(cfg.db_path)
    embedder = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    counts = asyncio.run(_index.index_all(entries, store, embedder))
    for name, n in counts.items():
        print(f"indexed {name}: {n} units")
    return 0


def _run_eval(args) -> int:
    from repo_atlas.config import load_config
    from repo_atlas.store import Store
    from repo_atlas.eval.tasks import load_tasks
    from repo_atlas.eval.runner import ClaudeRunner
    from repo_atlas.eval.judge import GatewayJudge
    from repo_atlas.eval.oracle import store_exists_fn
    from repo_atlas.eval.harness import run_eval
    from repo_atlas.eval.report import render_scorecard
    from repo_atlas.registry import load_registry

    cfg = load_config(os.environ)
    tasks = load_tasks(args.tasks)
    if args.limit:
        tasks = tasks[:args.limit]
    if not tasks:
        print(f"repo_atlas eval: no tasks in {args.tasks}")
        return 2
    store = Store(cfg.db_path)
    registry = {e.name: e.repo_path
                for e in load_registry(os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))}
    runner = ClaudeRunner(registry, args.mcp_config or "")
    if args.scorer in ("grounding", "grounded-use"):
        from repo_atlas.eval.grounding_scorer import GroundingScorer, GroundedUseScorer
        judge = GroundedUseScorer() if args.scorer == "grounded-use" else GroundingScorer()
    else:
        judge = GatewayJudge(cfg.base_url, cfg.api_key,
                             os.environ.get("REPO_ATLAS_JUDGE_MODEL", "deepseek-chat"))
    oracles = {name: store_exists_fn(store, name) for name in registry}

    sc = asyncio.run(run_eval(
        tasks, runner, judge,
        exists_fn=lambda s: any(o(s) for o in oracles.values())))
    md = render_scorecard(sc)
    with open(args.out, "w") as fh:
        fh.write(md)
    print(md)
    print(f"\nwrote {args.out}")
    return 0


def _run_eval_arms(args) -> int:
    from repo_atlas.config import load_config
    from repo_atlas.store import Store
    from repo_atlas.embed import GatewayEmbedder
    from repo_atlas.eval.tasks import load_tasks
    from repo_atlas.eval.runner import ClaudeRunner
    from repo_atlas.eval.grounding_scorer import GroundingScorer, GroundedUseScorer
    from repo_atlas.eval.oracle import store_exists_fn
    from repo_atlas.eval.harness import run_multi_eval
    from repo_atlas.eval.correlation import compute_proxy, correlate
    from repo_atlas.eval.offline.retriever import OfflineRetriever
    from repo_atlas.eval.report import render_multi_scorecard
    from repo_atlas.registry import load_registry

    cfg = load_config(os.environ)
    tasks = load_tasks(args.tasks)
    if args.limit:
        tasks = tasks[:args.limit]
    if not tasks:
        print(f"repo_atlas eval-arms: no tasks in {args.tasks}")
        return 2
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    store = Store(cfg.db_path)
    embedder = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    registry = {e.name: e.repo_path
                for e in load_registry(os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))}
    retriever = OfflineRetriever(store, embedder)
    runner = ClaudeRunner(registry, args.mcp_config or "", retriever=retriever,
                          timeout=args.timeout, inject_k=args.inject_k)
    oracles = {name: store_exists_fn(store, name, repo_path=registry[name]) for name in registry}

    def exists(sym: str) -> bool:
        return any(o(sym) for o in oracles.values())

    scorer = GroundedUseScorer() if args.scorer == "grounded-use" else GroundingScorer()
    sc = asyncio.run(run_multi_eval(tasks, runner, arms, scorer, exists))
    proxy = asyncio.run(compute_proxy(tasks, retriever, k=args.proxy_k))
    corrs = [correlate(proxy, sc, a) for a in arms]
    md = render_multi_scorecard(sc, corrs)
    with open(args.out, "w") as fh:
        fh.write(md)
    print(md)
    print(f"\nwrote {args.out}")
    return 0


def _run_eval_offline(args) -> int:
    import asyncio as _aio

    from repo_atlas.config import load_config
    from repo_atlas.store import Store
    from repo_atlas.embed import GatewayEmbedder
    from repo_atlas.eval.offline.cases import load_retrieval_cases, load_grounding_cases
    from repo_atlas.eval.offline.retriever import OfflineRetriever
    from repo_atlas.eval.offline.harness import run_retrieval, run_grounding
    from repo_atlas.eval.offline.report import render_offline_scorecard

    cfg = load_config(os.environ)
    ks = tuple(int(x) for x in args.k.split(","))
    store = Store(cfg.db_path)
    embedder = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    retriever = OfflineRetriever(store, embedder)

    rret = gret = None
    if args.layer in ("retrieval", "all"):
        rcases = load_retrieval_cases(os.path.join(args.cases, "retrieval"))
        rret = _aio.run(run_retrieval(rcases, retriever, ks=ks))
    if args.layer in ("grounding", "all"):
        gcases = load_grounding_cases(os.path.join(args.cases, "grounding"))
        gret = run_grounding(gcases, retriever)

    md = render_offline_scorecard(rret, gret, embed_model=cfg.embed_model, db_path=cfg.db_path)
    with open(args.out, "w") as fh:
        fh.write(md)
    print(md)
    print(f"\nwrote {args.out}")
    return 0


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "index":
        return _run_index(args)
    if args.cmd == "eval":
        return _run_eval(args)
    if args.cmd == "eval-offline":
        return _run_eval_offline(args)
    if args.cmd == "eval-arms":
        return _run_eval_arms(args)
    from repo_atlas.server import main as serve_main
    serve_main()
    return 0
