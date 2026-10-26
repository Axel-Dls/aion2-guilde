"""
Accès à la base Supabase depuis les scripts (relevé automatique, migration).

Utilise la clé secrète du projet (secret GitHub SUPABASE_SECRET_KEY), qui passe
outre les règles d'accès : elle ne doit jamais être écrite dans le dépôt ni
dans le site. L'adresse du projet est dans config.json (« supabase_url »), ou
dans la variable SUPABASE_URL.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = 1000  # nombre de lignes par page renvoyées par Supabase


class SupaError(RuntimeError):
    pass


class Supa:
    def __init__(self, url=None, key=None):
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.url = (url or os.environ.get("SUPABASE_URL") or cfg.get("supabase_url") or "").rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SECRET_KEY", "")
        if not self.url or not self.key:
            raise SupaError("SUPABASE_SECRET_KEY (secret GitHub) ou supabase_url (config.json) manquant.")

    def _headers(self, extra=None):
        h = {"apikey": self.key, "Content-Type": "application/json", "Accept": "application/json"}
        if self.key.count(".") == 2:  # ancienne clé « service_role » (JWT) ou tests locaux
            h["Authorization"] = f"Bearer {self.key}"
        return {**h, **(extra or {})}

    def request(self, method, path, params=None, body=None, headers=None, tries=3):
        url = f"{self.url}{os.environ.get('SUPABASE_REST_PATH', '/rest/v1')}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="(),.:*")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        last = None
        for i in range(tries):
            req = urllib.request.Request(url, data=data, method=method, headers=self._headers(headers))
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code < 500:
                    raise SupaError(f"{method} {path} : HTTP {e.code} {detail}") from None
                last = f"HTTP {e.code} {detail}"
            except (urllib.error.URLError, TimeoutError) as e:
                last = str(e)
            time.sleep(2 * (i + 1))
        raise SupaError(f"{method} {path} : {last}")

    # Lecture de toutes les lignes, page par page
    def select(self, table, **params):
        out, start = [], 0
        while True:
            rows = self.request("GET", table, params, headers={"Range": f"{start}-{start + PAGE - 1}", "Range-Unit": "items"})
            out += rows
            if len(rows) < PAGE:
                return out
            start += PAGE

    def insert(self, table, rows, returning=False):
        return self.request("POST", table, body=rows,
                            headers={"Prefer": "return=representation" if returning else "return=minimal"})

    def upsert(self, table, rows, on_conflict, returning=False):
        out = []
        for i in range(0, len(rows), 500):
            res = self.request("POST", table, {"on_conflict": on_conflict}, rows[i:i + 500],
                               {"Prefer": "resolution=merge-duplicates," + ("return=representation" if returning else "return=minimal")})
            out += res or []
        return out

    def update(self, table, filters, values):
        return self.request("PATCH", table, filters, values, {"Prefer": "return=minimal"})
