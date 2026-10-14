# Ivalys · suivi GS / CP (Aion 2 global)

Site : **https://axel-dls.github.io/aion2-guilde/** · Admin : **https://axel-dls.github.io/aion2-guilde/admin.html**

Classement des membres de la guilde par GS (Item Level) et CP, avec leur progression sur 7 jours et la composition de la guilde. Les données viennent du site officiel d'Aion 2 et se mettent à jour toutes seules.

## Gérer les membres

Le plus simple : la page **Admin** du site (lien en haut du classement). Il faut une clé GitHub personnelle (« fine-grained token ») limitée à ce dépôt, avec les permissions **Contents** et **Actions** en *Read and write*. La page explique comment la créer.

Depuis l'admin, on peut :

- ajouter un perso, changer son statut (Chef, Officier, Membre) ou en faire l'**alt** d'un autre ;
- le mettre **en attente** (il n'est plus suivi mais garde son historique), puis corriger son pseudo ou son serveur et le réactiver ;
- voir l'**état du suivi** : date du dernier relevé, résultat du dernier passage GitHub, persos signalés ;
- relancer une mise à jour à la main ;
- **évaluer** chaque joueur (onglet Évaluations) : 7 critères notés bien / moyen / à surveiller, alerte et commentaire, à côté des signaux automatiques (GS qui stagne, sous la moyenne…). Le bouton « Importer le tableau Excel » reprend l'onglet « Suivi Global membres » ; le fichier est lu dans le navigateur, il n'est envoyé nulle part.

À défaut, on peut modifier [`members.csv`](members.csv) directement sur GitHub : une ligne `pseudo,serveur,statut,main` par perso (`main` vide pour un perso principal, sinon le pseudo de son main), et `# ` devant la ligne pour un perso en attente.

## Fonctionnement

| Fichier | Rôle |
|---|---|
| `members.csv` | Liste des persos suivis (et en attente) |
| `config.json` | Nom de la guilde, région (`eu`) et anciens noms des persos renommés |
| `scripts/update.py` | Interroge le site officiel pour chaque perso et écrit les données |
| `scripts/vault.py` | Chiffrement des données avec le mot de passe du site |
| `data/db.enc.json` | Données affichées, **chiffrées** : valeurs actuelles, historique (un point par jour), relevés manuels, signalements |
| `data/evals.enc.json` | Évaluations des gérants, **chiffrées** par la page admin (le script les rechiffre seulement si le mot de passe change) |
| `.github/workflows/update.yml` | Lance le script 2 fois par jour, après chaque modification de la liste, ou à la demande |
| `index.html`, `admin.html`, `assets/` | Le site (GitHub Pages) |

**Horaires** : deux passages par jour, prévus vers 6 h et 17 h (heure de Paris). GitHub retarde souvent ces passages de quelques heures ; le second sert de filet de sécurité.

## Accès protégé

Le dépôt et le site sont publics (c'est ce qui rend l'hébergement gratuit), donc les données sont **chiffrées** (AES-256-GCM) avec le mot de passe du site. Sans lui, `data/db.enc.json` est illisible ; le site affiche un écran de mot de passe, retenu ensuite sur l'appareil (bouton « Verrouiller » pour l'oublier).

- Le mot de passe est le secret GitHub **`SITE_PASSWORD`** (*Settings → Secrets and variables → Actions*). Il n'est écrit nulle part dans le dépôt.
- **Changer de mot de passe** : mettre le nouveau dans `SITE_PASSWORD` et l'ancien dans `SITE_PASSWORD_PREVIOUS`, lancer une mise à jour, puis supprimer `SITE_PASSWORD_PREVIOUS`. Tout le monde devra saisir le nouveau.
- Les journaux GitHub (publics eux aussi) n'affichent que des comptes, sans pseudo ni valeur.
- Restent visibles dans le dépôt : la liste des pseudos suivis et leur statut (`members.csv`), et le code.

## Surveillance

- Chaque passage affiche un résumé dans l'onglet **Actions** de GitHub (nombre de persos lus et de signalements) ; le détail est dans la page Admin.
- Signalements automatiques : perso **introuvable** (pseudo changé ?), **serveur inconnu**, **hors légion** (a changé de guilde), **GS en baisse** de plus de 30 points.
- Si moins de la moitié des persos sont lus, le passage échoue et GitHub envoie un e-mail : le site officiel a sans doute changé.
- Si les données ont plus de 36 h, le classement affiche un bandeau d'avertissement.

Les adresses du site officiel utilisées (page « Character Info ») ne sont pas documentées par NCSoft et peuvent changer sans prévenir.
