#!/usr/bin/env python3
"""
Migration unique vers Supabase : reprend la liste des membres (members.csv),
les anciens noms (config.json), l'historique des GS et CP (data/db.enc.json) et
les évaluations (data/evals.enc.json), déchiffrés avec le mot de passe du site.

Lancé une fois par .github/workflows/migration.yml (bouton « Run workflow »).
Peut être relancé sans risque : les lignes déjà présentes sont mises à jour,
rien n'est supprimé.

Variables : SITE_PASSWORD, SUPABASE_SECRET_KEY (secrets GitHub).
Dépendance : « cryptography » (déchiffrement), installée par le workflow.
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

import vault
from supa import Supa

ROOT = Path(__file__).resolve().parent.parent
RANKS = ("Chef", "Officier", "Membre")


def log(*a):
    print(*a, flush=True)


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def read_members():
    """members.csv → persos suivis et en attente (lignes « # pseudo,serveur,… »)."""
    out, seen = [], set()
    with (ROOT / "members.csv").open(encoding="utf-8-sig", newline="") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            off = line.startswith("#")
            parts = [x.strip() for x in re.sub(r"^#+\s*", "", line).split(",")]
            # Une phrase de commentaire n'est pas un perso : un pseudo n'a pas plusieurs mots.
            if len(parts) < 2 or not parts[0] or len(parts[0].split(" ")) > 2 or norm(parts[0]) == "pseudo":
                continue
            name, server = parts[0], parts[1] or "Triniel"
            key = (norm(name), norm(server))
            if key in seen:
                continue
            seen.add(key)
            role = parts[2] if len(parts) > 2 and parts[2] in RANKS else "Membre"
            main = parts[3] if len(parts) > 3 and norm(parts[3]) != norm(name) else ""
            out.append({"pseudo": name, "serveur": server, "statut": role, "main": main, "suivi": not off})
    return out


def decrypt(path, password):
    p = ROOT / path
    if not p.exists():
        return None
    return vault.decrypt(json.loads(p.read_text(encoding="utf-8")), password)[0]


def main():
    password = os.environ.get("SITE_PASSWORD", "")
    if not password:
        sys.exit("Secret SITE_PASSWORD manquant : il sert à déchiffrer l'historique.")
    db = Supa()
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    aliases = {norm(k): v for k, v in cfg.get("anciens_noms", {}).items() if isinstance(v, list)}

    data = decrypt("data/db.enc.json", password) or {}
    evals = decrypt("data/evals.enc.json", password) or {}
    old = {m["key"]: m for m in data.get("members", [])}

    # 1. Membres, avec leurs dernières valeurs connues
    rows = []
    for m in read_members():
        prev = old.get(f"{norm(m['serveur'])}:{norm(m['pseudo'])}", {})
        rows.append({
            **m,
            "anciens_noms": aliases.get(norm(m["pseudo"]), []),
            "classe": prev.get("className"), "niveau": prev.get("level"), "cp": prev.get("cp"),
            "gs": prev.get("itemLevel"), "legion": prev.get("legion"), "image": prev.get("image"),
            "character_id": prev.get("characterId"), "server_id": prev.get("serverId"),
            "region": prev.get("region"), "etat": prev.get("status"), "dernier_ok": prev.get("lastOk"),
        })
    saved = db.upsert("membres", rows, "cle", returning=True)
    ids = {r["cle"]: r["id"] for r in saved}
    log(f"Membres : {len(saved)} ({sum(r['suivi'] for r in rows)} suivis, {sum(not r['suivi'] for r in rows)} en attente)")

    # 2. Historique : un relevé par perso et par jour
    points = []
    for key, m in old.items():
        mid = ids.get(key)
        if not mid:
            continue
        for h in m.get("history", []):
            if h.get("d") and (h.get("il") is not None or h.get("cp") is not None):
                points.append({"membre_id": mid, "jour": h["d"], "gs": h.get("il"), "cp": h.get("cp"), "source": "site"})
    if points:
        db.upsert("releves", points, "membre_id,jour")
    log(f"Relevés : {len(points)}")

    # 3. Dernier passage, pour l'état du suivi
    run = data.get("run")
    if run and not db.select("passages", select="id", declencheur="eq.migration", limit=1):
        db.insert("passages", [{"debut": run["at"], "fin": run["at"], "ok": run.get("ok"), "total": run.get("total"),
                                "signalements": run.get("issues", []), "declencheur": "migration"}])
        log("Dernier passage repris.")

    # 4. Évaluations
    fiches = [{"pseudo_norm": k, "pseudo": ev.get("name") or k, "crit": ev.get("crit") or {},
               "alerte": bool(ev.get("alerte")), "commentaire": ev.get("comment") or "", "maj_par": "migration"}
              for k, ev in (evals.get("by") or {}).items()]
    if fiches:
        db.upsert("evaluations", fiches, "pseudo_norm")
    log(f"Évaluations : {len(fiches)}")

    if data.get("guild"):
        db.upsert("reglages", [{"cle": "guilde", "valeur": data["guild"]}, {"cle": "region", "valeur": data.get("region", "eu")}], "cle")
    log("Migration terminée.")


if __name__ == "__main__":
    main()
