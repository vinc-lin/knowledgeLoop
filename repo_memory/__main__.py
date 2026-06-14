"""`python -m repo_memory` → launch the grounded-MCP facade over stdio.

Equivalent to the `repo-memory` console script (both call `repo_memory.server:main`).
"""

from repo_memory.server import main

if __name__ == "__main__":
    main()
