from __future__ import annotations

import hashlib
import math
from typing import Protocol


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class StubEmbedder:
    """Deterministic hash-based vectors for offline tests (no semantics)."""
    def __init__(self, dim: int = 16):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in t.split():
                h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
                v[h % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class GatewayEmbedder:
    """Calls an OpenAI-compatible /v1/embeddings endpoint (GPU-served gateway).

    Retries each batch on transient failures (5xx / transport errors) with backoff,
    so a single gateway hiccup mid-index doesn't abort the whole run."""
    def __init__(self, base_url: str, api_key: str, model: str, batch: int = 64,
                 timeout: float = 60.0, retries: int = 4):
        self.url = base_url.rstrip("/") + "/embeddings"
        self.api_key = api_key
        self.model = model
        self.batch = batch
        self.timeout = timeout
        self.retries = retries

    def _post_batch(self, chunk: list[str]) -> list[list[float]]:
        import time
        import httpx
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(self.retries):
            try:
                resp = httpx.post(self.url, headers=headers,
                                  json={"model": self.model, "input": chunk},
                                  timeout=self.timeout)
                resp.raise_for_status()
                return [item["embedding"] for item in resp.json()["data"]]
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                transient = isinstance(exc, httpx.TransportError) or (status or 0) >= 500
                if transient and attempt < self.retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("unreachable")

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            out.extend(self._post_batch(texts[i:i + self.batch]))
        return out
