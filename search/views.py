from __future__ import annotations

import logging
from typing import Any, Dict, List

from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from opensearchpy import OpenSearch

from ndoc.opensearch import get_client  # helper

logger = logging.getLogger(__name__)

INDEX_DOCS = "ndoc_documents"
INDEX_SECTIONS = "ndoc_sections"
MAX_HITS = 5  # liczba wyników na stronę
SNIPPET_LENGTH = 500  # maksymalna długość snippetów


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
        must = [{"multi_match": {"query": query, "fields": fields, "operator": "and"}}]
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
            "title.*":     {"fragment_size": SNIPPET_LENGTH // 2, "number_of_fragments": 1},
            "content.*":   {"fragment_size": SNIPPET_LENGTH // 2, "number_of_fragments": 2},
        }
    else:
        fields = {
            "title.*":   {"fragment_size": SNIPPET_LENGTH // 2, "number_of_fragments": 1},
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


def search_documents(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    lang = request.GET.get("lang") or None
    sort_by = request.GET.get("sort", "relevance")

    try:
        page = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)
    offset = (page - 1) * MAX_HITS

    client: OpenSearch = get_client()
    is_section = bool(query)
    index_name = INDEX_SECTIONS if is_section else INDEX_DOCS

    body = _build_body(query or None, lang, is_section)
    if query:
        body["highlight"] = _highlight_block(True, is_section)
    if sort_by == "date":
        body["sort"] = [{"release_date": "desc"}]

    # Ensure exact total count (no 10k cap)
    body["track_total_hits"] = True

    body["from"] = offset
    body["size"] = MAX_HITS

    resp = client.search(index=index_name, body=body)
    total = resp.get("hits", {}).get("total", {}).get("value", 0)
    total_pages = max((total + MAX_HITS - 1) // MAX_HITS, 1)

    eff_lang = lang or "en"
    query_present = bool(query)
    raw_hits = resp.get("hits", {}).get("hits", [])
    results: List[Dict[str, Any]] = []
    for i, hit in enumerate(raw_hits, start=offset + 1):
        fmt = _format_hit(hit, eff_lang, query, query_present, is_section)
        fmt["number"] = i
        results.append(fmt)

    logger.debug(
        "search q='%s' lang=%s sort=%s page=%d hits=%d total=%d total_pages=%d index=%s",
        query, lang, sort_by, page, len(results), total, total_pages, index_name
    )

    return render(
        request,
        "search.html",
        {
            "results": results,
            "query": query,
            "selected_lang": lang,
            "sort_by": sort_by,
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "start_index": offset + 1,
            "index_used": index_name
        }
    )
