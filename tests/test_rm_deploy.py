"""Tests for the CBM deployment/config layer (resolver + client passthrough + wiring)."""

import os

import pytest

from repo_memory.deploy import (
    DEFAULT_CBM_VERSION, DeployConfigError, LaunchSpec, resolve_launch_spec)
from repo_memory.graph.client import CBMClient


def test_cbmclient_sets_env_and_cwd_on_params():
    client = CBMClient(["mybin", "--flag"], env={"CBM_CACHE_DIR": "/tmp/x"}, cwd="/repo")
    assert client._params.command == "mybin"
    assert client._params.args == ["--flag"]
    assert client._params.env == {"CBM_CACHE_DIR": "/tmp/x"}
    assert client._params.cwd == "/repo"


def test_cbmclient_env_and_cwd_default_to_none():
    client = CBMClient(["mybin"])
    assert client._params.env is None
    assert client._params.cwd is None


def test_default_profile_is_dev_with_pinned_command():
    spec = resolve_launch_spec(environ={})
    assert isinstance(spec, LaunchSpec)
    assert spec.command == ["uvx", f"codebase-memory-mcp@{DEFAULT_CBM_VERSION}"]
    assert "CBM_CACHE_DIR" not in spec.env
    assert spec.cwd is None


def test_preserve_env_carries_through():
    spec = resolve_launch_spec(environ={"HOME": "/h", "PATH": "/b", "IGNORED": "x"})
    assert spec.env["HOME"] == "/h"
    assert spec.env["PATH"] == "/b"
    assert "IGNORED" not in spec.env


def test_raw_cbm_knob_passthrough():
    spec = resolve_launch_spec("dev", environ={"CBM_LOG_LEVEL": "debug"})
    assert spec.env["CBM_LOG_LEVEL"] == "debug"


def test_profile_env_applied():
    spec = resolve_launch_spec("ephemeral", environ={}, cache_dir="/t")
    assert spec.env["CBM_LOG_LEVEL"] == "warn"
    assert spec.env["CBM_CACHE_DIR"] == "/t"


def test_env_overrides_profile():
    spec = resolve_launch_spec("ephemeral", environ={"CBM_LOG_LEVEL": "error"}, cache_dir="/t")
    assert spec.env["CBM_LOG_LEVEL"] == "error"  # env > profile


def test_cache_dir_arg_wins_over_env():
    spec = resolve_launch_spec("ephemeral", environ={"CBM_CACHE_DIR": "/a"}, cache_dir="/b")
    assert spec.env["CBM_CACHE_DIR"] == "/b"


def test_requires_cache_dir_raises():
    with pytest.raises(DeployConfigError):
        resolve_launch_spec("ephemeral", environ={})


def test_unknown_profile_raises():
    with pytest.raises(DeployConfigError):
        resolve_launch_spec("nope", environ={})


def test_command_override_splits():
    spec = resolve_launch_spec("dev", environ={"REPO_MEMORY_CBM_COMMAND": "/opt/cbm --foo"})
    assert spec.command == ["/opt/cbm", "--foo"]


def test_version_override():
    spec = resolve_launch_spec("dev", environ={"REPO_MEMORY_CBM_VERSION": "9.9.9"})
    assert spec.command == ["uvx", "codebase-memory-mcp@9.9.9"]


def test_invalid_workers_dropped_valid_kept():
    bad = resolve_launch_spec("dev", environ={"CBM_WORKERS": "0"})
    assert "CBM_WORKERS" not in bad.env
    good = resolve_launch_spec("dev", environ={"CBM_WORKERS": "4"})
    assert good.env["CBM_WORKERS"] == "4"


def test_profile_selected_from_environ():
    spec = resolve_launch_spec(
        environ={"REPO_MEMORY_CBM_PROFILE": "ephemeral", "CBM_CACHE_DIR": "/t"})
    assert spec.env["CBM_CACHE_DIR"] == "/t"
    assert spec.env["CBM_LOG_LEVEL"] == "warn"


def test_build_app_accepts_cbm_env_and_cwd(tmp_path):
    from repo_memory.server import build_app
    app = build_app(wiki_dir=str(tmp_path), entity_map_path=str(tmp_path / "em.json"),
                    cbm_command=["uvx", "cbm@x"], cbm_env={"CBM_CACHE_DIR": "/t"}, cbm_cwd=None)
    assert app is not None


def test_main_wires_resolved_spec_into_build_app(monkeypatch):
    import repo_memory.server as srv
    from repo_memory.deploy import LaunchSpec
    captured = {}

    class FakeApp:
        def run(self, **kw):
            captured["transport"] = kw.get("transport")

    monkeypatch.setattr(srv, "build_app", lambda **kw: (captured.update(kw) or FakeApp()))
    monkeypatch.setattr(srv, "resolve_launch_spec",
                        lambda **kw: LaunchSpec(command=["uvx", "cbm@x"],
                                                env={"CBM_CACHE_DIR": "/t"}, cwd=None))
    monkeypatch.setenv("REPO_MEMORY_WIKI_DIR", "docs")
    srv.main()

    assert captured["cbm_command"] == ["uvx", "cbm@x"]
    assert captured["cbm_env"] == {"CBM_CACHE_DIR": "/t"}
    assert captured["cbm_cwd"] is None
    assert captured["transport"] == "stdio"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_injected_cache_dir_is_used(tmp_path):
    """CBM started via the resolved spec writes its index under the injected CBM_CACHE_DIR."""
    import shutil

    if shutil.which("uvx") is None:
        pytest.skip("uvx not available")

    # a tiny repo to index
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def hello():\n    return 1\n")

    cache = tmp_path / "cbm-cache"
    spec = resolve_launch_spec("ephemeral", environ=dict(os.environ), cache_dir=str(cache))

    client = CBMClient(spec.command, env=spec.env, cwd=spec.cwd)
    try:
        await client.start()
    except Exception as exc:
        pytest.skip(f"CBM unavailable: {exc}")
    try:
        await client.call_tool_with_restart("index_repository", {"repo_path": str(repo)})
    finally:
        await client.aclose()

    # CBM created its store under the injected cache dir, not the default ~/.cache location
    assert cache.exists()
    assert any(cache.rglob("*")), "expected CBM to write its index under the injected CBM_CACHE_DIR"
