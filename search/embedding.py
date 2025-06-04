from __future__ import annotations

from typing import List
import hashlib

DIMENSION = 384

try:
    from sentence_transformers import SentenceTransformer
    _MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
except Exception:  # library missing or model unavailable
    _MODEL = None

def _fallback(text: str) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vals = list(digest)
    reps = (DIMENSION + len(vals) - 1) // len(vals)
    vec = (vals * reps)[:DIMENSION]
    return [float(v) for v in vec]

def embed_text(text: str) -> List[float]:
    if _MODEL is not None:
        try:
            return _MODEL.encode(text).tolist()
        except Exception:
            pass
    return _fallback(text)
