#!/usr/bin/env bash
# Lap-7 outcome-driven flywheel: 3-arm agentic eval + proxy<->outcome correlation.
#
# Produces a scorecard with, per arm (control/optional/forced-inject/mandatory-call):
# grounded-success, adoption rate, surfaced rate; the three arm contrasts
# (forced-control = knowledge ceiling, optional-control = captured today,
# forced-optional = adoption tax); and the proxy->outcome correlation
# (does the offline symbol-rank proxy predict per-arm grounded-success?).
#
# PRECONDITIONS (all must hold at run time; the preflight checks each):
#   1. the `claude` CLI on PATH                 -> the agent under test
#   2. a live /v1/embeddings endpoint serving   -> embeds task queries; MUST be the
#      the SAME model the index was built with     same model (bge-m3) used to build the index
#   3. a leaner-enriched atlas index            -> atlas-leaner.db (body_lines=3, lap-6b default)
#
# Everything is parameterized via env with eval-dir defaults; override any of them inline, e.g.
#   ARMS=control,forced-inject LIMIT=2 bash scripts/run_eval_arms.sh   # quick 2-task smoke
set -euo pipefail

# --- locations -------------------------------------------------------------
REPO="${REPO:-/mnt/x/code/knowledgeLoop}"                 # repo on master (durable; not the worktree)
PY="${PY:-$REPO/.venv/bin/python}"
EVAL_DIR="${EVAL_DIR:-/home/vinc/repo-atlas-eval-full}"

# --- repo_atlas config (consumed by load_config + the eval-arms CLI) -------
# REPO_ATLAS_DB drives the OFFLINE retriever (proxy + forced-inject); MCP_CONFIG drives the
# agent's MCP server (optional/mandatory-call arms). Both point at the SAME leaner db so the
# four arms differ only in HOW the knowledge reaches the agent, not in WHAT it is.
export REPO_ATLAS_DB="${REPO_ATLAS_DB:-$EVAL_DIR/atlas-leaner.db}"
export REPO_ATLAS_REGISTRY="${REPO_ATLAS_REGISTRY:-$EVAL_DIR/atlas.toml}"
export REPO_ATLAS_BASE_URL="${REPO_ATLAS_BASE_URL:-http://127.0.0.1:11434/v1}"
export REPO_ATLAS_API_KEY="${REPO_ATLAS_API_KEY:-local}"
export REPO_ATLAS_EMBED_MODEL="${REPO_ATLAS_EMBED_MODEL:-bge-m3}"

# --- eval-arms knobs -------------------------------------------------------
TASKS="${TASKS:-$REPO/repo_atlas/eval/tasks-grounding}"   # the finding-bottleneck task set
MCP_CONFIG="${MCP_CONFIG:-$EVAL_DIR/mcp-leaner.json}"      # MCP server -> the SAME leaner db
ARMS="${ARMS:-control,optional,forced-inject,mandatory-call}"
PROXY_K="${PROXY_K:-10}"
LIMIT="${LIMIT:-0}"                                        # 0 = all tasks
OUT="${OUT:-$EVAL_DIR/eval-arms-scorecard.md}"

# --- preflight -------------------------------------------------------------
fail() { echo "PRECONDITION FAILED: $*" >&2; exit 1; }
command -v claude >/dev/null 2>&1 || fail "the 'claude' CLI is not on PATH (the agent under test)"
[ -x "$PY" ] || fail "venv python not found at $PY (create per CLAUDE.md, or set PY=...)"
[ -f "$REPO_ATLAS_DB" ] || fail "index not found: $REPO_ATLAS_DB
  build a leaner-enriched index (body_lines=3 is now the default):
    REPO_ATLAS_DB=$REPO_ATLAS_DB REPO_ATLAS_REGISTRY=$REPO_ATLAS_REGISTRY \\
    REPO_ATLAS_BASE_URL=$REPO_ATLAS_BASE_URL REPO_ATLAS_EMBED_MODEL=$REPO_ATLAS_EMBED_MODEL \\
    $PY -m repo_atlas index --all"
[ -f "$REPO_ATLAS_REGISTRY" ] || fail "registry not found: $REPO_ATLAS_REGISTRY"
[ -f "$MCP_CONFIG" ] || fail "mcp config not found: $MCP_CONFIG"
[ -d "$TASKS" ] || fail "tasks dir not found: $TASKS"

# embeddings endpoint reachable AND serving the expected model?
if ! curl -sf -m 8 -X POST "$REPO_ATLAS_BASE_URL/embeddings" \
      -H 'content-type: application/json' \
      -d "{\"input\":[\"ping\"],\"model\":\"$REPO_ATLAS_EMBED_MODEL\"}" >/dev/null 2>&1; then
  fail "embeddings endpoint not reachable at $REPO_ATLAS_BASE_URL/embeddings
  start the bge-m3 GPU server (must serve the SAME model the index was built with):
    /tmp/bge-venv/bin/python $EVAL_DIR/bge_embed_server.py 11434 &
  if /tmp/bge-venv is gone (it is ephemeral), recreate it:
    uv venv --python 3.12 /tmp/bge-venv && \\
    uv pip install --python /tmp/bge-venv/bin/python sentence-transformers
  (weights are cached at ~/.cache/huggingface/hub/models--BAAI--bge-m3)"
fi

echo "== eval-arms (lap-7 outcome-driven flywheel) =="
echo "  index      = $REPO_ATLAS_DB"
echo "  registry   = $REPO_ATLAS_REGISTRY"
echo "  embeddings = $REPO_ATLAS_BASE_URL  (model: $REPO_ATLAS_EMBED_MODEL)"
echo "  tasks      = $TASKS"
echo "  mcp-config = $MCP_CONFIG"
echo "  arms       = $ARMS"
echo "  proxy-k    = $PROXY_K   limit = $LIMIT (0=all)"
echo "  out        = $OUT"
echo "  NOTE: each task runs once PER ARM via 'claude -p' (up to 900s/run). All arms x all"
echo "        tasks is a lot of agent runs — smoke first with ARMS=control,forced-inject LIMIT=2."
echo

# --- run -------------------------------------------------------------------
cd "$REPO"
exec "$PY" -m repo_atlas eval-arms \
  --tasks "$TASKS" \
  --mcp-config "$MCP_CONFIG" \
  --arms "$ARMS" \
  --proxy-k "$PROXY_K" \
  --limit "$LIMIT" \
  --out "$OUT"
