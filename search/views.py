from __future__ import annotations

import logging
from typing import Any, Dict, List

from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from opensearchpy import OpenSearch

from ndoc.opensearch import get_client  # helper
from .simple_semantic import search_semantic_chunks, hybrid_search_chunks, format_chunk_hit

logger = logging.getLogger(__name__)

INDEX_DOCS = "ndoc_documents"
INDEX_SECTIONS = "ndoc_sections"
MAX_HITS = 5  # liczba wyników na stronę
SNIPPET_LENGTH = 500  # maksymalna długość snippetów

# Search type constants
SEARCH_TYPE_STANDARD = "standard"
SEARCH_TYPE_SEMANTIC = "semantic"
SEARCH_TYPE_HYBRID = "hybrid"


def _get_snippet(
        src: Dict[str, Any],
        highlight: Dict[str, List[str]],
        eff_lang: str,
        query_present: bool,
        is_section: bool
) -> str:
    """Zwraca snippet: podsumowanie lub content z podświetleniem fragmentów."""
    field_base = 'content' if is_section else 'summary'

    # Try lang‐specific, then English, then Polish, then empty
    text = (
            src.get(f"{field_base}.{eff_lang}") or
            src.get(f"{field_base}.en") or
            src.get(f"{field_base}.pl") or
            ""
    )

    # Truncate if needed
    snippet = f"{text[:SNIPPET_LENGTH]}…" if text else ""

    if query_present and highlight:
        # Build prefixes: include doc_title only for sections
        prefixes = (["doc_title"] if is_section else []) + ["title", field_base]
        # Collect all matching fragments in prefix order
        frags: List[str] = []
        for pref in prefixes:
            for field, hits in highlight.items():
                if field.startswith(pref):
                    frags.extend(hits)
        if frags:
            snippet = " … ".join(frags)

    return snippet


def _query_block(
        query: str | None,
        lang: str | None,
        is_section: bool = False
) -> Dict[str, Any]:
    filters: List[Dict[str, Any]] = []
    if lang in {"pl", "en"}:
        filters.append({"term": {"language": lang}})
    if query:
        if is_section:
            bases = ["doc_title", "title", "content"]
        else:
            bases = ["title", "summary"]
        fields: List[str] = []
        for base in bases:
            if lang:
                fields.append(
                    f"{base}.{lang}^{3}" if base == 'title'
                    else f"{base}.{lang}"
                )
            else:
                fields.extend([
                    f"{base}.en^{3}" if base == 'title' else f"{base}.en",
                    f"{base}.pl^{3}" if base == 'title' else f"{base}.pl",
                ])

        # Use multi_match with fuzziness for better typo tolerance
        must = [{
            "multi_match": {
                "query": query,
                "fields": fields,
                "operator": "and",
                "fuzziness": "AUTO",  # Added fuzziness for typo tolerance
                "prefix_length": 1,  # Prevent too aggressive fuzzy matching
                "max_expansions": 50  # Limit expansions for performance
            }
        }]
        bool_q = {"must": must}
        if filters:
            bool_q["filter"] = filters
        return {"bool": bool_q}

    if filters:
        return {"bool": {"filter": filters}}
    return {"match_all": {}}


