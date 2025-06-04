#!/usr/bin/env python
"""
tools.index
~~~~~~~~~~~

Bulk-imports a JSON catalog into OpenSearch with Polish and English language analysis:

* Polish stopwords (`_polish_`) and Stempel stemming
* Built-in `english` analyzer for English fields
* Dynamic template routing of `.pl` and `.en` fields to the correct analyzer

Creates and populates two indices:
* ndoc_documents - document-level index (metadata, titles, summaries)
* ndoc_sections - section-level index for chapters/sections (with content)

Usage:
    python -m tools.index path/to/catalog.json path/to/input_dir [-v 0-3] [--doc-index NAME] [--section-index NAME]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Any

import django
from opensearchpy import OpenSearch, helpers
from django.conf import settings
from ndoc.opensearch import get_client

# ────────────── Logging Setup ──────────────
logger = logging.getLogger("tools.index")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)

_VERBOSITY = {0: logging.ERROR, 1: logging.WARNING, 2: logging.INFO, 3: logging.DEBUG}

# ─────────── Django Bootstrap ───────────
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndoc.settings")
django.setup()

# ────────── Index Settings with Language-Specific Analyzers ──────────
DOCUMENT_INDEX_SETTINGS = {
    "mappings": {
        "dynamic_templates": [
            {"pl_text": {"match_mapping_type": "string", "match": "*.pl", "mapping": {"type": "text", "analyzer": "polish"}}},
            {"en_text": {"match_mapping_type": "string", "match": "*.en", "mapping": {"type": "text", "analyzer": "english"}}}
        ],
        "properties": {
            "id":           {"type": "keyword"},
            "language":     {"type": "keyword"},
            "version":      {"type": "keyword"},
            "release_date": {"type": "date"},
            "path":         {"type": "keyword"},
            "title.en":     {"type": "text", "analyzer": "english"},
            "title.pl":     {"type": "text", "analyzer": "polish"},
            "summary.en":   {"type": "text", "analyzer": "english"},
            "summary.pl":   {"type": "text", "analyzer": "polish"}
        }
    }
}

SECTION_INDEX_SETTINGS = {
    "mappings": {
        "dynamic_templates": [
            {"pl_text": {"match_mapping_type": "string", "match": "*.pl", "mapping": {"type": "text", "analyzer": "polish"}}},
            {"en_text": {"match_mapping_type": "string", "match": "*.en", "mapping": {"type": "text", "analyzer": "english"}}}
        ],
        "properties": {
            "doc_id":       {"type": "keyword"},
            "section_id":   {"type": "keyword"},
            "section_name": {"type": "keyword"},
            "language":     {"type": "keyword"},
            "version":      {"type": "keyword"},
            "release_date": {"type": "date"},
            "path":         {"type": "keyword"},
            "doc_title.en": {"type": "text", "analyzer": "english"},
            "doc_title.pl": {"type": "text", "analyzer": "polish"},
            "title.en":     {"type": "text", "analyzer": "english"},
            "title.pl":     {"type": "text", "analyzer": "polish"},
            "content.en":   {"type": "text", "analyzer": "english"},
            "content.pl":   {"type": "text", "analyzer": "polish"},
            "level":        {"type": "integer"},
            "order":        {"type": "integer"}
        }
    }
}


def ensure_indices(client: OpenSearch, doc_index: str, section_index: str) -> None:
    """Create both indices with custom analyzers if they don't exist."""
    if client.indices.exists(index=doc_index):
        logger.debug("Index '%s' already exists — skipping creation", doc_index)
    else:
        logger.info("Creating index '%s'…", doc_index)
        client.indices.create(index=doc_index, body=DOCUMENT_INDEX_SETTINGS)

    if client.indices.exists(index=section_index):
        logger.debug("Index '%s' already exists — skipping creation", section_index)
    else:
        logger.info("Creating index '%s'…", section_index)
        client.indices.create(index=section_index, body=SECTION_INDEX_SETTINGS)


