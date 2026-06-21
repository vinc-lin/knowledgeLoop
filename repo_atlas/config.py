from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AtlasConfig:
    base_url: str
    api_key: str
    embed_model: str
    db_path: str
    symbol_ratio: float = 0.5


def _codewiki_creds() -> tuple[Optional[str], Optional[str]]:
    """Best-effort base_url + api_key from codewiki's stored config (default only)."""
    try:
        from codewiki.cli.config_manager import ConfigManager
        cm = ConfigManager()
        cm.load()
        cfg = cm.get_config()
        base = getattr(cfg, "base_url", None) if cfg else None
        return base, cm.get_api_key()
    except Exception:
        return None, None


def _parse_ratio(raw) -> float:
    """Clamp REPO_ATLAS_SYMBOL_RATIO to [0,1]; fall back to 0.5 on missing/garbage."""
    try:
        return min(1.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 0.5


def load_config(environ: Optional[dict] = None) -> AtlasConfig:
    env = environ if environ is not None else os.environ
    cw_base, cw_key = (None, None)
    base_url = env.get("REPO_ATLAS_BASE_URL")
    api_key = env.get("REPO_ATLAS_API_KEY")
    if base_url is None or api_key is None:
        cw_base, cw_key = _codewiki_creds()
    return AtlasConfig(
        base_url=base_url or cw_base or "",
        api_key=api_key or cw_key or "",
        embed_model=env.get("REPO_ATLAS_EMBED_MODEL", ""),
        db_path=env.get("REPO_ATLAS_DB", os.path.expanduser("~/.repo_atlas/atlas.db")),
        symbol_ratio=_parse_ratio(env.get("REPO_ATLAS_SYMBOL_RATIO")),
    )