def _highlight_block(query_present: bool, is_section: bool = False) -> Dict[str, Any]:
    if not query_present:
        return {}

    if is_section:
        fields = {
            "title.*": {"fragment_size": SNIPPET_LENGTH // 2, "number_of_fragments": 1},
            "content.*": {"fragment_size": SNIPPET_LENGTH // 2, "number_of_fragments": 2},
            "doc_title.*": {"fragment_size": SNIPPET_LENGTH // 2, "number_of_fragments": 1},
        }
    else:
        fields = {
            "title.*": {"fragment_size": SNIPPET_LENGTH // 2, "number_of_fragments": 1},
            "summary.*": {"fragment_size": SNIPPET_LENGTH // 2, "number_of_fragments": 2},
        }

    return {
        "pre_tags": ["<mark>"],
        "post_tags": ["</mark>"],
        "fields": fields,
        "require_field_match": False,
    }


def _build_body(
        query: str | None,
        lang: str | None,
        is_section: bool = False
) -> Dict[str, Any]:
    return {"query": _query_block(query, lang, is_section)}


def _format_hit(
        hit: Dict[str, Any],
        eff_lang: str,
        query_str: str,
        query_present: bool,
        is_section: bool = False
) -> Dict[str, Any]:
    src = hit.get("_source", {})
    highlight = hit.get("highlight", {})

    if is_section:
        doc_title = src.get(f"doc_title.{eff_lang}") or src.get("doc_title.en") or src.get("doc_title.pl") or ''
        sec_title = src.get(f"title.{eff_lang}") or src.get("title.en") or src.get("title.pl") or ''
        title = f"{doc_title} / {sec_title}" if doc_title and sec_title else doc_title or sec_title
        href = f"/docs/{src.get('path')}?highlight={query_str}"
        icon = """<i class="bi bi-file-text"></i>"""
    else:
        title = src.get(f"title.{eff_lang}") or src.get("title.en") or src.get("title.pl") or ''
        href = f"/docs/{src.get('path')}/{src.get('language')}/index.html"
        icon = """<i class="bi bi-files"></i>"""

    snippet = _get_snippet(src, highlight, eff_lang, query_present, is_section)

    version = src.get("version", '')
    langs = src.get("languages") or [src.get("language")]
    langs_str = ", ".join(str(l) for l in langs if l)
    meta_parts: List[str] = []
    if is_section and src.get("section_name"):
        meta_parts.append(f"Section: {src['section_name']}")
    if version:
        meta_parts.append(f"Version: {version}")
    if src.get("release_date"):
        meta_parts.append(f"Released: {src['release_date']}")
    if langs_str:
        meta_parts.append(f"Language: {langs_str}")
    meta = " | ".join(meta_parts)

    return {"title": title, "meta": meta, "snippet": snippet, "href": href, "icon": icon}


def _create_suggestion_config(query: str, lang: str | None) -> Dict[str, Any]:
    """ optimized suggestion configuration."""
    suggest_config = {}

    # Define fields to suggest on based on language preference
    if lang == "pl":
        field_priority = ["title.pl", "content.pl", "title.en", "content.en"]
    else:
        field_priority = ["title.en", "content.en", "title.pl", "content.pl"]

    # Create phrase suggestions with better configuration
    for i, field in enumerate(field_priority):
        field_key = field.replace(".", "_")
        suggest_config[f"phrase_{field_key}"] = {
            "text": query,
            "phrase": {
                "field": field,
                "size": 3,  # Get more suggestions
                "real_word_error_likelihood": 0.95,  # High likelihood of real word errors
                "max_errors": 0.8,  #  up to 80% of words to have errors
                "confidence": 0.0001,  # Very low confidence threshold
                "separator": " ",
                "direct_generator": [{
                    "field": field,
                    "suggest_mode": "always",
                    "min_word_length": 2,
                    "prefix_length": 1,
                    "min_doc_freq": 1,
                    "max_edits": 2,
                    "max_inspections": 5,
                    "max_term_freq": 0.01,
                    "size": 5
                }],
                "highlight": {
                    "pre_tag": "<em>",
                    "post_tag": "</em>"
                },
                "collate": {
                    "query": {
                        "source": {
                            "match": {
                                "{{field_name}}": "{{suggestion}}"
                            }
                        }
                    },
                    "params": {"field_name": field},
                    "prune": True
                }
            }
        }

    # term suggestions as fallback
    for i, field in enumerate(field_priority):
        field_key = field.replace(".", "_")
        suggest_config[f"term_{field_key}"] = {
            "text": query,
            "term": {
                "field": field,
                "size": 3,
                "suggest_mode": "always",
                "min_word_length": 2,
                "prefix_length": 1,
                "min_doc_freq": 1,
                "max_edits": 2,
                "max_inspections": 5,
                "max_term_freq": 0.01
            }
        }

    return suggest_config


def _extract_suggestions(resp: Dict[str, Any], lang: str | None) -> Dict[str, str | None]:
    """Extract the best suggestions from OpenSearch response."""
    if "suggest" not in resp:
        return {"term": None, "phrase": None}

    suggest_data = resp["suggest"]
    best_phrase = None
    best_term = None

    # Define field priority based on language
    if lang == "pl":
        field_priority = ["title_pl", "content_pl", "title_en", "content_en"]
    else:
        field_priority = ["title_en", "content_en", "title_pl", "content_pl"]

    # Extract phrase suggestions with priority
    for field in field_priority:
        phrase_key = f"phrase_{field}"
        if phrase_key in suggest_data:
            suggestions = suggest_data[phrase_key]
            for suggestion_group in suggestions:
                options = suggestion_group.get("options", [])
                if options:
                    # Get the best scoring option that was collated (validated)
                    for option in options:
                        if option.get("collate_match", False) and option.get("score", 0) > 0:
                            best_phrase = option["text"]
                            break
                    if best_phrase:
                        break
            if best_phrase:
                break

    # If no good phrase suggestion, try term suggestions
    if not best_phrase:
        for field in field_priority:
            term_key = f"term_{field}"
            if term_key in suggest_data:
                suggestions = suggest_data[term_key]
                for suggestion_group in suggestions:
                    options = suggestion_group.get("options", [])
                    if options and options[0].get("freq", 0) > 0:
                        best_term = options[0]["text"]
                        break
                if best_term:
                    break

    return {"term": best_term, "phrase": best_phrase}


def _fallback_search(client: OpenSearch, query: str, lang: str | None, is_section: bool) -> Dict[str, Any]:
    """Perform a fallback search with relaxed constraints when no results found."""
    index_name = INDEX_SECTIONS if is_section else INDEX_DOCS

    # Try a more relaxed search
    if is_section:
        bases = ["doc_title", "title", "content"]
    else:
        bases = ["title", "summary"]

    fields: List[str] = []
    for base in bases:
        if lang:
            fields.append(f"{base}.{lang}")
        else:
            fields.extend([f"{base}.en", f"{base}.pl"])

    # Use should with lower minimum_should_match for more flexibility
    query_words = query.split()
    should_clauses = []

    for word in query_words:
        should_clauses.append({
            "multi_match": {
                "query": word,
                "fields": fields,
                "fuzziness": "AUTO",
                "boost": 1.0
            }
        })

    fallback_body = {
        "query": {
            "bool": {
                "should": should_clauses,
                "minimum_should_match": max(1, len(query_words) // 2)  # Match at least half the words
            }
        },
        "highlight": _highlight_block(True, is_section),
        "size": MAX_HITS,
        "track_total_hits": True
    }

    return client.search(index=index_name, body=fallback_body)


def search_documents(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    lang = request.GET.get("lang") or None
    sort_by = request.GET.get("sort", "relevance")
    # Handle both old search_type and new mode parameters for backward compatibility
    search_type = request.GET.get("mode") or request.GET.get("search_type", "keyword")
    
    # Map mode values to search type constants
    if search_type == "keyword":
        search_type = SEARCH_TYPE_STANDARD
    elif search_type == "semantic":
        search_type = SEARCH_TYPE_SEMANTIC
    elif search_type == "hybrid":
        search_type = SEARCH_TYPE_HYBRID
    
    # If semantic or hybrid search is requested, redirect to semantic search handler
    if search_type in [SEARCH_TYPE_SEMANTIC, SEARCH_TYPE_HYBRID]:
        return semantic_search_documents(request)

    page = 1
    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        pass
    offset = (page - 1) * MAX_HITS

    client = get_client()
    is_section = bool(query)
    index_name = INDEX_SECTIONS if is_section else INDEX_DOCS

    body = _build_body(query or None, lang, is_section)
    if query:
        body["highlight"] = _highlight_block(True, is_section)
        # Add improved suggestion configuration
        body["suggest"] = _create_suggestion_config(query, lang)

    if sort_by == "date":
        body["sort"] = [{"release_date": "desc"}]

    body["track_total_hits"] = True
    body["from"] = offset
    body["size"] = MAX_HITS

    # Execute primary search
    resp = client.search(index=index_name, body=body)
    total = resp["hits"]["total"]["value"]

    # If no results and we have a query, try fallback search
    if total == 0 and query:
        logger.info(f"No results for query '{query}', trying fallback search")
        try:
            fallback_resp = _fallback_search(client, query, lang, is_section)
            if fallback_resp["hits"]["total"]["value"] > 0:
                resp = fallback_resp
                total = resp["hits"]["total"]["value"]
                logger.info(f"Fallback search found {total} results")
        except Exception as e:
            logger.warning(f"Fallback search failed: {e}")

    total_pages = max((total + MAX_HITS - 1) // MAX_HITS, 1)

    # Extract suggestions using the improved helper function
    suggestions = _extract_suggestions(resp, lang)

    # Format hits
    eff_lang = lang or "en"
    query_present = bool(query)
    raw_hits = resp["hits"]["hits"]
    results = []
    for i, hit in enumerate(raw_hits, start=offset + 1):
        fmt = _format_hit(hit, eff_lang, query, query_present, is_section)
        fmt["number"] = i
        results.append(fmt)

    # Use phrase suggestion if available, otherwise use term suggestion
    best_suggestion = suggestions["phrase"] or suggestions["term"]

    # Map search type back to mode values for template
    mode_value = "keyword"
    if search_type == SEARCH_TYPE_SEMANTIC:
        mode_value = "semantic"
    elif search_type == SEARCH_TYPE_HYBRID:
        mode_value = "hybrid"
    
    return render(request, "search.html", {
        "results": results,
        "query": query,
        "selected_lang": lang,
        "search_mode": mode_value,
        "search_type": search_type,  # Keep for backward compatibility
        "sort_by": sort_by,
        "page": page,
        "total": total,
        "total_pages": total_pages,
        "start_index": offset + 1,
        "index_used": index_name,
        "suggestion": best_suggestion,  # Use the best available suggestion
        "term_suggestion": suggestions["term"],
        "phrase_suggestion": suggestions["phrase"],
    })


def semantic_search_documents(request: HttpRequest) -> HttpResponse:
    """
    Handle semantic search requests using vector similarity.
    Provides a search option selector like ChatGPT's model selector.
    """
    query = request.GET.get("q", "").strip()
    lang = request.GET.get("lang") or None
    # Handle both old search_type and new mode parameters for backward compatibility
    search_type = request.GET.get("mode") or request.GET.get("search_type", "keyword")
    
    # Map mode values to search type constants
    if search_type == "keyword":
        search_type = SEARCH_TYPE_STANDARD
    elif search_type == "semantic":
        search_type = SEARCH_TYPE_SEMANTIC
    elif search_type == "hybrid":
        search_type = SEARCH_TYPE_HYBRID
    
    page = 1
    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        pass
    offset = (page - 1) * MAX_HITS

    client = get_client()
    
    # Handle different search types
    if search_type == SEARCH_TYPE_SEMANTIC and query:
        # Pure semantic search using simplified chunks
        resp = search_semantic_chunks(
            client=client,
            query=query,
            lang=lang,
            size=MAX_HITS,
            offset=offset
        )
        
        # Format results for semantic search
        eff_lang = lang or "en"
        raw_hits = resp["hits"]["hits"]
        results = []
        for i, hit in enumerate(raw_hits, start=offset + 1):
            fmt = format_chunk_hit(hit, query)
            fmt["number"] = i
            results.append(fmt)
        
        total = resp["hits"]["total"]["value"] if "total" in resp["hits"] else len(raw_hits)
        total_pages = max((total + MAX_HITS - 1) // MAX_HITS, 1)
        index_used = "Semantic Chunks (Vector-based)"
        
        # Map search type back to mode values for template
        mode_value = "semantic"
        
        context = {
            "results": results,
            "query": query,
            "selected_lang": lang,
            "search_mode": mode_value,
            "search_type": search_type,  # Keep for backward compatibility
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "start_index": offset + 1,
            "index_used": index_used,
            "suggestion": None,  # No suggestions for semantic search
            "term_suggestion": None,
            "phrase_suggestion": None,
        }
        
    elif search_type == SEARCH_TYPE_HYBRID and query:
        # Hybrid search combining semantic and keyword using chunks
        resp = hybrid_search_chunks(
            client=client,
            query=query,
            lang=lang,
            size=MAX_HITS,
            offset=offset,
            semantic_weight=0.6  # 60% semantic, 40% keyword
        )
        
        # Format results for hybrid search
        eff_lang = lang or "en"
        raw_hits = resp["hits"]["hits"]
        results = []
        for i, hit in enumerate(raw_hits, start=offset + 1):
            fmt = format_chunk_hit(hit, query)
            fmt["number"] = i
            results.append(fmt)
        
        total = resp["hits"]["total"]["value"] if "total" in resp["hits"] else len(raw_hits)
        total_pages = max((total + MAX_HITS - 1) // MAX_HITS, 1)
        index_used = "Hybrid Chunks (Semantic + Keyword)"
        
        # Map search type back to mode values for template
        mode_value = "hybrid"
        
        context = {
            "results": results,
            "query": query,
            "selected_lang": lang,
            "search_mode": mode_value,
            "search_type": search_type,  # Keep for backward compatibility
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "start_index": offset + 1,
            "index_used": index_used,
            "suggestion": None,
            "term_suggestion": None,
            "phrase_suggestion": None,
        }
        
    else:
        # Fall back to standard search (existing functionality)
        # Redirect to the standard search with the same parameters
        from django.http import HttpResponseRedirect
        from django.urls import reverse
        
        params = request.GET.copy()
        params['search_type'] = SEARCH_TYPE_STANDARD
        
        redirect_url = reverse('search_documents') + '?' + params.urlencode()
        return HttpResponseRedirect(redirect_url)
    
    return render(request, "search.html", context)


def get_search_options(request: HttpRequest) -> HttpResponse:
    """
    API endpoint to get available search options.
    Used for dynamic search type selection in the frontend.
    """
    from django.http import JsonResponse
    
    search_options = [
        {
            "value": SEARCH_TYPE_STANDARD,
            "label": "Standard Search",
            "description": "Traditional keyword-based search with suggestions"
        },
        {
            "value": SEARCH_TYPE_SEMANTIC,
            "label": "Semantic Search", 
            "description": "AI-powered search based on meaning and context"
        },
        {
            "value": SEARCH_TYPE_HYBRID,
            "label": "Hybrid Search",
            "description": "Combines semantic understanding with keyword matching"
        }
    ]
    
    return JsonResponse({"search_options": search_options})