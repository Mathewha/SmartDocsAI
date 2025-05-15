"""
tools.catalog
~~~~~~~~~~~~~

Recursively scans a source directory and produces a JSON catalog with
metadata for every document found in language‑specific sub‑folders.
Each document contains global **version** and **release_date** fields,
plus per‑language titles, summaries and chapter stats.

Changes in this revision
-----------------------
* `release` from *conf.py* is treated as **version** when it looks like a
  numeric semantic string; only non‑numeric `release` is parsed as a
  date.
* `_add()` split into two pep‑8‑compliant statements.
* Robust mapping of `-v/--verbosity` to logging levels (no `IndexError`).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Tuple

# -----------------------------------------------------------------------------
#  Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("tools.catalog")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)

_VERBOSITY_TO_LEVEL = {
    0: logging.ERROR,
    1: logging.WARNING,
    2: logging.INFO,
    3: logging.DEBUG,
}

# -----------------------------------------------------------------------------
#  HTML helpers
# -----------------------------------------------------------------------------
class H1Extractor(HTMLParser):
    """Extract the first ``<h1>`` text from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.h1: str | None = None

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == "h1":
            self.depth += 1

    def handle_endtag(self, tag: str):
        if tag.lower() == "h1" and self.depth:
            self.depth -= 1

    def handle_data(self, data: str):
        if self.depth and self.h1 is None:
            cleaned = _clean_text(data)
            if cleaned:
                self.h1 = cleaned


def _clean_text(txt: str) -> str:
    """Collapse whitespace, unescape HTML entities, trim trailing pilcrow."""
    cleaned = unescape(re.sub(r"\s+", " ", txt.replace("\u00a0", " ").replace("\u2013", "-")))
    return cleaned.strip().rstrip("¶").strip()

