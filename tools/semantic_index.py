#!/usr/bin/env python
"""
tools.semantic_index
~~~~~~~~~~~~~~~~~~~~

Simplified semantic indexing using OpenSearch with chunks created by semantic_chunker.
This module replaces the complex setup and provides a streamlined approach.

Usage:
    python -m tools.semantic_index path/to/chunks.json [--create-index] [--index-chunks]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Any

import django
from opensearchpy import OpenSearch, helpers

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndoc.settings")
django.setup()

from ndoc.opensearch import get_client

logger = logging.getLogger("tools.semantic_index")

# Simple index configuration
SEMANTIC_INDEX = "ndoc_semantic_chunks"
VECTOR_DIMENSION = 384  # all-MiniLM-L6-v2 dimension

INDEX_SETTINGS = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 512,
            "number_of_shards": 1,
            "number_of_replicas": 0
        }
    },
    "mappings": {
        "properties": {
            # Core fields
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "language": {"type": "keyword"},
            "file_name": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "path": {"type": "keyword"},
            
            # Content fields with language-specific analyzers
            "doc_title": {"type": "text", "analyzer": "standard"},
            "doc_summary": {"type": "text", "analyzer": "standard"},
            "content": {"type": "text", "analyzer": "standard"},
            "content_length": {"type": "integer"},
            
            # Vector field for semantic search
            "content_vector": {
                "type": "knn_vector",
                "dimension": VECTOR_DIMENSION,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "lucene",
                    "parameters": {
                        "ef_construction": 512,
                        "m": 16
                    }
                }
            }
        }
    }
}


def create_semantic_index(client: OpenSearch) -> bool:
    """Create the semantic chunks index."""
    try:
        if client.indices.exists(index=SEMANTIC_INDEX):
            logger.info(f"Index '{SEMANTIC_INDEX}' already exists")
            return True
        
        response = client.indices.create(index=SEMANTIC_INDEX, body=INDEX_SETTINGS)
        logger.info(f"Created semantic index: {response}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to create semantic index: {e}")
        return False


def generate_embeddings(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate embeddings for chunks using the existing embedding service."""
    try:
        # Import here to avoid circular dependencies
        from search.embeddings import get_embedding_service
        
        embedding_service = get_embedding_service()
        logger.info(f"Using embedding model: {embedding_service.model_name}")
        
        # Prepare chunks with embeddings
        processed_chunks = []
        
        for i, chunk in enumerate(chunks):
            if i % 100 == 0:
                logger.info(f"Processing embeddings: {i}/{len(chunks)}")
            
            # Combine title and content for embedding
            text_parts = []
            if chunk.get("doc_title"):
                text_parts.append(chunk["doc_title"])
            if chunk.get("content"):
                text_parts.append(chunk["content"])
            
            combined_text = " ".join(text_parts) if text_parts else "empty content"
            
            # Generate embedding
            try:
                vector = embedding_service.encode_text(combined_text)
                chunk_with_vector = chunk.copy()
                chunk_with_vector["content_vector"] = vector.tolist()
                processed_chunks.append(chunk_with_vector)
            except Exception as e:
                logger.warning(f"Failed to generate embedding for chunk {chunk.get('chunk_id')}: {e}")
                continue
        
        logger.info(f"Generated embeddings for {len(processed_chunks)}/{len(chunks)} chunks")
        return processed_chunks
        
    except ImportError as e:
        logger.error(f"Failed to import embedding service: {e}")
        return []


def index_chunks(client: OpenSearch, chunks: List[Dict[str, Any]], batch_size: int = 100) -> bool:
    """Index chunks into OpenSearch."""
    try:
        # Prepare bulk actions
        actions = []
        for chunk in chunks:
            action = {
                "_index": SEMANTIC_INDEX,
                "_id": chunk["chunk_id"],
                "_source": chunk
            }
            actions.append(action)
        
        # Bulk index in batches
        total_indexed = 0
        for i in range(0, len(actions), batch_size):
            batch = actions[i:i + batch_size]
            result = helpers.bulk(client, batch, refresh=False)
            total_indexed += len(batch)
            logger.info(f"Indexed batch: {total_indexed}/{len(actions)} chunks")
        
        # Refresh index
        client.indices.refresh(index=SEMANTIC_INDEX)
        logger.info(f"Successfully indexed {total_indexed} chunks")
        return True
        
    except Exception as e:
        logger.error(f"Failed to index chunks: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Index semantic chunks into OpenSearch")
    parser.add_argument("chunks_file", type=Path, help="Path to semantic chunks JSON file")
    parser.add_argument("--create-index", action="store_true", help="Create the semantic index")
    parser.add_argument("--index-chunks", action="store_true", help="Index the chunks")
    parser.add_argument("--all", action="store_true", help="Create index and index chunks")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for indexing")
    parser.add_argument("-v", "--verbosity", type=int, choices=[0, 1, 2, 3], default=2,
                       help="Verbosity level")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=[logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG][args.verbosity],
        format="[%(levelname)s] %(name)s: %(message)s"
    )
    
    if args.all:
        args.create_index = True
        args.index_chunks = True
    
    if not (args.create_index or args.index_chunks):
        logger.error("Specify --create-index, --index-chunks, or --all")
        return
    
    # Get OpenSearch client
    try:
        client = get_client()
        logger.info("Connected to OpenSearch")
    except Exception as e:
        logger.error(f"Failed to connect to OpenSearch: {e}")
        return
    
    # Create index if requested
    if args.create_index:
        if not create_semantic_index(client):
            logger.error("Failed to create semantic index")
            return
    
    # Index chunks if requested
    if args.index_chunks:
        # Load chunks
        try:
            with open(args.chunks_file, 'r', encoding='utf-8') as f:
                chunks = json.load(f)
            logger.info(f"Loaded {len(chunks)} chunks from {args.chunks_file}")
        except Exception as e:
            logger.error(f"Failed to load chunks file: {e}")
            return
        
        # Generate embeddings
        chunks_with_vectors = generate_embeddings(chunks)
        if not chunks_with_vectors:
            logger.error("Failed to generate embeddings")
            return
        
        # Index chunks
        if not index_chunks(client, chunks_with_vectors, args.batch_size):
            logger.error("Failed to index chunks")
            return
    
    logger.info("Semantic indexing completed successfully")


if __name__ == "__main__":
    main() 