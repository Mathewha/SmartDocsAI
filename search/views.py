from __future__ import annotations

import logging
from typing import Any, Dict, List

from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from django.conf import settings
from opensearchpy import OpenSearch

from ndoc.opensearch import get_client  # helper
from tools.embedding import semantic_search

logger = logging.getLogger(__name__)

# Use index names from settings
INDEX_DOCS = settings.OPENSEARCH["DOC_INDEX"]
INDEX_SECTIONS = settings.OPENSEARCH["SECTION_INDEX"]
MAX_HITS = settings.MAX_HITS
SNIPPET_LENGTH = settings.SNIPPET_LENGTH


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
        is_section: bool = False,
        is_semantic: bool = False
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

    # For semantic search, use the full summary without highlighting
    if is_semantic:
        field_base = 'content' if is_section else 'summary'
        text = (
            src.get(f"{field_base}.{eff_lang}") or
            src.get(f"{field_base}.en") or
            src.get(f"{field_base}.pl") or
            ""
        )
        snippet = f"{text[:SNIPPET_LENGTH]}…" if text else ""
        # Add similarity score to meta
        similarity = hit.get("_score", 0)
        similarity_percent = int(similarity * 100)
    else:
        snippet = _get_snippet(src, highlight, eff_lang, query_present, is_section)
        similarity_percent = None

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
    if similarity_percent is not None:
        meta_parts.append(f"Similarity: {similarity_percent}%")
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


def _perform_keyword_search(
    client: OpenSearch,
    query: str | None,
    lang: str | None,
    is_section: bool,
    sort_by: str,
    offset: int
) -> Dict[str, Any]:
    """Perform traditional keyword-based search."""
    body = _build_body(query or None, lang, is_section)
    if query:
        body["highlight"] = _highlight_block(True, is_section)
        body["suggest"] = _create_suggestion_config(query, lang)

    if sort_by == "date":
        body["sort"] = [{"release_date": "desc"}]

    body["track_total_hits"] = True
    body["from"] = offset
    body["size"] = MAX_HITS

    index_name = INDEX_SECTIONS if is_section else INDEX_DOCS
    return client.search(index=index_name, body=body)


def _perform_semantic_search(
    client: OpenSearch,
    query: str,
    lang: str | None,
    is_section: bool
) -> Dict[str, Any]:
    """Perform semantic search using vector similarity."""
    return semantic_search(client, query, lang, is_section)


def search_documents(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    lang = request.GET.get("lang") or None
    sort_by = request.GET.get("sort", "relevance")
    search_mode = request.GET.get("mode", "keyword")  # Default to keyword search

    page = 1
    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        pass
    offset = (page - 1) * MAX_HITS

    client = get_client()
    is_section = bool(query)

    # Choose search method based on mode
    if search_mode == "semantic" and query:
        resp = _perform_semantic_search(client, query, lang, is_section)
    else:
        resp = _perform_keyword_search(client, query, lang, is_section, sort_by, offset)

    total = resp["hits"]["total"]["value"]

    # If no results and we have a query, try fallback search (only for keyword mode)
    if total == 0 and query and search_mode == "keyword":
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

    # Extract suggestions using the improved helper function (only for keyword mode)
    suggestions = _extract_suggestions(resp, lang) if search_mode == "keyword" else {"term": None, "phrase": None}

    # Format hits
    eff_lang = lang or "en"
    query_present = bool(query)
    raw_hits = resp["hits"]["hits"]
    results = []
    for i, hit in enumerate(raw_hits, start=offset + 1):
        fmt = _format_hit(hit, eff_lang, query, query_present, is_section, search_mode == "semantic")
        fmt["number"] = i
        results.append(fmt)

    # Use phrase suggestion if available, otherwise use term suggestion
    best_suggestion = suggestions["phrase"] or suggestions["term"]

    return render(request, "search.html", {
        "results": results,
        "query": query,
        "selected_lang": lang,
        "sort_by": sort_by,
        "search_mode": search_mode,  # Add search mode to template context
        "page": page,
        "total": total,
        "total_pages": total_pages,
        "start_index": offset + 1,
        "index_used": INDEX_SECTIONS if is_section else INDEX_DOCS,
        "suggestion": best_suggestion,
        "term_suggestion": suggestions["term"],
        "phrase_suggestion": suggestions["phrase"],
    })