from __future__ import annotations

import pytest

from src.terrain.utils.embedder import EmbeddingClient, LocalHashEmbeddingClient


class _EmbeddingData:
    embedding = [0.1, 0.2, 0.3]


class _EmbeddingResponse:
    data = [_EmbeddingData()]


class _Embeddings:
    def __init__(self):
        self.params = None

    def create(self, **params):
        self.params = params
        return _EmbeddingResponse()


class _OpenAIStub:
    def __init__(self):
        self.embeddings = _Embeddings()


def test_default_embedding_client_uses_openai_text_embedding_3_large(monkeypatch):
    client = EmbeddingClient()
    stub = _OpenAIStub()
    monkeypatch.setattr(client, "_client", lambda: stub)

    vector = client.embed("semantic terrain")

    assert client.model == "text-embedding-3-large"
    assert vector == [0.1, 0.2, 0.3]
    assert stub.embeddings.params == {
        "model": "text-embedding-3-large",
        "input": "semantic terrain",
        "encoding_format": "float",
    }


def test_default_embedding_client_can_request_dimensions(monkeypatch):
    client = EmbeddingClient(dimensions=256)
    stub = _OpenAIStub()
    monkeypatch.setattr(client, "_client", lambda: stub)

    client.embed("semantic terrain")

    assert stub.embeddings.params["dimensions"] == 256
    assert client.hash("same text") != EmbeddingClient().hash("same text")


def test_default_embedding_client_requires_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required"):
        EmbeddingClient().embed("semantic terrain")


def test_local_hash_embedding_client_is_explicitly_local():
    client = LocalHashEmbeddingClient(dimensions=8)

    vector = client.embed("semantic terrain")

    assert client.model == "local-hash-v1"
    assert len(vector) == 8
    assert sum(value * value for value in vector) == pytest.approx(1.0)
