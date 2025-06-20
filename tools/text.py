 #!/usr/bin/env python
"""
tools.text
~~~~~~~~~~

Extracts text from all chapters in a JSON catalog, reads source HTML files,
handles tables by merging row cells into single lines, strips pilcrow characters,
skips elements with CSS class 'toctree-wrapper' (always) and
'<div class="toctree-wrapper compound">' only in non-index.html files,
treats <strong>, <em>, <code>, <span>, <pre> as inline,
formats unordered list items (<li>) with two-space indent and '-' prefix,
manages paragraphs to avoid breaking inline text, inserts blank lines before <h2>,
collects entire <pre> blocks into single lines,
and prefixes each line with spaces according to HTML nesting depth.

Usage:
    text.py [-h] [-v {0,1,2,3}] json_file input_dir output_subdir
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from html.parser import HTMLParser
from pathlib import Path

logger = logging.getLogger("tools.text")
_VERBOSITY = {0: logging.ERROR, 1: logging.WARNING, 2: logging.INFO, 3: logging.DEBUG}


class TableAwareExtractor(HTMLParser):
    INLINE_TAGS = {"strong", "em", "code", "span", "pre"}
    LIST_ITEM_TAG = "li"
    LIST_ITEM_PREFIX = "  - "

    def __init__(self, is_index: bool = False) -> None:
        super().__init__()
        self.lines: list[str] = []
        self.current_cells: list[str] = []
        self.in_row = False
        self.in_cell = False
        self.in_paragraph = False
        self.current_para: list[str] = []
        self.skip_section = False
        self.skip_stack: list[str] = []
        self.depth = 0
        self.is_index = is_index
        self.in_list_item = False
        self.in_pre = False
        self.pre_buffer = ''

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str]]) -> None:
        tag_lower = tag.lower()
        # skip toctree-wrapper sections
        if tag_lower in ("div", "section"):
            for name, value in attrs:
                if name.lower() == "class":
                    classes = value.split()
                    cond = "toctree-wrapper" in classes and (
                        "compound" not in classes or not self.is_index
                    )
                    if cond:
                        self.skip_section = True
                        self.skip_stack.append(tag_lower)
                        return
        if self.skip_section:
            if tag_lower == self.skip_stack[-1]:
                self.skip_stack.append(tag_lower)
            return
        # handle pre blocks
        if tag_lower == "pre":
            self.in_pre = True
            self.pre_buffer = ''
            return
        # list item start
        if tag_lower == self.LIST_ITEM_TAG:
            self.in_list_item = True
            self.current_para = []
            return
        # blank line before <h2>
        if tag_lower == "h2":
            self.lines.append("")
            return
        # start paragraph
        if tag_lower == "p" and not self.in_row:
            self.in_paragraph = True
            self.current_para = []
            return
        # depth increase for block tags
        if tag_lower not in self.INLINE_TAGS and tag_lower not in ("tr", "td", "th", "p", self.LIST_ITEM_TAG):
            self.depth += 1
        # table row start
        if tag_lower == "tr":
            self.in_row = True
            self.current_cells.clear()
        elif tag_lower in ("td", "th") and self.in_row:
            self.in_cell = True

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        # skip section logic
        if self.skip_section:
            if self.skip_stack and tag_lower == self.skip_stack[-1]:
                self.skip_stack.pop()
                if not self.skip_stack:
                    self.skip_section = False
            return
        # end pre: flush entire buffer
        if tag_lower == "pre" and self.in_pre:
            text = self.pre_buffer.replace("\n", " ").strip()
            if text:
                self.lines.append(" " * self.depth + text)
            self.in_pre = False
            self.pre_buffer = ''
            return
        # list item end
        if tag_lower == self.LIST_ITEM_TAG and self.in_list_item:
            text = " ".join(self.current_para).strip()
            if text:
                self.lines.append(self.LIST_ITEM_PREFIX + text)
            self.in_list_item = False
            self.current_para = []
            return
        # end paragraph
        if tag_lower == "p" and self.in_paragraph:
            text = " ".join(self.current_para).strip()
            if self.in_row:
                if text:
                    self.current_cells.append(text)
            else:
                if text:
                    self.lines.append(" " * self.depth + text)
            self.in_paragraph = False
            self.current_para = []
            return
        # end cell
        if tag_lower in ("td", "th") and self.in_cell:
            self.in_cell = False
        # end row
        elif tag_lower == "tr" and self.in_row:
            row_text = " ".join(self.current_cells).strip()
            if row_text:
                self.lines.append(" " * self.depth + row_text)
            self.in_row = False
        # block separation
        elif tag_lower == "div" and not self.in_row and not self.in_paragraph:
            self.lines.append(" " * self.depth)
        # depth decrease
        if tag_lower not in self.INLINE_TAGS and tag_lower not in ("tr", "td", "th", "p", self.LIST_ITEM_TAG, "pre") and self.depth > 0:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_section:
            return
        if self.in_pre:
            self.pre_buffer += data
            return
        clean = data.replace("¶", "").strip()
        if not clean:
            return
        if self.in_paragraph or self.in_list_item:
            self.current_para.append(clean)
        elif self.in_row:
            self.current_cells.append(clean)
        else:
            self.lines.append(" " * self.depth + clean)

    def get_text(self, sep: str = "\n") -> str:
        out: list[str] = []
        for line in self.lines:
            if line or (out and out[-1]):
                out.append(line)
        filtered = [ln for ln in out if any(ch.isalpha() for ch in ln)]
        return sep.join(filtered)


def extract_text(json_path: Path, input_dir: Path, output_subdir: str) -> None:
    try:
        catalog_text = json_path.read_text(encoding="utf-8")
    except Exception:
        logger.error("Cannot read JSON file: %s", json_path)
        sys.exit(1)
    catalog = json.loads(catalog_text)

    for entry in catalog:
        doc_id = entry.get("id")
        for lang in entry.get("languages", []):
            chapters = entry.get("chapters") or []
            if not chapters:
                logger.warning("%s [%s] - no chapters, skipping", doc_id, lang)
                continue

            out_dir = input_dir.joinpath(doc_id, lang, output_subdir)
            out_dir.mkdir(parents=True, exist_ok=True)
            logger.debug("Output dir: %s", out_dir)

            for chap in chapters:
                name = chap.get("name", "")
                src = input_dir.joinpath(doc_id, lang, name)
                if not src.is_file():
                    logger.error("Missing HTML: %s", src)
                    continue
                logger.info("Processing: %s", src)

                raw = src.read_text(encoding="utf-8")
                low = raw.lower()
                is_idx = Path(name).name.lower() == "index.html"
                i1 = low.find("<h1")
                if i1 != -1:
                    i2 = low.find("</h1>", i1)
                    raw = raw[(i2 + 5) if i2 != -1 else i1 :]
                    low = raw.lower()
                i3 = low.find("<footer>")
                if i3 != -1:
                    raw = raw[:i3]

                extractor = TableAwareExtractor(is_index=is_idx)
                extractor.feed(raw)
                out_text = extractor.get_text()

                stem = Path(name).stem
                txt_file = out_dir.joinpath(f"{stem}.txt")
                txt_file.write_text(out_text, encoding="utf-8")
                logger.info("Written: %s", txt_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from HTML chapters.")
    parser.add_argument("json_file", type=Path, help="Path to catalog JSON")
    parser.add_argument("input_dir", type=Path, help="Root directory of HTML files")
    parser.add_argument(
        "output_subdir", type=str, help="Subdir under each <id>/<lang> for txt"
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        choices=[0, 1, 2, 3],
        default=2,
        help="Log level: 0=ERROR,1=WARNING,2=INFO,3=DEBUG",
    )
    args = parser.parse_args()
    logging.basicConfig(level=_VERBOSITY[args.verbosity], format="%(levelname)s | %(message)s")
    logger.setLevel(_VERBOSITY[args.verbosity])

    if not args.json_file.is_file():
        logger.error("JSON file not found: %s", args.json_file)
        sys.exit(1)
    if not args.input_dir.is_dir():
        logger.error("Input dir not found: %s", args.input_dir)
        sys.exit(1)

    extract_text(args.json_file.resolve(), args.input_dir.resolve(), args.output_subdir)


if __name__ == "__main__":
    main()
