"""Client for the knowledge pipeline (ai_service) — the moat feeding the product.

The platform calls ai_service's MCP-style endpoints (/knowledge/concept,
/knowledge/neighbors) to enrich the clinical UI (e.g. ICD-11 crosswalk for a
patient's conditions). Degrades gracefully: if AI_SERVICE_URL is unset or the
service is unreachable, every call returns empty (same NullProvider pattern as
SMS/billing) so the clinic app never depends on the pipeline being up. Uses
stdlib urllib (no extra dependency); ``fetcher`` is injectable for tests.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class KnowledgeClient:
    def __init__(self, base_url=None, fetcher=None, timeout=2):
        self.base_url = (base_url if base_url is not None else os.getenv("AI_SERVICE_URL", "")).rstrip("/")
        self._fetch = fetcher
        self.timeout = timeout

    def _get(self, path, params):
        if not self.base_url:
            return None
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        try:
            if self._fetch is not None:
                return self._fetch(url)
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except Exception:
            # best-effort enrichment: any failure degrades to "no data"
            return None

    def concept(self, term):
        data = self._get("/knowledge/concept", {"term": term})
        if not data or "detail" in data:  # 'detail' => not found
            return None
        return data

    def neighbors(self, term):
        data = self._get("/knowledge/neighbors", {"term": term})
        return (data or {}).get("neighbors", [])


def knowledge_client():
    return KnowledgeClient()
