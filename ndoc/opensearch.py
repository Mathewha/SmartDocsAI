import os
import django
from django.conf import settings
from opensearchpy import OpenSearch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndoc.settings")  # ← change if needed
django.setup()

def get_client() -> OpenSearch:
    """Create an OpenSearch client from settings.OPENSEARCH."""
    cfg = settings.OPENSEARCH
    return OpenSearch(
        hosts=[{"host": cfg["HOST"], "port": cfg["PORT"]}],
        http_auth=(cfg["USER"], cfg["PASSWORD"]) if cfg.get("USER") else None,
        use_ssl=cfg.get("USE_SSL", False),
        verify_certs=cfg.get("VERIFY_CERTS", False),
    )
