#!/usr/bin/env python3
"""
Met à jour data/db.json avec le Combat Power et l'Item Level de chaque membre
listé dans members.csv, en interrogeant le site officiel d'Aion 2 (global).

Lancé une fois par jour par GitHub Actions (.github/workflows/update.yml).
Aucune dépendance : bibliothèque standard Python 3.9+.

Les adresses utilisées sont celles de la page officielle « Character Info »
(aion2.plaync.com). Elles ne sont pas documentées par NCSoft et peuvent changer.
"""

import csv
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMBERS = ROOT / "members.csv"
CONFIG = ROOT / "config.json"
DB = ROOT / "data" / "db.json"
MANUAL = ROOT / "data" / "historique-manuel.csv"

SITE = "https://aion2.plaync.com"
SEARCH = "https://api-search.plaync.com/aion2global/search/v2/character"
LANG = "en-US"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (aion2-guilde tracker)",
    "Accept": "application/json",
    "Referer": f"{SITE}/en-us/characters/index",
    "Origin": SITE,
}
PAUSE = 0.6          # secondes entre deux requêtes, pour rester discret
MAX_HISTORY = 400    # jours d'historique conservés par membre


def log(*a):
    print(*a, flush=True)


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


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def read_members():
    """members.csv : une ligne par perso, « pseudo,serveur[,statut] ». Les lignes # sont ignorées."""
    out, seen = [], set()
    with MEMBERS.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip() or row[0].strip().startswith("#"):
                continue
            name = row[0].strip()
            server = row[1].strip() if len(row) > 1 else ""
            if norm(name) in ("pseudo", "name") and norm(server) in ("serveur", "server"):
                continue  # ligne d'en-tête
            k = (norm(name), norm(server))
            if k not in seen:
                seen.add(k)
                role = row[2].strip() if len(row) > 2 else ""
                out.append({"name": name, "server": server, "role": role or "Membre"})
    return out


REGIONS = ["eu", "naw", "nae", "la", "as"]


def read_manual_history():
    """data/historique-manuel.csv : relevés faits à la main (pseudo,date,gs,cp), fusionnés dans l'historique."""
    def to_int(v):
        v = (v or "").strip().replace(" ", "").replace(",", ".")
        if not v:
            return None
        mult = 1000 if v.lower().endswith("k") else 1
        try:
            return int(round(float(v.rstrip("kK")) * mult))
        except ValueError:
            return None

    out = {}
    if not MANUAL.exists():
        return out
    with MANUAL.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 3 or row[0].strip().startswith("#") or norm(row[0]) == "pseudo":
                continue
            gs = to_int(row[2])
            cp = to_int(row[3]) if len(row) > 3 else None
            if gs is None and cp is None:
                continue
            out.setdefault(norm(row[0]), []).append({"d": row[1].strip(), "cp": cp, "il": gs})
    return out


def merge_manual(history, manual):
    """Ajoute les relevés manuels ; à une date déjà connue, ne complète que les valeurs manquantes."""
    by_date = {h.get("d"): dict(h) for h in history}
    for p in manual:
        cur = by_date.get(p["d"])
        if cur is None:
            by_date[p["d"]] = dict(p)
        else:
            for k in ("cp", "il"):
                if cur.get(k) is None and p.get(k) is not None:
                    cur[k] = p[k]
    return sorted(by_date.values(), key=lambda h: h.get("d", ""))


def load_servers(preferred):
    """Nom de serveur → serveur (avec sa région). La région de config.json est
    prioritaire, puis les autres : un serveur absent de l'Europe est trouvé quand même."""
    by_name = {}
    for region in [preferred] + [r for r in REGIONS if r != preferred]:
        try:
            data = get_json(f"{SITE}/en-us/api/gameinfo/servers", {"lang": LANG, "region": region})
        except RuntimeError as e:
            log(f"  liste des serveurs {region} indisponible : {e}")
            continue
        for s in data.get("serverList", []):
            s = {**s, "region": region}
            for k in (norm(s["serverName"]), norm(s["serverShortName"])):
                by_name.setdefault(k, s)
    if not by_name:
        raise RuntimeError("impossible de charger la liste des serveurs")
    return by_name


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


