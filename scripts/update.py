#!/usr/bin/env python3
"""
Met à jour les données du site : GS (Item Level) et CP de chaque membre listé
dans members.csv, récupérés sur le site officiel d'Aion 2 (global).

Les données sont chiffrées avec le mot de passe du site (secret GitHub
SITE_PASSWORD) dans data/db.enc.json : le dépôt et les journaux GitHub étant
publics, ils n'affichent aucune valeur. Sans ce secret, elles sont écrites en
clair dans data/db.json (avec un avertissement).

Lancé par GitHub Actions (.github/workflows/update.yml) deux fois par jour, à
chaque modification de la liste des membres, ou à la main.
Dépendance : « cryptography » (chiffrement), installée par le workflow.

Les adresses utilisées sont celles de la page officielle « Character Info »
(aion2.plaync.com). Elles ne sont pas documentées par NCSoft et peuvent changer :
si moins de la moitié des persos sont trouvés, le passage échoue et GitHub
prévient par e-mail.
"""

import csv
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import vault

ROOT = Path(__file__).resolve().parent.parent
MEMBERS = ROOT / "members.csv"
CONFIG = ROOT / "config.json"
DB = ROOT / "data" / "db.json"            # version en clair (seulement sans mot de passe)
DB_ENC = ROOT / "data" / "db.enc.json"    # version chiffrée
MANUAL = ROOT / "data" / "historique-manuel.csv"  # importé une fois dans les données chiffrées, puis supprimé

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
MAX_HISTORY = 400      # jours d'historique conservés par membre
GS_DROP_ALERT = 30     # baisse de GS (par rapport au relevé précédent) signalée
MIN_SUCCESS = 0.5      # en dessous de cette part de persos trouvés, le passage échoue
KEEP = ("serverId", "characterId", "region", "className", "level", "cp", "itemLevel", "legion", "image", "lastOk")

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


# ---------------------------------------------------------------- fichiers du dépôt

def read_members():
    """members.csv : « pseudo,serveur,statut » par ligne. Les lignes # (persos en attente) sont ignorées."""
    out, seen = [], set()
    with MEMBERS.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip() or row[0].strip().startswith("#") or norm(row[0]) == "pseudo":
                continue
            name = row[0].strip()
            server = row[1].strip() if len(row) > 1 else ""
            role = row[2].strip() if len(row) > 2 else ""
            if (norm(name), norm(server)) not in seen:
                seen.add((norm(name), norm(server)))
                out.append({"name": name, "server": server, "role": role or "Membre"})
    return out


def to_int(v):
    """« 2049 », « 96,80K » ou « 96.8k » → entier."""
    v = (v or "").strip().replace(" ", "").replace(",", ".")
    if not v:
        return None
    mult = 1000 if v.lower().endswith("k") else 1
    try:
        return int(round(float(v.rstrip("kK")) * mult))
    except ValueError:
        return None


def read_manual_csv():
    """data/historique-manuel.csv : relevés faits à la main (pseudo,date,gs,cp) → liste de lignes."""
    rows = []
    if MANUAL.exists():
        with MANUAL.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if len(row) < 3 or row[0].strip().startswith("#") or norm(row[0]) == "pseudo":
                    continue
                gs, cp = to_int(row[2]), (to_int(row[3]) if len(row) > 3 else None)
                if gs is not None or cp is not None:
                    rows.append({"name": row[0].strip(), "d": row[1].strip(), "il": gs, "cp": cp})
    return rows


def index_manual(rows):
    out = {}
    for r in rows:
        out.setdefault(norm(r["name"]), []).append({"d": r["d"], "cp": r.get("cp"), "il": r.get("il")})
    return out


def merge_history(history, today_point, manual):
    """Un point par jour, trié par date : le point du jour remplace l'éventuel précédent,
    les relevés manuels complètent les valeurs manquantes."""
    by_date = {h["d"]: dict(h) for h in history if h.get("d")}
    if today_point:
        by_date[today_point["d"]] = today_point
    for p in manual:
        cur = by_date.setdefault(p["d"], dict(p))
        for k in ("cp", "il"):
            if cur.get(k) is None and p.get(k) is not None:
                cur[k] = p[k]
    return sorted(by_date.values(), key=lambda h: h["d"])[-MAX_HISTORY:]


# ---------------------------------------------------------------- un membre

def update_member(m, prev, servers, manual, now, guild, aliases=()):
    """Renvoie l'entrée à jour du membre et ses signalements [(type, détail)]."""
    entry = {
        "key": f"{norm(m['server'])}:{norm(m['name'])}",
        "name": prev.get("name", m["name"]),
        "server": m["server"],
        "role": m["role"],
        "history": prev.get("history", []),
        **{k: prev[k] for k in KEEP if k in prev},
    }

    srv = servers.get(m["server"])
    if not srv:
        hint = servers.suggest(m["server"])
        entry["status"] = "unknown_server"
        return entry, [("unknown_server", f"serveur « {m['server']} » inconnu" + (f", « {hint} » ?" if hint else ""))]
    entry.update(server=srv["serverName"], serverId=srv["serverId"], region=srv["region"])

    try:
        char = find_character(m["name"], srv["serverId"], srv["region"])
        if not char:
            entry["status"] = "not_found"
            return entry, [("not_found", f"introuvable sur {srv['serverName']} : pseudo changé ou mal orthographié ?")]
        info = get_info(char["characterId"], srv["serverId"], srv["region"])
        p = info["profile"]
    except Exception as e:  # réseau ou format inattendu : on garde les anciennes valeurs
        entry["status"] = "error"
        return entry, [("error", str(e)[:200])]

    previous = [h for h in entry["history"] if h.get("il") is not None and h["d"] < now.date().isoformat()]
    il = item_level(info)
    entry.update({
        "name": p.get("characterName") or m["name"],
        "className": p.get("className"),
        "level": p.get("characterLevel"),
        "cp": p.get("combatPower"),
        "itemLevel": il,
        "legion": p.get("regionName") or "",
        "image": p.get("profileImage") or "",
        "characterId": char["characterId"],
        "status": "ok",
        "lastOk": now.isoformat(timespec="seconds"),
    })
    entry["history"] = merge_history(entry["history"], {"d": now.date().isoformat(), "cp": entry["cp"], "il": il},
                                     [p for n in (entry["name"], *aliases) for p in manual.get(norm(n), [])])

    issues = []
    if guild and entry["legion"] and norm(entry["legion"]) != norm(guild):
        issues.append(("left_guild", f"dans la légion « {entry['legion']} »"))
    if il is not None and previous and il < previous[-1]["il"] - GS_DROP_ALERT:
        issues.append(("gs_drop", f"GS {previous[-1]['il']} → {il} depuis le {previous[-1]['d']}"))
    return entry, issues


