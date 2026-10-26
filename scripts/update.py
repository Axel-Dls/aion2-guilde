#!/usr/bin/env python3
"""
Relevé automatique : GS (Item Level) et CP de chaque perso suivi, récupérés sur
le site officiel d'Aion 2 (global) et enregistrés dans la base Supabase.

Lancé par GitHub Actions (.github/workflows/update.yml) :
  python scripts/update.py                 relevé complet (bouton « Run workflow »)
  python scripts/update.py --si-necessaire relevé seulement s'il est demandé (bouton
                                           « Relancer » de l'admin, ajout d'un perso)
                                           ou si le dernier date de plus de 11 h

Les journaux GitHub sont publics : ils n'affichent que des comptes, ni pseudo ni
valeur. Aucune dépendance en dehors de Python.

Les adresses utilisées sont celles de la page officielle « Character Info »
(aion2.plaync.com). Elles ne sont pas documentées par NCSoft et peuvent changer :
si moins de la moitié des persos sont trouvés, le passage échoue et GitHub
prévient par e-mail.
"""

import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from supa import Supa

SITE = "https://aion2.plaync.com"
SEARCH = "https://api-search.plaync.com/aion2global/search/v2/character"
LANG = "en-US"
REGIONS = ["eu", "naw", "nae", "la", "as"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (aion2-guilde tracker)",
    "Accept": "application/json",
    "Referer": f"{SITE}/en-us/characters/index",
    "Origin": SITE,
}
PAUSE = 0.6            # secondes entre deux requêtes, pour rester discret
GS_DROP_ALERT = 30     # baisse de GS (par rapport au relevé précédent) signalée
MIN_SUCCESS = 0.5      # en dessous de cette part de persos trouvés, le passage échoue
REFRESH_HOURS = 11     # en mode --si-necessaire : relevé si le dernier est plus ancien

# Libellés des signalements (repris tels quels par le site et l'admin)
ISSUE_LABEL = {
    "not_found": "Introuvable",
    "unknown_server": "Serveur inconnu",
    "error": "Échec de lecture",
    "left_guild": "Hors légion",
    "gs_drop": "GS en baisse",
}


def log(*a):
    print(*a, flush=True)


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


# ---------------------------------------------------------------- site officiel

def get_json(url, params, tries=3):
    full = f"{url}?{urllib.parse.urlencode(params)}"
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(full, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8")
            time.sleep(PAUSE)
            return json.loads(body)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url} : {last}")


class Servers:
    """Nom de serveur → serveur (avec sa région). Charge la région de config.json,
    et les autres seulement si un serveur demandé n'y figure pas."""

    def __init__(self, preferred):
        self.order = [preferred] + [r for r in REGIONS if r != preferred]
        self.loaded, self.by_name = set(), {}
        self._load(preferred)

    def _load(self, region):
        self.loaded.add(region)
        try:
            data = get_json(f"{SITE}/en-us/api/gameinfo/servers", {"lang": LANG, "region": region})
        except RuntimeError as e:
            log(f"  liste des serveurs {region} indisponible : {e}")
            return
        for s in data.get("serverList", []):
            s = {**s, "region": region}
            for k in (norm(s["serverName"]), norm(s["serverShortName"])):
                self.by_name.setdefault(k, s)

    def _load_all(self):
        for region in self.order:
            if region not in self.loaded:
                self._load(region)

    def get(self, name):
        if norm(name) not in self.by_name:
            self._load_all()
        return self.by_name.get(norm(name))

    def suggest(self, name):
        self._load_all()
        close = difflib.get_close_matches(norm(name), list(self.by_name), n=1)
        return self.by_name[close[0]]["serverName"] if close else None

    def count(self):
        return len({(s["region"], s["serverId"]) for s in self.by_name.values()})


def find_character(name, server_id, region):
    data = get_json(SEARCH, {
        "keyword": name, "serverId": server_id, "page": 1, "size": 30,
        "region": region, "localeInfo": LANG,
    })
    for c in data.get("list", []):
        clean = re.sub(r"<[^>]+>", "", c.get("name", ""))
        if norm(clean) == norm(name) and int(c["serverId"]) == int(server_id):
            return c
    return None


def get_info(character_id, server_id, region):
    return get_json(f"{SITE}/api/character/info", {
        "lang": LANG,
        "characterId": urllib.parse.unquote(character_id),
        "serverId": server_id,
        "region": region,
    })


def item_level(info):
    for s in (info.get("stat") or {}).get("statList") or []:
        if s.get("type") == "ItemLevel":
            return s.get("value")
    return None


# ---------------------------------------------------------------- un perso

