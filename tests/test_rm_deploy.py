"""Tests for the CBM deployment/config layer (resolver + client passthrough + wiring)."""

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