# ---------------------------------------------------------------- passage complet

def step_summary(db, removed):
    """Résumé affiché sur la page du passage dans GitHub Actions. Ces pages sont
    publiques : on n'y met que des comptes, ni pseudos ni valeurs."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    run = db["run"]
    by_type = {}
    for i in run["issues"]:
        by_type[i["type"]] = by_type.get(i["type"], 0) + 1
    lines = [f"## {run['ok']}/{run['total']} persos à jour", ""]
    lines += [f"- {ISSUE_LABEL.get(t, t)} : {n}" for t, n in by_type.items()] or ["Aucun signalement."]
    if removed:
        lines.append(f"- Retirés du suivi depuis le passage précédent : {len(removed)}")
    lines += ["", "Le détail est visible dans la page Admin du site (« État du suivi »)."]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def load_previous():
    """Données du passage précédent → (db, sel). Lit la version chiffrée si elle existe
    (avec SITE_PASSWORD, ou SITE_PASSWORD_PREVIOUS juste après un changement de mot de passe)."""
    password = os.environ.get("SITE_PASSWORD", "")
    if DB_ENC.exists():
        box = json.loads(DB_ENC.read_text(encoding="utf-8"))
        for i, pw in enumerate(p for p in (password, os.environ.get("SITE_PASSWORD_PREVIOUS", "")) if p):
            try:
                db, salt = vault.decrypt(box, pw)
                if i:
                    log("Mot de passe précédent utilisé : les données seront rechiffrées avec le nouveau.")
                return db, (salt if i == 0 else None)
            except vault.WrongPassword:
                continue
        sys.exit("Impossible de déchiffrer data/db.enc.json : vérifie le secret SITE_PASSWORD "
                 "(après un changement de mot de passe, mets l'ancien dans SITE_PASSWORD_PREVIOUS).")
    if DB.exists():
        return json.loads(DB.read_text(encoding="utf-8")), None
    return {}, None


def save(db, salt):
    DB.parent.mkdir(parents=True, exist_ok=True)
    password = os.environ.get("SITE_PASSWORD", "")
    if password:
        DB_ENC.write_text(json.dumps(vault.encrypt(db, password, salt)) + "\n", encoding="utf-8")
        DB.unlink(missing_ok=True)
        MANUAL.unlink(missing_ok=True)  # son contenu est désormais dans les données chiffrées
    else:
        log("::warning::Secret SITE_PASSWORD absent : données écrites EN CLAIR dans data/db.json.")
        DB.write_text(json.dumps(db, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    guild, region = cfg.get("guild", ""), cfg.get("region", "eu")
    aliases = {norm(k): v for k, v in cfg.get("anciens_noms", {}).items() if isinstance(v, list)}
    now = datetime.now(timezone.utc)

    prev_db, salt = load_previous()
    old = {m["key"]: m for m in prev_db.get("members", [])}
    manual_rows = prev_db.get("manual") or read_manual_csv()
    manual = index_manual(manual_rows)

    members = read_members()
    servers = Servers(region)
    log(f"{len(members)} membres suivis · région {region} · {servers.count()} serveurs chargés")

    result, issues = [], []
    for n, m in enumerate(members, 1):
        key = f"{norm(m['server'])}:{norm(m['name'])}"
        entry, found = update_member(m, old.get(key, {}), servers, manual, now, guild, aliases.get(norm(m["name"]), ()))
        result.append(entry)
        for t, detail in found:
            issues.append({"name": entry["name"], "type": t, "detail": detail})
        # Journal public : ni pseudo ni valeur, seulement le résultat
        log(f"  {n:>3}. {'ok' if entry['status'] == 'ok' else ISSUE_LABEL.get(entry['status'], entry['status'])}"
            + (f" (+{len(found)} signalement)" if found and entry["status"] == "ok" else ""))

    ok = sum(1 for e in result if e["status"] == "ok")
    removed = sorted(m["name"] for k, m in old.items() if k not in {e["key"] for e in result})
    db = {
        "guild": guild,
        "region": region,
        "updatedAt": now.isoformat(timespec="seconds"),
        "counts": {"total": len(result), "ok": ok},
        "run": {"at": now.isoformat(timespec="seconds"), "ok": ok, "total": len(result), "issues": issues},
        "members": result,
        "manual": manual_rows,
    }
    save(db, salt)
    step_summary(db, removed)
    log(f"Terminé : {ok}/{len(result)} à jour, {len(issues)} signalement(s)")

    # Moins de la moitié des persos trouvés : le site officiel a sans doute changé.
    if result and ok < len(result) * MIN_SUCCESS:
        sys.exit(f"Seulement {ok}/{len(result)} persos mis à jour : le site officiel a peut-être changé.")


if __name__ == "__main__":
    main()
