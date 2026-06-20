import httpx
import pytest

from repo_atlas.embed import GatewayEmbedder, StubEmbedder


def test_stub_is_deterministic_and_shaped():
    e = StubEmbedder(dim=8)
    a = e.embed(["hello world", "other"])
    assert len(a) == 2 and all(len(v) == 8 for v in a)
    assert e.embed(["hello world"])[0] == a[0]      # deterministic


class _Resp:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=httpx.Request("POST", "http://x"),
                                        response=self)

    def json(self):
        return {"data": [{"embedding": [0.1, 0.2]}]}


def test_gateway_embedder_retries_on_5xx(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, **kw):
        calls["n"] += 1
        return _Resp(500 if calls["n"] == 1 else 200)   # fail once, then succeed

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    out = GatewayEmbedder("http://x/v1", "k", "m", retries=3).embed(["a"])
    assert out == [[0.1, 0.2]]
    assert calls["n"] == 2                              # one retry


def test_gateway_embedder_raises_on_4xx(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp(400))
    with pytest.raises(httpx.HTTPStatusError):
        GatewayEmbedder("http://x/v1", "k", "m", retries=3).embed(["a"])
