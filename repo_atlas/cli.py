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


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "index":
        return _run_index(args)
    from repo_atlas.server import main as serve_main
    serve_main()
    return 0
