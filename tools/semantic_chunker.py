#!/usr/bin/env python
"""
tools.semantic_chunker
~~~~~~~~~~~~~~~~~~~~~~

Creates semantic chunks from documents using the existing text processing tools.
This module leverages tools/text.py and tools/catalog.py to create meaningful
chunks for semantic search indexing.

Usage:
    python -m tools.semantic_chunker path/to/catalog.json path/to/input_dir path/to/output_dir
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Any

# Import existing tools functions
from .text import TableAwareExtractor
from .catalog import extract_title, extract_summary

logger = logging.getLogger("tools.semantic_chunker")

# Chunk configuration
MAX_CHUNK_SIZE = 800  # Maximum characters per chunk
MIN_CHUNK_SIZE = 200  # Minimum characters per chunk
OVERLAP_SIZE = 100    # Overlap between chunks


class SemanticChunker:
    """Creates semantic chunks from documents for better search indexing."""
    
    def __init__(self, max_chunk_size: int = MAX_CHUNK_SIZE, 
                 min_chunk_size: int = MIN_CHUNK_SIZE,
                 overlap_size: int = OVERLAP_SIZE):
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self.overlap_size = overlap_size
    
    def chunk_document(self, doc_path: Path, lang: str, doc_id: str) -> List[Dict[str, Any]]:
        """
        Create semantic chunks from a document.
        
        Args:
            doc_path: Path to document directory
            lang: Language code (en/pl)
            doc_id: Document identifier
            
        Returns:
            List of chunk dictionaries with metadata
        """
        chunks = []
        
        # Extract document title and summary using existing tools
        title = extract_title(doc_path, lang)
        summary = extract_summary(doc_path, lang)
        
        # Process each HTML file in the language directory
        lang_dir = doc_path / lang
        if not lang_dir.exists():
            return chunks
        
        # Get ordered list of HTML files
        html_files = list(lang_dir.glob("*.html"))
        html_files.sort()  # Basic sorting, could be improved with index.html order
        
        chunk_id = 0
        for html_file in html_files:
            if html_file.name.lower() in {"search.html", "genindex.html"}:
                continue
                
            file_chunks = self._process_html_file(
                html_file, doc_id, lang, title, summary, chunk_id
            )
            chunks.extend(file_chunks)
            chunk_id += len(file_chunks)
        
        return chunks
    
    def _process_html_file(self, html_file: Path, doc_id: str, lang: str, 
                          doc_title: str, doc_summary: str, start_chunk_id: int) -> List[Dict[str, Any]]:
        """Process a single HTML file into chunks."""
        chunks = []
        
        # Extract clean text using existing TableAwareExtractor
        is_index = html_file.name == "index.html"
        extractor = TableAwareExtractor(is_index=is_index)
        
        try:
            html_content = html_file.read_text(encoding="utf-8", errors="ignore")
            extractor.feed(html_content)
            clean_text = extractor.get_text()
        except Exception as e:
            logger.warning(f"Failed to process {html_file}: {e}")
            return chunks
        
        if not clean_text.strip():
            return chunks
        
        # Split into semantic chunks
        text_chunks = self._split_text_semantically(clean_text)
        
        # Create chunk objects
        for i, chunk_text in enumerate(text_chunks):
            if len(chunk_text.strip()) < self.min_chunk_size:
                continue
                
            chunk = {
                "chunk_id": f"{doc_id}::{lang}::{start_chunk_id + i}",
                "doc_id": doc_id,
                "language": lang,
                "file_name": html_file.name,
                "chunk_index": i,
                "doc_title": doc_title or "",
                "doc_summary": doc_summary or "",
                "content": chunk_text.strip(),
                "content_length": len(chunk_text.strip()),
                "path": f"{doc_id}/{lang}/{html_file.name}"
            }
            chunks.append(chunk)
        
        return chunks
    
    def _split_text_semantically(self, text: str) -> List[str]:
        """
        Split text into semantic chunks preserving meaning.
        
        This is a simple but effective approach that:
        1. Splits by paragraphs first
        2. Combines paragraphs into chunks
        3. Ensures chunks don't exceed max size
        4. Adds overlap between chunks
        """
        # Split by double newlines (paragraphs)
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        if not paragraphs:
            return []
        
        chunks = []
        current_chunk = ""
        current_size = 0
        
        for para in paragraphs:
            para_size = len(para)
            
            # If adding this paragraph would exceed max size, finalize current chunk
            if current_size + para_size > self.max_chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                
                # Start new chunk with overlap from previous chunk
                if self.overlap_size > 0:
                    overlap_text = self._get_text_end(current_chunk, self.overlap_size)
                    current_chunk = overlap_text + " " + para
                    current_size = len(current_chunk)
                else:
                    current_chunk = para
                    current_size = para_size
            else:
                # Add paragraph to current chunk
                if current_chunk:
                    current_chunk += "\n\n" + para
                    current_size += 2 + para_size  # +2 for \n\n
                else:
                    current_chunk = para
                    current_size = para_size
        
        # Add the last chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _get_text_end(self, text: str, max_length: int) -> str:
        """Get the end portion of text, preferably at word boundary."""
        if len(text) <= max_length:
            return text
        
        # Try to break at word boundary
        end_portion = text[-max_length:]
        space_idx = end_portion.find(' ')
        if space_idx > 0:
            return end_portion[space_idx + 1:]
        return end_portion


def create_semantic_chunks(catalog_path: Path, input_dir: Path, output_dir: Path) -> None:
    """
    Create semantic chunks for all documents in the catalog.
    
    Args:
        catalog_path: Path to JSON catalog file
        input_dir: Path to input documents directory
        output_dir: Path to output chunks directory
    """
    # Load catalog
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to load catalog {catalog_path}: {e}")
        return
    
    # Initialize chunker
    chunker = SemanticChunker()
    
    # Process each document
    all_chunks = []
    for entry in catalog:
        doc_id = entry.get("id")
        if not doc_id:
            continue
        
        logger.info(f"Processing document: {doc_id}")
        doc_path = input_dir / doc_id
        
        if not doc_path.exists():
            logger.warning(f"Document path not found: {doc_path}")
            continue
        
        # Process each language
        for lang in entry.get("languages", []):
            logger.debug(f"Chunking {doc_id} in {lang}")
            chunks = chunker.chunk_document(doc_path, lang, doc_id)
            all_chunks.extend(chunks)
    
    # Save chunks to output
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks_file = output_dir / "semantic_chunks.json"
    
    with open(chunks_file, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Created {len(all_chunks)} semantic chunks in {chunks_file}")
    
    # Create summary stats
    stats = {
        "total_chunks": len(all_chunks),
        "documents_processed": len(set(chunk["doc_id"] for chunk in all_chunks)),
        "languages": list(set(chunk["language"] for chunk in all_chunks)),
        "avg_chunk_size": sum(chunk["content_length"] for chunk in all_chunks) / len(all_chunks) if all_chunks else 0
    }
    
    stats_file = output_dir / "chunk_stats.json"
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Chunk statistics saved to {stats_file}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Create semantic chunks from document catalog")
    parser.add_argument("catalog", type=Path, help="Path to JSON catalog file")
    parser.add_argument("input_dir", type=Path, help="Path to input documents directory")
    parser.add_argument("output_dir", type=Path, help="Path to output chunks directory")
    parser.add_argument("-v", "--verbosity", type=int, choices=[0, 1, 2, 3], default=2,
                       help="Verbosity level (0=ERROR, 1=WARNING, 2=INFO, 3=DEBUG)")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=[logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG][args.verbosity],
        format="[%(levelname)s] %(name)s: %(message)s"
    )
    
    create_semantic_chunks(args.catalog, args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()