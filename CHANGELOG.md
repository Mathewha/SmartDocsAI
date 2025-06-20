# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [1.0.5] - 2025-06-06

### Added
- `semantic_search.py` - semantic search functionality using OpenSearch vector search (KNN) with cosine similarity
- `embeddings.py` - text-to-vector conversion service using SentenceTransformer model (all-MiniLM-L6-v2)
- `setup_vector_search.py` - Django management command to create vector indices and index existing documents
- Vector search indices: `ndoc_documents_vector` and `ndoc_sections_vector` with 384-dimensional embeddings
- Hybrid search combining semantic similarity (60%) with keyword matching (40%)
- Search mode selector with three options: Standard, Semantic, and Hybrid search
- `/search` API endpoint `get_search_options` for dynamic search type selection

### Changed
- `views.py` - added `semantic_search_documents()` function and integrated search type routing
- `views.py` - added search type constants (`SEARCH_TYPE_STANDARD`, `SEARCH_TYPE_SEMANTIC`, `SEARCH_TYPE_HYBRID`)
- `search.html` - updated to support search mode selection and display semantic/hybrid search results
- `requirements.txt` - added `sentence-transformers` dependency for embeddings generation

---

## [1.0.4] - 2025-04-29

### Changed
- `views.py` - added OpenSearch *term–suggest* logic.
- `search.html` - displays a bold **“Did you mean / Czy chodziło o:”** line with the suggested query, localized to the selected language and shown above the results.
- `opensearch.py`- changed to the same as in main 

---

## [1.0.3] - 2025-04-28

### Changed
- better formatting of results
- new fonts and icons

---

## [1.0.2] - 2025-04-27

### Changed
- `tools.text` works better on single-page documents (with index.html only)
- `tools.index` creates two indexes: `ndoc_documents` and `ndoc_sections`
- `tools.index` adds the full contents of the relevant section of the document to the `ndoc_sections` index

---


## [1.0.1] - 2025-04-26

### Added
- `/search` search results pagination
- `/search` option to sort by various criteria


### Changed
- `main.css` refactoring / display formatting  

---

## [1.0.0] - 2025-04-26
### Added
- Initial release of NeuroDoc.
- Metadata extraction (version, release date, title, summary).
- `tools.catalog` for generating JSON file containing all document in given collection
- `tools.index` for generating opensearch index
- `/docs` endpoint serving document catalog / content
- `/search` endpoint serving simple document search capabilities
