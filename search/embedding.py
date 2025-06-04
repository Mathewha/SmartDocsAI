from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_model = SentenceTransformer(MODEL_NAME)

def embed_text(text: str) -> list[float]:
    """Return the embedding vector for a single text snippet."""
    return _model.encode([text])[0].tolist()
