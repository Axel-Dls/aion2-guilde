"""
Test de l'outil de capture sur une fausse capture (pseudos inventés), au format
réel du jeu : paquets groupés et compressés en LZ4, avec ou sans relais.

  python capture/test_capture.py                       teste le code Python
  python capture/test_capture.py dist/IvalysCapture.exe teste le programme Windows
"""

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import lz4.block
from scapy.layers.inet import IP, TCP
from scapy.layers.l2 import Ether
from scapy.utils import wrpcap

ICI = Path(__file__).resolve().parent
MEMBRES = [  # (code de classe, pseudo, rang, message, gs, cp)
    (20, "Testchef", 0, "Je suis le chef", 2833, 178688),
    (7, "Officiéra", 1, "", 2334, 118859),
    (36, "Aédia", 2, "Une phrase ! ( •̀ᴗ•́ )つ", 2807, 164640),
    (27, "Sorcix", 2, "", 2827, 192942),
    (16, "长弓手", 2, "", 2960, 199034),
    (32, "Soigneuse", 2, "x" * 30, 2100, 95976),
]
TS = 1792000000000  # ms, octobre 2026


def varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def trame(contenu):
    return varint(len(contenu) + 4) + contenu


def paquet_legion():
    p = bytearray(b"\x05\x8a\x00\x00" + struct.pack("<H", len(MEMBRES)) + b"\x0d\x8b\x07\x00\x00\x00\x00\x00")
    for i, (code, nom, rang, msg, gs, cp) in enumerate(MEMBRES):
        n = nom.encode()
        p += b"\xff\x08" + struct.pack("<IB", code, len(n)) + n + struct.pack("<IB", 45, rang)
        if msg:
            m = msg.encode()
            p += bytes([len(m)]) + m
        p += struct.pack("<QIIQ", TS + i * 3600_000, 901, gs, cp) + b"\x00" + struct.pack("<QI", 463991, 1000 + i)
    return bytes(p)


def flux_jeu():
    nom = b"Testlegion"
    info = b"\x03\x8a\x00\x00" + bytes([len(nom)]) + nom + b"\x03Doc" + b"\x00" * 20
    bruit = [b"\x00\x36" + bytes(range(8)), b"\x1d\x37" + b"\x01" * 30]
    interne = b"".join(trame(x) for x in (*bruit, info, paquet_legion(), *bruit))
    groupe = b"\xff\xff" + struct.pack("<I", len(interne)) + lz4.block.compress(interne, store_size=False)
    return b"".join(trame(x) for x in bruit) + trame(groupe) + b"".join(trame(x) for x in bruit)


def avec_relais(data):
    out, seq = bytearray(), 0
    for i in range(0, len(data), 700):
        morceau = data[i:i + 700]
        champs = (b"\x05\x01\x01\x09" + b"\x05\x02\x01\x01" + b"\x05\x03\x10" + bytes(16)
                  + b"\x05\x22\x02" + struct.pack("<H", seq) + b"\x09\x23" + struct.pack("<H", len(morceau)) + morceau)
        out += b"\x01" + struct.pack("<H", len(champs) + 4) + b"\x00" + champs + b"\x05\x25\x01\x01"
        seq += 1
    return bytes(out)


def pcap(chemin, data, port=50590):
    pkts, seq = [], 1000
    for i in range(0, len(data), 300):
        morceau = data[i:i + 300]
        pkts.append(Ether() / IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=port, dport=52364, seq=seq, flags="PA") / morceau)
        seq += len(morceau)
    pkts.insert(1, pkts[1].copy())  # une retransmission, comme sur un vrai réseau
    wrpcap(str(chemin), pkts)


def lancer(cmd, fichier, dossier):
    subprocess.run([*cmd, str(fichier), "--sans-pause"], cwd=dossier, check=True, timeout=120)
    sortie = sorted(Path(cmd[-1]).resolve().parent.glob("legion-*.json"))[-1]
    data = json.loads(sortie.read_text(encoding="utf-8"))
    sortie.unlink()
    return data


def main():
    cmd = [sys.argv[1]] if len(sys.argv) > 1 else [sys.executable, str(ICI / "ivalys_capture.py")]
    erreurs = 0
    with tempfile.TemporaryDirectory() as tmp:
        for nom, data in (("direct", flux_jeu()), ("relais", avec_relais(flux_jeu()))):
            f = Path(tmp) / f"{nom}.pcap"
            pcap(f, data)
            r = lancer(cmd, f, tmp)
            attendu = [m[1] for m in MEMBRES]
            lus = {m["pseudo"]: m for m in r["membres"]}
            ok = (r["legion"] == "Testlegion" and r["annonces"] == len(MEMBRES) and sorted(lus) == sorted(attendu)
                  and lus["Testchef"]["statut"] == "Chef" and lus["Officiéra"]["statut"] == "Officier"
                  and lus["Aédia"]["classe"] == "Chanter" and lus["Aédia"]["gs"] == 2807 and lus["Aédia"]["cp"] == 164640
                  and lus["Sorcix"]["classe"] == "Sorcerer" and lus["长弓手"]["classe"] == "Ranger"
                  and lus["Testchef"]["derniere_connexion"].startswith("2026-10-"))
            print(("OK  " if ok else "ÉCHEC"), nom, len(lus), "membres")
            if not ok:
                print(json.dumps(r, ensure_ascii=False, indent=1)[:1500])
            erreurs += not ok
    sys.exit(erreurs)


if __name__ == "__main__":
    main()
