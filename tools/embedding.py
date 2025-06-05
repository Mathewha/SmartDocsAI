from typing import List, Dict, Any
import numpy as np
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch
from django.conf import settings

# Initialize the sentence transformer model
model = SentenceTransformer('all-MiniLM-L6-v2')


def get_embedding(text: str) -> List[float]:
    """Generate embeddings for a given text using the sentence transformer model."""
    return model.encode(text).tolist()


def create_semantic_search_body(query: str, lang: str | None, is_section: bool = False) -> Dict[str, Any]:
    """Create the OpenSearch query body for semantic search."""
    # Get the embedding for the query
    query_embedding = get_embedding(query)

    # Create the k-NN query
    # Build the basic k-NN query body using OpenSearch syntax
    knn_query: Dict[str, Any] = {
        "size": settings.MAX_HITS,
        "query": {
            "knn": {
                "field": "embedding",
                "query_vector": query_embedding,
                "k": settings.MAX_HITS,
                "num_candidates": settings.MAX_HITS * 10,
            }
        },
        "_source": {"excludes": ["embedding"]},  # Exclude raw vectors from results
    }

    # Add language filter if specified
    if lang in {"pl", "en"}:
        knn_query["query"]["knn"]["filter"] = {"term": {"language": lang}}

    return knn_query


def semantic_search(client: OpenSearch, query: str, lang: str | None, is_section: bool = False) -> Dict[str, Any]:
    """Perform semantic search using vector similarity."""
    index_name = settings.OPENSEARCH["SECTION_INDEX"] if is_section else settings.OPENSEARCH["DOC_INDEX"]
    body = create_semantic_search_body(query, lang, is_section)
    return client.search(index=index_name, body=body)