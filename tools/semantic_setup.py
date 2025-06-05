#!/usr/bin/env python
"""
tools.semantic_setup
~~~~~~~~~~~~~~~~~~~

Configures OpenSearch for semantic search by:
1. Creating the necessary indices with KNN vector support
2. Setting up the required analyzers and mappings
3. Verifying the configuration

Usage:
    python -m tools.semantic_setup
"""

from __future__ import annotations

import logging
import sys
from typing import Dict, Any

import django
from opensearchpy import OpenSearch
from django.conf import settings
from ndoc.opensearch import get_client

# ────────────── Logging Setup ──────────────
logger = logging.getLogger("tools.semantic_setup")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)

# ─────────── Django Bootstrap ───────────
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndoc.settings")
django.setup()

# Get index names from settings
INDEX_DOCS = settings.OPENSEARCH["DOC_INDEX"]
INDEX_SECTIONS = settings.OPENSEARCH["SECTION_INDEX"]

# ────────── Index Settings ──────────
DOCUMENT_INDEX_SETTINGS = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100,
            "knn.algo_param.ef_construction": 200,
            "knn.algo_param.m": 16
        }
    },
    "mappings": {
        "dynamic_templates": [
            {"pl_text": {"match_mapping_type": "string", "match": "*.pl",
                         "mapping": {"type": "text", "analyzer": "polish"}}},
            {"en_text": {"match_mapping_type": "string", "match": "*.en",
                         "mapping": {"type": "text", "analyzer": "english"}}}
        ],
        "properties": {
            "id": {"type": "keyword"},
            "language": {"type": "keyword"},
            "version": {"type": "keyword"},
            "release_date": {"type": "date"},
            "path": {"type": "keyword"},
            "title.en": {"type": "text", "analyzer": "english"},
            "title.pl": {"type": "text", "analyzer": "polish"},
            "summary.en": {"type": "text", "analyzer": "english"},
            "summary.pl": {"type": "text", "analyzer": "polish"},
            "embedding": {"type": "knn_vector", "dimension": 384,
                          "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "nmslib"}}
        }
    }
}

SECTION_INDEX_SETTINGS = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100,
            "knn.algo_param.ef_construction": 200,
            "knn.algo_param.m": 16
        }
    },
    "mappings": {
        "dynamic_templates": [
            {"pl_text": {"match_mapping_type": "string", "match": "*.pl",
                         "mapping": {"type": "text", "analyzer": "polish"}}},
            {"en_text": {"match_mapping_type": "string", "match": "*.en",
                         "mapping": {"type": "text", "analyzer": "english"}}}
        ],
        "properties": {
            "doc_id": {"type": "keyword"},
            "section_id": {"type": "keyword"},
            "section_name": {"type": "keyword"},
            "language": {"type": "keyword"},
            "version": {"type": "keyword"},
            "release_date": {"type": "date"},
            "path": {"type": "keyword"},
            "doc_title.en": {"type": "text", "analyzer": "english"},
            "doc_title.pl": {"type": "text", "analyzer": "polish"},
            "title.en": {"type": "text", "analyzer": "english"},
            "title.pl": {"type": "text", "analyzer": "polish"},
            "content.en": {"type": "text", "analyzer": "english"},
            "content.pl": {"type": "text", "analyzer": "polish"},
            "level": {"type": "integer"},
            "order": {"type": "integer"},
            "embedding": {"type": "knn_vector", "dimension": 384,
                          "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "nmslib"}}
        }
    }
}


def setup_indices(client: OpenSearch) -> None:
    """Create or update indices with semantic search configuration."""
    indices = {
        INDEX_DOCS: DOCUMENT_INDEX_SETTINGS,
        INDEX_SECTIONS: SECTION_INDEX_SETTINGS
    }

    for index_name, settings in indices.items():
        if client.indices.exists(index=index_name):
            logger.info(f"Index '{index_name}' exists, checking configuration...")
            current_settings = client.indices.get_settings(index=index_name)
            current_mappings = client.indices.get_mapping(index=index_name)

            # Check if KNN is already enabled
            knn_enabled = current_settings[index_name]["settings"]["index"].get("knn") == "true"

            if not knn_enabled:
                logger.info(f"KNN not enabled for '{index_name}', recreating index...")
                # Delete the existing index
                client.indices.delete(index=index_name)
                # Create new index with KNN settings
                client.indices.create(index=index_name, body=settings)
            else:
                logger.info(f"Updating mappings for '{index_name}'...")
                # Only update mappings if KNN is already enabled
                client.indices.put_mapping(index=index_name, body=settings["mappings"])
        else:
            logger.info(f"Creating index '{index_name}'...")
            client.indices.create(index=index_name, body=settings)


def verify_setup(client: OpenSearch) -> None:
    """Verify that the indices are properly configured for semantic search."""
    indices = [INDEX_DOCS, INDEX_SECTIONS]

    for index_name in indices:
        try:
            # Get index settings
            settings = client.indices.get_settings(index=index_name)
            # Get index mappings
            mappings = client.indices.get_mapping(index=index_name)

            # Verify KNN settings
            knn_enabled = settings[index_name]["settings"]["index"]["knn"] == "true"
            if not knn_enabled:
                logger.error(f"KNN is not enabled for index '{index_name}'")
                sys.exit(1)

            # Verify embedding field
            embedding_field = mappings[index_name]["mappings"]["properties"]["embedding"]
            if embedding_field["type"] != "knn_vector":
                logger.error(f"Embedding field is not properly configured in index '{index_name}'")
                sys.exit(1)

            logger.info(f"Index '{index_name}' is properly configured for semantic search")

        except Exception as e:
            logger.error(f"Failed to verify index '{index_name}': {e}")
            sys.exit(1)


def main() -> None:
    """Main entry point."""
    try:
        client = get_client()

        logger.info("Setting up indices for semantic search...")
        setup_indices(client)

        logger.info("Verifying setup...")
        verify_setup(client)

        logger.info("Semantic search setup completed successfully!")

    except Exception as e:
        logger.error(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()