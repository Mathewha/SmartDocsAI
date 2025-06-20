"""
Simple semantic search using chunked documents.
This replaces the complex semantic_search.py with a streamlined approach.
"""

import logging
from typing import Any, Dict, List, Optional

from opensearchpy import OpenSearch
from .embeddings import encode_query_for_search

logger = logging.getLogger(__name__)

# Simple configuration
SEMANTIC_INDEX = "ndoc_semantic_chunks"
DEFAULT_SIZE = 5
SNIPPET_LENGTH = 300


def search_semantic_chunks(
    client: OpenSearch,
    query: str,
    lang: Optional[str] = None,
    size: int = DEFAULT_SIZE,
    offset: int = 0
) -> Dict[str, Any]:
    """
    Search semantic chunks using vector similarity.
    
    Args:
        client: OpenSearch client
        query: Search query
        lang: Language filter (en/pl)
        size: Number of results
        offset: Pagination offset
        
    Returns:
        OpenSearch response
    """
    if not query.strip():
        return {"hits": {"total": {"value": 0}, "hits": []}}
    
    try:
        # Get query embedding
        query_vector = encode_query_for_search(query)
        
        # Build search query
        search_body = {
            "size": size,
            "from": offset,
            "_source": {
                "excludes": ["content_vector"]  # Don't return the vector
            },
            "query": {
                "knn": {
                    "content_vector": {
                        "vector": query_vector,
                        "k": size + offset
                    }
                }
            }
        }
        
        # Add language filter
        if lang in {"en", "pl"}:
            search_body["query"] = {
                "bool": {
                    "must": [search_body["query"]],
                    "filter": [{"term": {"language": lang}}]
                }
            }
        
        # Add highlighting for keyword matches in content
        search_body["highlight"] = {
            "fields": {
                "content": {
                    "fragment_size": SNIPPET_LENGTH,
                    "number_of_fragments": 2
                },
                "doc_title": {
                    "fragment_size": 100,
                    "number_of_fragments": 1
                }
            },
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
            "require_field_match": False
        }
        
        logger.info(f"Semantic search query: '{query[:50]}...'")
        response = client.search(index=SEMANTIC_INDEX, body=search_body)
        
        return response
        
    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        return {"hits": {"total": {"value": 0}, "hits": []}}


def format_chunk_hit(hit: Dict[str, Any], query: str) -> Dict[str, Any]:
    """
    Format a chunk search hit for display.
    
    Args:
        hit: OpenSearch hit
        query: Original query
        
    Returns:
        Formatted hit dictionary
    """
    source = hit.get("_source", {})
    highlight = hit.get("highlight", {})
    
    # Build title
    doc_title = source.get("doc_title", "")
    file_name = source.get("file_name", "")
    title = f"{doc_title} / {file_name}" if doc_title and file_name else doc_title or file_name
    
    # Build snippet from content or highlight
    content = source.get("content", "")
    if highlight.get("content"):
        snippet = " ... ".join(highlight["content"])
    elif content:
        # Truncate content if no highlight
        snippet = content[:SNIPPET_LENGTH] + "..." if len(content) > SNIPPET_LENGTH else content
    else:
        snippet = source.get("doc_summary", "")
    
    # Build href
    path = source.get("path", "")
    href = f"/docs/{path}?highlight={query}" if path else "#"
    
    # Build metadata
    meta_parts = []
    if source.get("language"):
        meta_parts.append(f"Language: {source['language']}")
    if source.get("chunk_index") is not None:
        meta_parts.append(f"Chunk: {source['chunk_index'] + 1}")
    if source.get("content_length"):
        meta_parts.append(f"Length: {source['content_length']} chars")
    
    return {
        "title": title,
        "snippet": snippet,
        "href": href,
        "meta": " | ".join(meta_parts),
        "icon": '<i class="bi bi-file-text"></i>',
        "score": hit.get("_score", 0)
    }


def hybrid_search_chunks(
    client: OpenSearch,
    query: str,
    lang: Optional[str] = None,
    size: int = DEFAULT_SIZE,
    offset: int = 0,
    semantic_weight: float = 0.7
) -> Dict[str, Any]:
    """
    Perform hybrid search combining semantic and keyword search on chunks.
    
    Args:
        client: OpenSearch client
        query: Search query
        lang: Language filter
        size: Number of results
        offset: Pagination offset
        semantic_weight: Weight for semantic vs keyword (0.0-1.0)
        
    Returns:
        OpenSearch response
    """
    if not query.strip():
        return {"hits": {"total": {"value": 0}, "hits": []}}
    
    try:
        # Get query embedding
        query_vector = encode_query_for_search(query)
        
        # Build hybrid query
        search_body = {
            "size": size,
            "from": offset,
            "_source": {
                "excludes": ["content_vector"]
            },
            "query": {
                "bool": {
                    "should": [
                        # Semantic component
                        {
                            "knn": {
                                "content_vector": {
                                    "vector": query_vector,
                                    "k": size + offset,
                                    "boost": semantic_weight
                                }
                            }
                        },
                        # Keyword component
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["doc_title^3", "content"],
                                "operator": "and",
                                "fuzziness": "AUTO",
                                "boost": 1.0 - semantic_weight
                            }
                        }
                    ],
                    "minimum_should_match": 1
                }
            }
        }
        
        # Add language filter
        if lang in {"en", "pl"}:
            if "filter" not in search_body["query"]["bool"]:
                search_body["query"]["bool"]["filter"] = []
            search_body["query"]["bool"]["filter"].append({"term": {"language": lang}})
        
        # Add highlighting
        search_body["highlight"] = {
            "fields": {
                "content": {
                    "fragment_size": SNIPPET_LENGTH,
                    "number_of_fragments": 2
                },
                "doc_title": {
                    "fragment_size": 100,
                    "number_of_fragments": 1
                }
            },
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
            "require_field_match": False
        }
        
        logger.info(f"Hybrid search query: '{query[:50]}...'")
        response = client.search(index=SEMANTIC_INDEX, body=search_body)
        
        return response
        
    except Exception as e:
        logger.error(f"Hybrid search failed: {e}")
        return {"hits": {"total": {"value": 0}, "hits": []}}


def get_chunk_suggestions(client: OpenSearch, query: str, lang: Optional[str] = None) -> List[str]:
    """
    Get search suggestions based on chunk content.
    
    Args:
        client: OpenSearch client
        query: Partial query
        lang: Language filter
        
    Returns:
        List of suggestions
    """
    try:
        suggest_body = {
            "suggest": {
                "chunk_suggest": {
                    "text": query,
                    "phrase": {
                        "field": "content",
                        "size": 5,
                        "real_word_error_likelihood": 0.95,
                        "max_errors": 2
                    }
                }
            }
        }
        
        if lang in {"en", "pl"}:
            suggest_body["query"] = {"term": {"language": lang}}
        
        response = client.search(index=SEMANTIC_INDEX, body=suggest_body)
        
        suggestions = []
        suggest_data = response.get("suggest", {}).get("chunk_suggest", [])
        for suggest_group in suggest_data:
            for option in suggest_group.get("options", []):
                text = option.get("text", "")
                if text and text not in suggestions:
                    suggestions.append(text)
        
        return suggestions[:5]  # Return top 5 suggestions
        
    except Exception as e:
        logger.error(f"Failed to get suggestions: {e}")
        return []