def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    region = cfg.get("region", "eu")
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    old = {}
    if DB.exists():
        prev = json.loads(DB.read_text(encoding="utf-8"))
        old = {m["key"]: m for m in prev.get("members", [])}

    manual = read_manual_history()
    members = read_members()
    log(f"{len(members)} membres dans members.csv, région {region}")

    servers = load_servers(region)
    log(f"{len({(s['region'], s['serverId']) for s in servers.values()})} serveurs chargés")

    result, ok_count = [], 0
    for m in members:
        srv = servers.get(norm(m["server"]))
        key = f"{norm(m['server'])}:{norm(m['name'])}"
        prev = old.get(key, {})
        entry = {
            "key": key,
            "name": prev.get("name", m["name"]),
            "server": srv["serverName"] if srv else m["server"],
            "role": m["role"],
            "history": prev.get("history", []),
        }
        for k in ("serverId", "characterId", "race", "className", "level", "cp", "itemLevel", "legion", "title", "image", "lastOk"):
            if k in prev:
                entry[k] = prev[k]

        if srv:
            entry["serverId"] = srv["serverId"]
            entry["region"] = srv["region"]
        if not srv:
            entry["status"] = "unknown_server"
            close = difflib.get_close_matches(norm(m["server"]), list(servers), n=1)
            hint = f" (tu voulais dire « {servers[close[0]]['serverName']} » ?)" if close else ""
            log(f"  ✗ {m['name']} : serveur « {m['server']} » inconnu{hint}")
            result.append(entry)
            continue

        try:
            char = find_character(m["name"], srv["serverId"], srv["region"])
            if not char:
                entry["status"] = "not_found"
                log(f"  ✗ {m['name']} ({srv['serverName']}) : introuvable")
                result.append(entry)
                continue

            info = get_info(char["characterId"], srv["serverId"], srv["region"])
            p = info["profile"]
            il = item_level(info)
            entry.update({
                "name": p.get("characterName") or m["name"],
                "server": p.get("serverName") or srv["serverName"],
                "race": p.get("raceName"),
                "className": p.get("className"),
                "level": p.get("characterLevel"),
                "cp": p.get("combatPower"),
                "itemLevel": il,
                "legion": p.get("regionName") or "",
                "title": p.get("titleName") or "",
                "image": p.get("profileImage") or "",
                "region": srv["region"],
                "serverId": srv["serverId"],
                "characterId": char["characterId"],
                "status": "ok",
                "lastOk": now.isoformat(timespec="seconds"),
            })
            hist = [h for h in entry["history"] if h.get("d") != today]
            hist.append({"d": today, "cp": entry["cp"], "il": il})
            entry["history"] = merge_manual(hist, manual.get(norm(entry["name"]), []))[-MAX_HISTORY:]
            ok_count += 1
            log(f"  ✓ {entry['name']} ({entry['server']}) : CP {entry['cp']}, IL {il}")
        except Exception as e:  # on garde les anciennes valeurs
            entry["status"] = "error"
            log(f"  ! {m['name']} ({m['server']}) : {e}")
        result.append(entry)

    db = {
        "guild": cfg.get("guild", ""),
        "region": region,
        "updatedAt": now.isoformat(timespec="seconds"),
        "counts": {"total": len(result), "ok": ok_count},
        "members": result,
    }
    DB.parent.mkdir(parents=True, exist_ok=True)
    DB.write_text(json.dumps(db, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"Terminé : {ok_count}/{len(result)} mis à jour → {DB.relative_to(ROOT)}")

    # Échec global (API bloquée ou modifiée) : on fait échouer le run pour être prévenu.
    if members and ok_count == 0:
        sys.exit("Aucun membre n'a pu être mis à jour.")


if __name__ == "__main__":
    main()
