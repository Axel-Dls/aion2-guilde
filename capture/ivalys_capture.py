"""
Ivalys Capture : lit la liste de légion d'Aion 2 et l'enregistre dans un fichier
à importer dans la page Admin du site.

Utilisation :
  1. Lancer IvalysCapture.exe (Aion 2 ouvert, perso connecté).
  2. En jeu, ouvrir la fenêtre de légion (onglet des membres).
  3. Le fichier « legion-AAAA-MM-JJ-HHMM.json » est créé à côté du programme et
     la page Admin s'ouvre : bouton « Importer une capture du jeu ».

Le programme écoute seulement le trafic réseau (comme les compteurs de dégâts),
avec le pilote Npcap (installé avec Wireshark, ou depuis https://npcap.com).
Il ne touche ni au jeu ni à ses fichiers, et n'envoie rien sur Internet.

Pour relire une capture Wireshark : IvalysCapture.exe fichier.pcapng
"""

import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from legion import analyser

ADMIN = "https://axel-dls.github.io/aion2-guilde/admin.html#capture"
MAX_FLUX = 30_000_000   # octets gardés par connexion
ATTENTE = 15 * 60       # secondes avant d'abandonner


def dossier():
    """Dossier du programme (ou du script), où le fichier est enregistré."""
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


class Flux:
    """Reconstitue les connexions TCP (côté serveur → PC) à partir des paquets capturés."""

    def __init__(self):
        self.morceaux = {}   # connexion → {numéro de séquence: données}
        self.tailles = {}
        self.nouveau = set()
        self.verrou = threading.Lock()

    def ajouter(self, pkt):
        from scapy.layers.inet import IP, TCP
        from scapy.layers.inet6 import IPv6
        tcp = pkt.getlayer(TCP)
        ip = pkt.getlayer(IP) or pkt.getlayer(IPv6)
        if tcp is None or ip is None:
            return
        data = bytes(tcp.payload)
        if not data or tcp.sport in (80, 443):  # le web ne nous intéresse pas
            return
        cle = (ip.src, tcp.sport, ip.dst, tcp.dport)
        with self.verrou:
            if self.tailles.get(cle, 0) > MAX_FLUX:
                return
            self.morceaux.setdefault(cle, {})[tcp.seq] = data
            self.tailles[cle] = self.tailles.get(cle, 0) + len(data)
            self.nouveau.add(cle)

    def octets(self, cle):
        out, fin = bytearray(), None
        for seq in sorted(self.morceaux[cle]):
            d = self.morceaux[cle][seq]
            if fin is not None and seq < fin:  # retransmission : on garde la suite
                d = d[fin - seq:]
            out += d
            fin = max(fin or 0, seq + len(self.morceaux[cle][seq]))
        return bytes(out)

    def a_relire(self):
        with self.verrou:
            cles, self.nouveau = list(self.nouveau), set()
            return [self.octets(c) for c in cles]


def enregistrer(resultat):
    nom, annonce, membres = resultat
    maintenant = datetime.now()
    contenu = {
        "type": "ivalys-capture",
        "version": 1,
        "capture_le": maintenant.astimezone().isoformat(timespec="seconds"),
        "legion": nom,
        "annonces": annonce,
        "membres": membres,
    }
    chemin = dossier() / f"legion-{maintenant:%Y-%m-%d-%H%M}.json"
    chemin.write_text(json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")
    return chemin


def resume(resultat, chemin):
    nom, annonce, membres = resultat
    print()
    print(f"  Légion {nom or '?'} : {len(membres)} membres lus" + (f" sur {annonce}" if annonce else ""))
    print(f"  Fichier : {chemin}")
    print()


def depuis_fichier(fichier):
    from scapy.all import PcapReader  # charge aussi les protocoles (Ethernet, IP, TCP…)
    flux = Flux()
    with PcapReader(fichier) as lecteur:
        for pkt in lecteur:
            flux.ajouter(pkt)
    return analyser(flux.a_relire())


def en_direct():
    from scapy.all import AsyncSniffer, conf
    flux = Flux()
    ecoutes = []
    for iface in list(conf.ifaces.values()):
        try:
            s = AsyncSniffer(iface=iface, filter="tcp", prn=flux.ajouter, store=False)
            s.start()
            ecoutes.append(s)
        except Exception:
            pass  # carte réseau inutilisable (Bluetooth, désactivée…)
    if not ecoutes:
        print("  Aucune carte réseau n'a pu être écoutée.")
        print("  Vérifie que Npcap est installé (https://npcap.com), ou relance en tant qu'administrateur.")
        return None
    print(f"  Écoute en cours ({len(ecoutes)} cartes réseau).")
    print("  Ouvre maintenant la fenêtre de légion en jeu (onglet des membres)…")

    meilleur, depuis, debut = None, None, time.time()
    try:
        while time.time() - debut < ATTENTE:
            time.sleep(2)
            r = analyser(flux.a_relire())
            if r and (not meilleur or len(r[2]) > len(meilleur[2])):
                meilleur, depuis = r, time.time()
                print(f"  … {len(r[2])} membres lus" + (f" sur {r[1]}" if r[1] else ""))
            # Liste complète, ou plus rien de nouveau depuis 6 secondes : terminé
            if meilleur and (len(meilleur[2]) >= meilleur[1] > 0 or time.time() - depuis > 6):
                return meilleur
        print("  Rien reçu au bout de 15 minutes : la fenêtre de légion a-t-elle été ouverte ?")
        return meilleur
    finally:
        for s in ecoutes:
            try:
                s.stop()
            except Exception:
                pass


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print()
    print("  Ivalys Capture · liste de légion Aion 2")
    print("  ---------------------------------------")
    fichier = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    try:
        resultat = depuis_fichier(fichier) if fichier else en_direct()
    except Exception as e:
        print(f"  Erreur : {e}")
        if "npcap" in str(e).lower() or "winpcap" in str(e).lower() or "libpcap" in str(e).lower():
            print("  Installe Npcap (https://npcap.com) puis relance.")
        resultat = None
    if resultat:
        chemin = enregistrer(resultat)
        resume(resultat, chemin)
        if "--sans-navigateur" not in sys.argv and not fichier:
            print("  La page Admin s'ouvre : clique sur « Importer une capture du jeu » et choisis ce fichier.")
            webbrowser.open(ADMIN)
    else:
        print("  Aucune liste de légion trouvée.")
    if getattr(sys, "frozen", False) and "--sans-pause" not in sys.argv:
        input("\n  Appuie sur Entrée pour fermer…")
    return 0 if resultat else 1


if __name__ == "__main__":
    sys.exit(main())
