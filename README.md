# Ivalys · suivi des CP (Aion 2 global)

Site qui affiche le Combat Power et l'Item Level des membres de la guilde, mis à jour automatiquement une fois par jour.

## Ajouter ou retirer un membre

Modifie [`members.csv`](members.csv) directement sur GitHub (icône crayon), une ligne par perso :

```
Nioky,Tiriel
```

Valide avec « Commit changes » : la mise à jour se lance toute seule et le site est à jour quelques minutes plus tard.

## Comment ça marche

- `scripts/update.py` interroge la page officielle Character Info (aion2.plaync.com) pour chaque membre et écrit `data/db.json`, avec un point d'historique par jour.
- `.github/workflows/update.yml` lance le script tous les jours vers 6 h (heure de Paris), à chaque modification de `members.csv`, ou à la main depuis l'onglet **Actions** → « Mise à jour CP guilde » → **Run workflow**.
- `index.html` est le site (GitHub Pages) : il lit `data/db.json`.

Les adresses utilisées ne sont pas documentées par NCSoft : si le site officiel change, la mise à jour peut échouer (le run apparaît en rouge dans l'onglet Actions et GitHub t'envoie un e-mail).
