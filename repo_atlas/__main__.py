"""`python -m repo_atlas [serve|index ...]` -> the cross-repo CLI.

No subcommand (or `serve`) launches the MCP server over stdio; `index` populates
the store. See `repo_atlas.cli`.
"""
import sys

from repo_atlas.cli import main

if __name__ == "__main__":
    sys.exit(main())
