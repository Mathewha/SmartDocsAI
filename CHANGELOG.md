# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


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
