import os
import json
import logging
from datetime import datetime
from urllib.parse import quote
from typing import Optional, List

from django.conf import settings
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import Http404, FileResponse
from django.shortcuts import render
from django.utils import translation
from django.views import View

logger = logging.getLogger(__name__)


#################################################
# Documentation Handling View
#################################################

class DocsView(View):
    """Django view for serving documentation files and directory listings."""
    PER_PAGE = 10

    #-----------------------------------------
    # Helper Methods - Language & Localization
    #-----------------------------------------
    
    def _get_user_language(self, request) -> str:
        """Extract user's preferred language code from request."""
        if (param := request.GET.get("lang")):
            return param.split("-")[0]
        if (lang := getattr(request, "LANGUAGE_CODE", None)):
            return lang.split("-")[0]
        accept = request.headers.get("Accept-Language", "")
        return accept.split(",")[0].split("-")[0] if accept else "en"

    def _parse_iso_date(self, value) -> Optional[datetime]:
        """Parse ISO date string or extract date from language dictionary."""
        if not value:
            return None
        if isinstance(value, dict):
            value = value.get(self.user_lang) or value.get("en")
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    #-----------------------------------------
    # Helper Methods - URL Generation
    #-----------------------------------------
    
    def _build_href_for_lang(self, base_path: str, lang: str, *, allow_fallback: bool = False) -> str:
        """Create URL for accessing documentation in specified language."""
        if base_path.lower().endswith((".html", ".htm")):
            return f"/docs/{quote(base_path)}"

        rel_dir = base_path.rstrip("/")
        lang_index = os.path.join(rel_dir, lang, "index.html")
        if os.path.isfile(os.path.join(settings.DOCS_DIR, lang_index)):
            return f"/docs/{quote(lang_index)}"

        if allow_fallback:
            en_index = os.path.join(rel_dir, "en", "index.html")
            if os.path.isfile(os.path.join(settings.DOCS_DIR, en_index)):
                return f"/docs/{quote(en_index)}"

        return f"/docs/{quote(rel_dir)}/"

    def _build_href(self, base_path: str) -> str:
        """Create URL for documentation in user's language with English fallback."""
        return self._build_href_for_lang(base_path, self.user_lang, allow_fallback=True)

    #-----------------------------------------
    # Helper Methods - Content Discovery
    #-----------------------------------------
    
    def _discover_langs(self, rel_dir: str) -> List[str]:
        """Find available language versions in the given directory."""
        dir_path = os.path.join(settings.DOCS_DIR, rel_dir)
        if not os.path.isdir(dir_path):
            return []
        return sorted([
            name for name in os.listdir(dir_path)
            if os.path.isfile(os.path.join(dir_path, name, "index.html"))
        ])

    def _paginate(self, docs: List[dict], page_number):
        """Paginate documents and handle pagination errors."""
        paginator = Paginator(docs, self.PER_PAGE)
        try:
            page_obj = paginator.page(page_number)
        except (PageNotAnInteger, EmptyPage):
            page_obj = paginator.page(1)
        return page_obj, list(page_obj.object_list)

    #-----------------------------------------
    # Main Request Handler
    #-----------------------------------------
    
    def get(self, request, path: str = ""):
        """
        Handle GET requests for documentation.
        
        Shows catalog if path is empty, directory listing if path is directory,
        or serves file if path points to a file.
        """
        self.user_lang = self._get_user_language(request)
        translation.activate(self.user_lang)

        page_number = request.GET.get("page", 1)

        #----------------------
        # Display documentation catalog
        #----------------------
        if path in ("", "/"):
            catalog_path = os.path.join(settings.DOCS_DIR, "catalog.json")
            if not os.path.isfile(catalog_path):
                raise Http404("catalog.json not found in DOCS_DIR")
            
            try:
                with open(catalog_path, encoding="utf-8") as f:
                    catalog = json.load(f)
            except json.JSONDecodeError:
                raise Http404("catalog.json is not valid JSON")

            # Process catalog entries
            entries = []
            if isinstance(catalog, list):
                for e in catalog:
                    lang_tag = e.get("lang")
                    if lang_tag and lang_tag.split("-")[0] != self.user_lang:
                        continue
                    date_val = self._parse_iso_date(e.get("release_date") or e.get("date"))
                    entries.append((date_val, e))
                entries.sort(key=lambda t: t[0] or datetime.min, reverse=True)
            else:
                entries.append((None, catalog))

            # Build document list from entries
            docs_all = []
            for date_val, e in entries:
                if not isinstance(e, dict):
                    continue
                raw_name = e.get("name") or e.get("title") or "Unnamed"
                if isinstance(raw_name, dict):
                    name = raw_name.get(self.user_lang) or raw_name.get("en") or next(iter(raw_name.values()))
                else:
                    name = raw_name

                version = e.get("version")
                summary = (
                    e.get("summary", "") if not isinstance(e.get("summary"), dict)
                    else e["summary"].get(self.user_lang) or e["summary"].get("en")
                )
                raw_path = e.get("path") or e.get("url") or ""
                langs = e.get("langs") or self._discover_langs(raw_path)
                lang_links = [(l, self._build_href_for_lang(raw_path, l)) for l in langs]
                href = self._build_href_for_lang(raw_path, self.user_lang, allow_fallback=True)

                docs_all.append({
                    "name": name,
                    "href": href,
                    "date": date_val,
                    "version": version,
                    "langs": langs,
                    "lang_links": lang_links,
                    "summary": summary,
                })

            available_langs = sorted({lang for doc in docs_all for lang in doc.get("langs", [])})
            logger.debug("Available languages for available documents: %s", available_langs)

            page_obj, docs = self._paginate(docs_all, page_number)

            global_index_start = (page_obj.number - 1) * self.PER_PAGE
            return render(request, "docs.html", {
                "heading": translation.gettext("Documentation catalog"),
                "global_index_start": global_index_start,
                "lang": self.user_lang,
                "docs": docs,
                "available_langs": available_langs,
                "page_obj": page_obj,
                "paginator": page_obj.paginator,
            })

        full_path = os.path.join(settings.DOCS_DIR, path)
        # Security check to prevent directory traversal attacks
        if not os.path.abspath(full_path).startswith(os.path.abspath(settings.DOCS_DIR)):
            raise Http404("Access denied")
            
        #----------------------
        # Handle directory listing
        #----------------------
        if os.path.isdir(full_path):
            try:
                items = sorted(os.listdir(full_path), key=lambda n: os.path.getmtime(os.path.join(full_path, n)), reverse=True)
            except (FileNotFoundError, PermissionError):
                raise Http404("Directory not found or access denied")

            docs_all = []
            for name in items:
                item_path = os.path.join(full_path, name)
                rel_path = os.path.join(path, name) if path else name
                try:
                    date_val = datetime.fromtimestamp(os.path.getmtime(item_path))
                except (OSError, PermissionError):
                    date_val = None

                if os.path.isdir(item_path):
                    langs = self._discover_langs(rel_path)
                    lang_links = [(l, self._build_href_for_lang(rel_path, l)) for l in langs]
                    href = self._build_href_for_lang(rel_path, self.user_lang, allow_fallback=True)
                else:
                    langs = []
                    lang_links = []
                    href = f"/docs/{quote(rel_path)}"

                docs_all.append({
                    "name": name,
                    "href": href,
                    "date": date_val,
                    "version": None,
                    "langs": langs,
                    "lang_links": lang_links,
                    "summary": "",
                })

            available_langs = sorted({lang for doc in docs_all for lang in doc.get("langs", [])})
            page_obj, docs = self._paginate(docs_all, page_number)

            global_index_start = (page_obj.number - 1) * self.PER_PAGE
            return render(request, "docs.html", {
                "heading": f"Contents of /docs/{path}",
                "global_index_start": global_index_start,
                "lang": self.user_lang,
                "docs": docs,
                "available_langs": available_langs,
                "page_obj": page_obj,
                "paginator": page_obj.paginator,
            })

        #----------------------
        # Handle file serving
        #----------------------
        if os.path.isfile(full_path):
            try:
                return FileResponse(open(full_path, "rb"))
            except (IOError, PermissionError):
                raise Http404("Cannot access requested file")

        raise Http404("File or directory not found")