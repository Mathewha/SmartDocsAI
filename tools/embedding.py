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

    # Build the k-NN query using the classic ``embedding``/``vector`` syntax
    # supported by older versions of OpenSearch. This keeps compatibility with
    # deployments that haven't upgraded to the newer ``query_vector`` format.
    base_query = {
        "knn": {
            "embedding": {
                "vector": query_embedding,
                "k": settings.MAX_HITS,
            }
        }
    }

    knn_query: Dict[str, Any] = {
        "size": settings.MAX_HITS,
        "query": base_query,
        "_source": {"excludes": ["embedding"]},
    }

    # Add language filter if specified
    if lang in {"pl", "en"}:
        knn_query["query"] = {
            "bool": {
                "must": [base_query, {"term": {"language": lang}}]
            }
        }

    return knn_query


def semantic_search(client: OpenSearch, query: str, lang: str | None, is_section: bool = False) -> Dict[str, Any]:
    """Perform semantic search using vector similarity."""
    index_name = settings.OPENSEARCH["SECTION_INDEX"] if is_section else settings.OPENSEARCH["DOC_INDEX"]
    body = create_semantic_search_body(query, lang, is_section)
    return client.search(index=index_name, body=body)
