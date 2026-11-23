"""Dense embeddings with fastembed (ONNX, BAAI/bge-small-en-v1.5, 384 dimensions).

The same model embeds passages at index time and queries at search time. Passage vectors are cached in
`data/corpus/index/embeddings.npz` keyed by the sha256 of the embedded text, so re-indexing an unchanged
corpus needs no model run; a query always runs the model.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

from sgw.agent.rag.corpus import CORPUS_DIR, REPO_ROOT, sha256_text

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384
CACHE_FILE = CORPUS_DIR / "index" / "embeddings.npz"


class Embedder(Protocol):
    def passages(self, texts: Sequence[str]) -> np.ndarray: ...

    def query(self, text: str) -> np.ndarray: ...


def model_cache_dir() -> Path:
    """`SGW_FASTEMBED_CACHE`, else fastembed's own `FASTEMBED_CACHE_PATH` (the python image bakes the model
    into `/opt/models` and sets it, so the read-only container never writes), else `var/models/fastembed`."""
    for env in ("SGW_FASTEMBED_CACHE", "FASTEMBED_CACHE_PATH"):
        if os.environ.get(env):
            return Path(os.environ[env])
    return REPO_ROOT / "var" / "models" / "fastembed"


class FastEmbedder:
    def __init__(self, model_name: str = MODEL_NAME) -> None:
        from fastembed import TextEmbedding

        cache = model_cache_dir()
        if not cache.is_dir():
            cache.mkdir(parents=True, exist_ok=True)
        self.model = TextEmbedding(model_name=model_name, cache_dir=str(cache), threads=2)

    def passages(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        return np.asarray(list(self.model.passage_embed(list(texts), batch_size=32)), dtype=np.float32)

    def query(self, text: str) -> np.ndarray:
        return np.asarray(next(iter(self.model.query_embed(text))), dtype=np.float32)


@lru_cache(maxsize=1)
def default_embedder() -> FastEmbedder:
    return FastEmbedder()


class CachedPassages:
    """Passage vectors by text hash; misses are embedded and added."""

    def __init__(self, path: Path = CACHE_FILE) -> None:
        self.path = path
        self.vectors: dict[str, np.ndarray] = {}
        if path.is_file():
            with np.load(path) as data:
                for key, vec in zip(data["keys"], data["vectors"], strict=True):
                    self.vectors[str(key)] = vec.astype(np.float32)

    def embed(self, texts: Sequence[str], embedder: Embedder | None) -> np.ndarray:
        keys = [sha256_text(t) for t in texts]
        missing = [i for i, k in enumerate(keys) if k not in self.vectors]
        if missing:
            if embedder is None:
                raise RuntimeError(
                    f"{len(missing)} passages not in the embedding cache and no embedder given"
                )
            fresh = embedder.passages([texts[i] for i in missing])
            for i, vec in zip(missing, fresh, strict=True):
                self.vectors[keys[i]] = vec
        return np.stack([self.vectors[k] for k in keys]) if keys else np.zeros((0, DIM), dtype=np.float32)

    def save(self, keep: Sequence[str] | None = None) -> None:
        keys = sorted(self.vectors if keep is None else {sha256_text(t) for t in keep})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            self.path,
            keys=np.array(keys),
            vectors=np.stack([self.vectors[k] for k in keys]).astype(np.float16),
        )


def to_pgvector(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec.tolist()) + "]"