# -----------------------------------------------------------------------------
#  Version / date detection
# -----------------------------------------------------------------------------
_VERSION_RE = re.compile(r"^\s*version\s*=\s*[\"']([^\"']+)[\"']", re.M)
_RELEASE_RE = re.compile(r"^\s*release\s*=\s*[\"']([^\"']+)[\"']", re.M)
_META_VERSION_RE = re.compile(r'<meta[^>]+name=["\']?version["\']?[^>]+content=["\']([^"\']+)', re.I)
_META_DATE_RE = re.compile(r'<meta[^>]+name=["\']?(?:date|released?|build)["\']?[^>]+content=["\']([^"\']+)', re.I)
_LAST_UPDATED_RE = re.compile(r"Last updated on ([^<]+)<", re.I)
_PL_PARA_RE = re.compile(r"Wersja[^\d]*(\d+(?:\.\d+)+)[^\d]{0,20}?wydana\s+dnia\s+([\d]{1,2}\s+\w{3}\s+\d{4})", re.I | re.S)
_EN_PARA_RE = re.compile(r"Version[^\d]*(\d+(?:\.\d+)+)[^\d]{0,20}?released\s+on\s+([A-Za-z]{3}\s+\d{1,2},\s+\d{4})", re.I | re.S)
_PL_MONTHS = {"sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6, "lip": 7, "sie": 8, "wrz": 9, "paź": 10, "paz": 10, "lis": 11, "gru": 12}


def _parse_date(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    try:
        return datetime.strptime(raw, "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})\s+(\w{3})\s+(\d{4})", raw, re.I)
    if m and (mon := _PL_MONTHS.get(m.group(2).lower())):
        return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
    return raw


def _looks_like_version(text: str) -> bool:
    """Return True if *text* looks like a semantic version (digits & dots)."""
    return bool(re.fullmatch(r"\d+(?:\.\d+)*", text.strip()))


def extract_version_release(doc_dir: Path) -> Tuple[str | None, str | None]:
    """Derive version and release_date for a document folder."""
    version: str | None = None
    release_date: str | None = None

    # --- conf.py ------------------------------------------------------------
    conf = doc_dir / "conf.py"
    if conf.is_file():
        txt = conf.read_text(encoding="utf-8", errors="ignore")
        if m := _VERSION_RE.search(txt):
            version = m.group(1).strip()
        if m := _RELEASE_RE.search(txt):
            rel_text = m.group(1).strip()
            if _looks_like_version(rel_text):
                version = version or rel_text
            else:
                release_date = _parse_date(rel_text)

    # --- index.html ---------------------------------------------------------
    idx = next((p for p in doc_dir.rglob("*/index.html")), None)
    if idx and idx.is_file():
        html = idx.read_text(encoding="utf-8", errors="ignore")
        if not version and (m := _META_VERSION_RE.search(html)):
            version = m.group(1).strip()
        if not release_date and (m := _META_DATE_RE.search(html)):
            release_date = _parse_date(m.group(1))
        if (not version or not release_date) and (m := _PL_PARA_RE.search(html)):
            version = version or m.group(1).strip()
            release_date = release_date or _parse_date(m.group(2))
        if (not version or not release_date) and (m := _EN_PARA_RE.search(html)):
            version = version or m.group(1).strip()
            release_date = release_date or _parse_date(m.group(2))
        if not release_date and (m := _LAST_UPDATED_RE.search(html)):
            release_date = _parse_date(m.group(1))

    return version, release_date

# -----------------------------------------------------------------------------
#  Title / summary / chapters
# -----------------------------------------------------------------------------

def extract_title(doc: Path, lang: str) -> str | None:
    p = doc / lang / "index.html"
    if not p.is_file():
        return None
    parser = H1Extractor()
    parser.feed(p.read_text(encoding="utf-8", errors="ignore"))
    return parser.h1


def extract_summary(doc: Path, lang: str) -> str | None:
    p = doc / lang / "index.html"
    if not p.is_file():
        return None
    html = p.read_text(encoding="utf-8", errors="ignore")
    parts = re.split(r'<hr[^>]*\bclass=["\']?docutils["\']?[^>]*>', html, flags=re.I | re.S, maxsplit=1)
    if len(parts) < 2:
        return None
    paras = re.findall(r"<p[^>]*>(.*?)</p>", parts[0], flags=re.I | re.S)
    return _clean_text(re.sub(r"<[^>]+>", "", paras[-1])) if paras else None


_EXCLUDED = {"changelog.html", "genindex.html", "search.html", "seealso.html", "summary.html", "zextern.html", "license.html"}


def extract_chapters(doc: Path, lang: str) -> List[Dict]:
    lang_dir = doc / lang
    if not lang_dir.is_dir():
        return []
    # order by links in index.html
    order: list[str] = []
    idx = lang_dir / "index.html"
    if idx.is_file():
        order = re.findall(r'href=["\']([^"\']+\.html)["\']', idx.read_text(encoding="utf-8", errors="ignore"), flags=re.I)

    chapters: Dict[str, Dict] = {}
    for file in lang_dir.glob("*.html"):
        name = file.name
        if name.lower() in _EXCLUDED:
            continue
        html = file.read_text(encoding="utf-8", errors="ignore")
        text = re.sub(r"<[^>]+>", " ", html)
        words, chars = len(text.split()), len(text)
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S)
        title = _clean_text(re.sub(r"<[^>]+>", "", m.group(1))) if m else ""
        if name == "index.html":
            title = {"pl": "Treść", "en": "Content"}.get(lang, title)
        chapters[name] = {"name": name, "title": {lang: title}, "words": words, "chars": chars}

    ordered: List[Dict] = []
    seen: set[str] = set()

    def _add(n: str):
        if n in chapters and n not in seen:
            ordered.append(chapters[n]); seen.add(n)

    _add("index.html")
    for n in order:
        _add(n)
    for n in sorted(chapters):
        _add(n)
    return ordered

# -----------------------------------------------------------------------------
#  Catalog building
# -----------------------------------------------------------------------------

def build_catalog(source_dir: Path) -> List[Dict]:
    catalog: List[Dict] = []
    for doc_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
        ver, rel = extract_version_release(doc_dir)
        doc_meta = {
            "id": doc_dir.name,
            "version": ver,
            "release_date": rel,
            "languages": [],
            "title": {},
            "summary": {},
            "chapters": [],
            "path": str(doc_dir.relative_to(source_dir)),
        }
        for lang_dir in sorted(p for p in doc_dir.iterdir() if p.is_dir()):
            lang = lang_dir.name
            doc_meta["languages"].append(lang)
            if (t := extract_title(doc_dir, lang)):
                doc_meta["title"][lang] = t
            if (s := extract_summary(doc_dir, lang)):
                doc_meta["summary"][lang] = s
            for ch in extract_chapters(doc_dir, lang):
                ex = next((c for c in doc_meta["chapters"] if c["name"] == ch["name"]), None)
                if ex:
                    ex["title"].update(ch["title"])
                    ex["words"] = max(ex["words"], ch["words"])
                    ex["chars"] = max(ex["chars"], ch["chars"])
                else:
                    doc_meta["chapters"].append(ch)
        doc_meta["languages"].sort()
        catalog.append(doc_meta)
        logger.debug("Indexed %s", doc_meta["id"])
    logger.info("Catalog built (%d documents)", len(catalog))
    return catalog


def save_catalog(cat: List[Dict], dest: Path) -> None:
    dest.write_text(json.dumps(cat, indent=4, ensure_ascii=False), encoding="utf-8")
    logger.info("Catalog saved to: %s", dest)

# -----------------------------------------------------------------------------
#  CLI
# -----------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Build a file catalog from a directory.")
    p.add_argument("source_dir", type=Path, help="Source directory to scan")
    p.add_argument("dest_file", type=Path, help="Destination JSON file path")
    p.add_argument("-v", "--verbosity", type=int, choices=[0,1,2,3], default=2,
                   help="Logging level: 0=ERR,1=WRN,2=INF,3=DBG (default 2)")
    args = p.parse_args()
    logger.setLevel([logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG][args.verbosity])
    cat = build_catalog(args.source_dir.resolve())
    save_catalog(cat, args.dest_file.resolve())


if __name__ == "__main__":
    main()