def update_member(m, servers, guild, now):
    """Interroge le site officiel pour un perso de la table membres.
    Renvoie (valeurs à enregistrer, relevé du jour ou None, signalements [(type, détail)])."""
    srv = servers.get(m["serveur"])
    if not srv:
        hint = servers.suggest(m["serveur"])
        return {"etat": "unknown_server"}, None, [
            ("unknown_server", f"serveur « {m['serveur']} » inconnu" + (f", « {hint} » ?" if hint else ""))]

    try:
        char = find_character(m["pseudo"], srv["serverId"], srv["region"])
        if not char:
            return {"etat": "not_found", "server_id": srv["serverId"], "region": srv["region"]}, None, [
                ("not_found", f"introuvable sur {srv['serverName']} : pseudo changé ou mal orthographié ?")]
        info = get_info(char["characterId"], srv["serverId"], srv["region"])
        p = info["profile"]
    except Exception as e:  # réseau ou format inattendu : on garde les anciennes valeurs
        return {"etat": "error"}, None, [("error", str(e)[:200])]

    il = item_level(info)
    values = {
        "classe": p.get("className"),
        "niveau": p.get("characterLevel"),
        "cp": p.get("combatPower"),
        "gs": il,
        "legion": p.get("regionName") or "",
        "image": p.get("profileImage") or "",
        "character_id": char["characterId"],
        "server_id": srv["serverId"],
        "region": srv["region"],
        "etat": "ok",
        "dernier_ok": now.isoformat(timespec="seconds"),
    }
    issues = []
    if guild and values["legion"] and norm(values["legion"]) != norm(guild):
        issues.append(("left_guild", f"dans la légion « {values['legion']} »"))
    point = {"membre_id": m["id"], "jour": now.date().isoformat(), "gs": il, "cp": values["cp"], "source": "site"}
    return values, point, issues


# ---------------------------------------------------------------- passage complet

def step_summary(ok, total, issues):
    """Résumé affiché sur la page du passage dans GitHub Actions. Ces pages sont
    publiques : on n'y met que des comptes, ni pseudos ni valeurs."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    by_type = {}
    for i in issues:
        by_type[i["type"]] = by_type.get(i["type"], 0) + 1
    lines = [f"## {ok}/{total} persos à jour", ""]
    lines += [f"- {ISSUE_LABEL.get(t, t)} : {n}" for t, n in by_type.items()] or ["Aucun signalement."]
    lines += ["", "Le détail est visible dans la page Admin du site (« État du suivi »)."]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def needed(db, now):
    """Mode --si-necessaire : (faut-il un relevé, déclencheur)."""
    last = db.select("passages", select="debut", order="debut.desc", limit=1)
    since = last[0]["debut"] if last else None
    if since:
        asked = db.select("demandes_maj", select="id", demande_le=f"gt.{since}", limit=1)
        if asked:
            return True, "demande"
    if not since or datetime.fromisoformat(since) < now - timedelta(hours=REFRESH_HOURS):
        return True, "planifié"
    return False, None


def previous_gs(db, ids, today):
    """Dernier GS connu avant aujourd'hui pour chaque perso (sur 30 jours)."""
    since = (today - timedelta(days=30)).isoformat()
    rows = db.select("releves", select="membre_id,jour,gs", jour=f"gte.{since}", gs="not.is.null", order="jour.asc")
    out = {}
    for r in rows:
        if r["membre_id"] in ids and r["jour"] < today.isoformat():
            out[r["membre_id"]] = r
    return out


def main():
    now = datetime.now(timezone.utc)
    db = Supa()
    trigger = "manuel" if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" else "planifié"
    if "--si-necessaire" in sys.argv:
        go, trigger = needed(db, now)
        if not go:
            log("Pas de relevé nécessaire pour l'instant.")
            return

    settings = {r["cle"]: r["valeur"] for r in db.select("reglages")}
    guild, region = settings.get("guilde", ""), settings.get("region", "eu")
    members = db.select("membres", select="id,pseudo,serveur", suivi="is.true", order="id.asc")
    # Début daté par la base (même horloge que les demandes de relevé)
    run = db.insert("passages", [{"total": len(members), "declencheur": trigger}], returning=True)[0]
    servers = Servers(region)
    log(f"{len(members)} persos suivis · région {region} · {servers.count()} serveurs chargés · {trigger}")

    before = previous_gs(db, {m["id"] for m in members}, now.date())
    points, issues, ok = [], [], 0
    for n, m in enumerate(members, 1):
        values, point, found = update_member(m, servers, guild, now)
        prev = before.get(m["id"])
        if point and point["gs"] is not None and prev and point["gs"] < prev["gs"] - GS_DROP_ALERT:
            found.append(("gs_drop", f"GS {prev['gs']} → {point['gs']} depuis le {prev['jour']}"))
        db.update("membres", {"id": f"eq.{m['id']}"}, values)
        if point:
            points.append(point)
        ok += values["etat"] == "ok"
        for t, detail in found:
            issues.append({"name": m["pseudo"], "type": t, "detail": detail})
        # Journal public : ni pseudo ni valeur, seulement le résultat
        log(f"  {n:>3}. {'ok' if values['etat'] == 'ok' else ISSUE_LABEL.get(values['etat'], values['etat'])}"
            + (f" (+{len(found)} signalement)" if found and values["etat"] == "ok" else ""))

    if points:
        db.upsert("releves", points, "membre_id,jour")
    end = datetime.now(timezone.utc)
    db.update("passages", {"id": f"eq.{run['id']}"},
              {"fin": end.isoformat(timespec="seconds"), "ok": ok, "total": len(members), "signalements": issues})
    step_summary(ok, len(members), issues)
    log(f"Terminé : {ok}/{len(members)} à jour, {len(issues)} signalement(s)")

    # Moins de la moitié des persos trouvés : le site officiel a sans doute changé.
    if members and ok < len(members) * MIN_SUCCESS:
        sys.exit(f"Seulement {ok}/{len(members)} persos mis à jour : le site officiel a peut-être changé.")


if __name__ == "__main__":
    main()
