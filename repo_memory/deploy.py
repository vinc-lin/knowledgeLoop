"""Resolve a CBM launch spec (command/env/cwd) per deployment profile.

Pure: reads only the `environ` passed in (defaulting to os.environ). No file IO.
This is how repo_memory injects per-deployment settings into the CBM subprocess
without forking CBM. See docs/superpowers/specs/2026-06-14-repo-memory-cbm-deploy-config-design.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# The version that resolves on the package index. NOTE: the CBM repo's server.json says 0.7.0 and
# the local git tag is v0.8.0, but the index publishes 0.8.1 (0.7.0/0.8.0 do not resolve via uvx).
DEFAULT_CBM_VERSION = "0.8.1"

# Vars CBM reads that the MCP SDK's clean-env merge may not carry; preserve those present.
PRESERVE_ENV = ("HOME", "XDG_CONFIG_HOME", "APPDATA", "LOCALAPPDATA",
                "PATH", "TMP", "TEMP", "USERPROFILE")

# Raw CBM_* knobs honored if present in the environment (passed straight through, env > profile).
KNOBS = ("CBM_CACHE_DIR", "CBM_WORKERS", "CBM_LOG_LEVEL", "CBM_DIAGNOSTICS",
         "CBM_SEMANTIC_ENABLED", "CBM_SEMANTIC_THRESHOLD", "CBM_LSP_DISABLED",
         "CBM_SQLITE_MMAP_SIZE")

# Declarative per-target profiles. "requires_cache_dir" => resolve fails if none supplied.
# "version" (optional) pins a CBM version for that profile (env override still wins).
PROFILES: dict = {
    "dev": {"requires_cache_dir": False, "env": {}},
    "ephemeral": {"requires_cache_dir": True, "env": {"CBM_LOG_LEVEL": "warn"}},
    "shared": {"requires_cache_dir": True,
               "env": {"CBM_SEMANTIC_ENABLED": "1", "CBM_SQLITE_MMAP_SIZE": "1073741824"}},
    "ci": {"requires_cache_dir": True, "env": {"CBM_LOG_LEVEL": "warn"}},
}


class DeployConfigError(RuntimeError):
    """A deployment profile cannot be resolved into a runnable launch spec."""


@dataclass(frozen=True)
class LaunchSpec:
    command: list
    env: dict
    cwd: Optional[str] = None


def _command(environ: dict, profile: dict) -> list:
    override = environ.get("REPO_MEMORY_CBM_COMMAND")
    if override:
        return str(override).split()
    version = (environ.get("REPO_MEMORY_CBM_VERSION")
               or profile.get("version")
               or DEFAULT_CBM_VERSION)
    return ["uvx", f"codebase-memory-mcp@{version}"]


def resolve_launch_spec(profile_name: Optional[str] = None,
                        environ: Optional[dict] = None,
                        *, cache_dir: Optional[str] = None) -> LaunchSpec:
    if environ is None:
        environ = dict(os.environ)
    name = profile_name or environ.get("REPO_MEMORY_CBM_PROFILE") or "dev"
    if name not in PROFILES:
        raise DeployConfigError(
            f"unknown CBM profile '{name}'; known: {', '.join(sorted(PROFILES))}")
    profile = PROFILES[name]

    # precedence: profile env -> raw CBM_* from environ -> explicit cache_dir arg
    env: dict = dict(profile["env"])
    for knob in KNOBS:
        if knob in environ:
            env[knob] = environ[knob]
    if cache_dir is not None:
        env["CBM_CACHE_DIR"] = cache_dir

    if profile.get("requires_cache_dir") and not env.get("CBM_CACHE_DIR"):
        raise DeployConfigError(
            f"profile '{name}' requires a cache dir; set CBM_CACHE_DIR or pass cache_dir=")

    # drop an invalid worker count rather than spawn CBM with a bad value
    if "CBM_WORKERS" in env:
        try:
            n = int(env["CBM_WORKERS"])
            if not (1 <= n <= 256):
                raise ValueError
        except (ValueError, TypeError):
            env.pop("CBM_WORKERS")

    # preserve vars CBM needs that the SDK clean-env merge may drop
    for var in PRESERVE_ENV:
        if var in environ and var not in env:
            env[var] = environ[var]

    return LaunchSpec(command=_command(environ, profile), env=env,
                      cwd=environ.get("REPO_MEMORY_CBM_CWD"))
