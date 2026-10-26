"""
Lecture de la liste de légion d'Aion 2 dans le trafic réseau du jeu.

Le jeu envoie la liste quand on ouvre la fenêtre de légion. Rien n'est chiffré :
  - les paquets sont précédés de leur longueur (varint ; longueur = contenu + 4) ;
  - certains sont regroupés et compressés en LZ4 : « FF FF <taille u32> <bloc LZ4> » ;
  - la liste des membres est le paquet « 05 8A », le nom de la légion le paquet « 03 8A ».
Si le trafic passe par un relais (ExitLag ou autre), chaque morceau est emballé
dans des champs « type, numéro, longueur » : on en extrait le champ 0x23.

Découpage repris du compteur de dégâts open source A2Tools (GPL-3.0) ; format de
la liste établi à partir d'une capture de la légion Ivalys (octobre 2026).
"""

import re
import struct
from datetime import datetime, timezone

import lz4.block

# Code de classe du jeu (classe × faction × sexe, 4 par classe) → classe, avec les noms
# anglais du site officiel (le site de la guilde les traduit)
CLASSES = ["Gladiator", "Templar", "Ranger", "Assassin", "Spiritmaster", "Sorcerer", "Cleric", "Chanter"]
RANGS = {0: "Chef", 1: "Officier", 2: "Membre"}


def classe(code):
    i = (code - 5) // 4
    return CLASSES[i] if 0 <= i < len(CLASSES) else f"? ({code})"


# ---------------------------------------------------------------- couche relais

RELAIS = re.compile(rb"\x01..\x00\x05\x01\x01", re.S)


def retirer_relais(data):
    """Si le flux est emballé par un relais, renvoie le flux du jeu ; sinon le flux tel quel."""
    m = RELAIS.search(data[:65536])
    if not m:
        return data
    o, out = m.start(), bytearray()
    while o < len(data):
        t = data[o]
        if t == 1 and o + 4 <= len(data):
            o += 4
            continue
        if t in (5, 9, 13) and o + 2 < len(data):
            largeur = {5: 1, 9: 2, 13: 4}[t]
            if o + 2 + largeur > len(data):
                break
            n = int.from_bytes(data[o + 2:o + 2 + largeur], "little")
            if data[o + 1] == 0x23:
                out += data[o + 2 + largeur:o + 2 + largeur + n]
            o += 2 + largeur + n
            continue
        o += 1  # désynchronisé : on avance d'un octet
    return bytes(out)


# ---------------------------------------------------------------- paquets du jeu

def _varint(b, o):
    v = sh = n = 0
    while o + n < len(b):
        x = b[o + n]
        n += 1
        v |= (x & 0x7F) << sh
        if not x & 0x80:
            return v, n
        sh += 7
        if sh >= 32:
            break
    return None, 0


def _tls(b, o):
    if len(b) - o >= 5 and 0x14 <= b[o] <= 0x17 and b[o + 1] == 3 and 1 <= b[o + 2] <= 4:
        n = int.from_bytes(b[o + 3:o + 5], "big")
        if 0 < n <= 16640:
            return 5 + n
    return 0


def paquets(b, interne=False, profondeur=1):
    """Découpe un flux en paquets du jeu, en ouvrant les groupes compressés."""
    o, out = 0, []
    while o < len(b):
        if b[o] == 0:
            o += 1
            continue
        if not interne:
            t = _tls(b, o)
            if t:
                o += t
                continue
        v, n = _varint(b, o)
        total = (v or 0) - 4 + n
        if not v or total < n or total <= 0 or total > 65535 or o + total > len(b):
            if interne:
                break
            o += 1
            continue
        p = b[o + n:o + total]
        if len(p) > 6 and p[0] == 0xFF and p[1] == 0xFF and profondeur < 5:
            taille = int.from_bytes(p[2:6], "little")
            if 0 < taille <= 1_000_000:
                try:
                    out += paquets(lz4.block.decompress(p[6:], uncompressed_size=taille), True, profondeur + 1)
                except Exception:
                    pass
        else:
            out.append(p)
        o += total
    return out


# ---------------------------------------------------------------- liste de légion

def lire_membres(p):
    """Paquet 05 8A → (nombre annoncé, liste des membres)."""
    annonce = struct.unpack_from("<H", p, 4)[0] if len(p) >= 6 else 0
    membres, j = [], 6
    while j < len(p) - 10:
        try:
            code, n = struct.unpack_from("<IB", p, j)
            if not (1 <= code < 64 and 1 <= n <= 40):
                raise ValueError
            pseudo = p[j + 5:j + 5 + n].decode("utf-8")
            if not pseudo.isprintable():
                raise ValueError
            k = j + 5 + n
            niveau, rang = struct.unpack_from("<IB", p, k)
            if not (1 <= niveau <= 60 and rang <= 8):
                raise ValueError
            # Message perso facultatif, puis date de dernière connexion (ms) : on se cale sur la date
            for t in range(k + 5, min(k + 5 + 90, len(p) - 24 + 1)):
                ts, _, gs, cp = struct.unpack_from("<QIIQ", p, t)
                if 1.75e12 < ts < 1.85e12 and 0 < gs < 6000 and 0 < cp < 2_000_000:
                    break
            else:
                raise ValueError
            membres.append({
                "pseudo": pseudo,
                "classe": classe(code),
                "niveau": niveau,
                "statut": RANGS.get(rang, "Membre"),
                "rang": rang,
                "gs": gs,
                "cp": cp,
                "derniere_connexion": datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(timespec="seconds"),
            })
            j = t + 24
        except (ValueError, struct.error, UnicodeDecodeError):
            j += 1
    return annonce, membres


def lire_nom_legion(p):
    """Paquet 03 8A → nom de la légion."""
    try:
        n = p[4]
        nom = p[5:5 + n].decode("utf-8")
        return nom if nom.isprintable() else None
    except (IndexError, UnicodeDecodeError):
        return None


def analyser(flux):
    """Flux reçus du serveur (octets) → (nom de légion, nombre annoncé, membres) ou None."""
    nom, annonce, membres = None, 0, {}
    for data in flux:
        for p in paquets(retirer_relais(data)):
            if p[:2] == b"\x03\x8a":
                nom = lire_nom_legion(p) or nom
            elif p[:2] == b"\x05\x8a":
                a, ms = lire_membres(p)
                if ms:
                    annonce = max(annonce, a)
                    for m in ms:  # un même membre peut arriver deux fois (relais IPv4 + IPv6)
                        membres[m["pseudo"]] = m
    if not membres:
        return None
    return nom, annonce, sorted(membres.values(), key=lambda m: (m["rang"], -m["cp"]))