def index_catalog(
    json_path: Path,
    input_dir: Path,
    client: OpenSearch,
    doc_index: str,
    section_index: str
) -> None:
    """Load JSON catalog and bulk-index documents into both OpenSearch indices, overwriting existing docs."""
    catalog = json.loads(json_path.read_text(encoding="utf-8"))
    doc_actions: list[dict] = []
    section_actions: list[dict] = []
    skipped_docs = 0
    skipped_sections = 0

    for entry in catalog:
        base_id = entry.get("id")
        release_date = entry.get("release_date")
        path = entry.get("path")
        version = entry.get("version")
        chapters = entry.get("chapters", [])

        for lang in entry.get("languages", []):
            title = entry.get("title", {}).get(lang)
            summary = entry.get("summary", {}).get(lang)

            if not title:
                skipped_docs += 1
                logger.warning("Skipped '%s' (%s) — missing title", base_id, lang)
                continue

            suffix = ".pl" if lang == "pl" else ".en"
            # Use index op_type to fully overwrite existing document
            doc_actions.append({
                "_op_type": "index",
                "_index": doc_index,
                "_id": f"{base_id}::{lang}",
                "_source": {
                    "id": base_id,
                    "language": lang,
                    "version": version,
                    "release_date": release_date,
                    "path": path,
                    f"title{suffix}": title,
                    f"summary{suffix}": summary or ""
                }
            })

            process_sections(
                base_id, lang, title, path, version, release_date,
                chapters, section_actions, section_index, suffix, input_dir
            )

    if doc_actions:
        helpers.bulk(client, doc_actions, refresh="wait_for")
        logger.info(
            "Indexed %d docs to %s (skipped %d)",
            len(doc_actions), doc_index, skipped_docs
        )
    else:
        logger.info("No documents to index in %s for %s", json_path.name, doc_index)

    if section_actions:
        helpers.bulk(client, section_actions, refresh="wait_for")
        logger.info(
            "Indexed %d sections to %s (skipped %d)",
            len(section_actions), section_index, skipped_sections
        )
    else:
        logger.info("No sections to index in %s for %s", json_path.name, section_index)


def process_sections(
    doc_id: str,
    lang: str,
    doc_title: str,
    path: str,
    version: str,
    release_date: str,
    chapters: List[Dict[str, Any]],
    section_actions: List[Dict],
    index_name: str,
    suffix: str,
    input_dir: Path,
    parent_path: str = "",
    level: int = 1
) -> None:
    """Recursively process document sections and add them to the section index, reading content from text files."""
    text_root = input_dir / doc_id / lang / "_text"

    for i, chapter in enumerate(chapters):
        section_name = chapter.get("name", "_")
        section_id   = section_name.split(".")[0]
        title        = chapter.get("title", {}).get(lang) or next((v for v in chapter.get("title", {}).values() if v), "")

        # Read content from file
        file_path = text_root / f"{section_id}.txt"
        try:
            content = file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Content file not found: %s", file_path)
            content = ""

        if not title and not content:
            continue

        # Use index op_type to fully overwrite existing section doc
        section_actions.append({
            "_op_type": "index",
            "_index": index_name,
            "_id": f"{doc_id}::{section_id}::{lang}",
            "_source": {
                "doc_id": doc_id,
                "section_id": section_id,
                "section_name": section_name,
                "language": lang,
                "version": version,
                "release_date": release_date,
                "path": f"{doc_id}/{lang}/{section_name}",
                f"doc_title{suffix}": doc_title,
                f"title{suffix}": title,
                f"content{suffix}": content,
                "level": level,
                "order": i
            }
        })

        # Recurse into sub-chapters if present
        if chapter.get("chapters"):
            process_sections(
                doc_id, lang, doc_title, path, version, release_date,
                chapter["chapters"], section_actions, index_name, suffix,
                input_dir, section_id, level + 1
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import JSON catalog into OpenSearch indices.")
    parser.add_argument("json_file", type=Path, help="Path to catalogue.json")
    parser.add_argument("input_dir", type=Path, help="Root directory of text files")
    parser.add_argument(
        "-v", "--verbosity", type=int, choices=[0,1,2,3], default=2,
        help="Logging level: 0=ERR,1=WRN,2=INF,3=DBG"
    )
    parser.add_argument(
        "--doc-index", default="ndoc_documents",
        help="Target document index name (default: ndoc_documents)"
    )
    parser.add_argument(
        "--section-index", default="ndoc_sections",
        help="Target section index name (default: ndoc_sections)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=_VERBOSITY[args.verbosity], format="%(levelname)s | %(message)s")
    if not args.json_file.is_file():
        logger.error("File not found: %s", args.json_file)
        sys.exit(1)
    if not args.input_dir.is_dir():
        logger.error("Input dir not found: %s", args.input_dir)
        sys.exit(1)

    client = get_client()
    ensure_indices(client, args.doc_index, args.section_index)
    try:
        index_catalog(
            args.json_file.resolve(),
            args.input_dir.resolve(),
            client,
            args.doc_index,
            args.section_index
        )
    except Exception:
        logger.exception("Import failed")
        sys.exit(2)


if __name__ == "__main__":
    main()
