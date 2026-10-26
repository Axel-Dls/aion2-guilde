# Ivalys · suivi GS / CP (Aion 2 global)

Site : **https://axel-dls.github.io/aion2-guilde/** · Admin : **https://axel-dls.github.io/aion2-guilde/admin.html**

Classement des membres de la guilde par GS (Item Level) et CP, avec leur progression sur 7 jours, la composition de la guilde et les évaluations des gérants. Les données viennent du site officiel d'Aion 2, se mettent à jour toutes seules et sont rangées dans une base **Supabase**.

## Accès

On se connecte avec son compte **Discord**. Seuls les comptes autorisés voient quelque chose ; la base le vérifie elle-même, même si quelqu'un a la clé publique du site.

| Rôle | Peut |
|---|---|
| Lecteur | voir le classement |
| Gérant | voir le classement, gérer les membres, noter les évaluations |
| Admin | tout, plus accepter ou retirer des accès (onglet **Accès** de l'admin) |

Quelqu'un qui se connecte sans être autorisé voit « Accès en attente » ; sa demande apparaît dans l'onglet Accès de l'admin.

**Premier admin** : se connecter une fois sur le site, ouvrir « Tu es l'administrateur du site ? » sur l'écran d'attente, et coller la ligne SQL affichée dans Supabase → SQL Editor.

## Gérer les membres

Depuis la page **Admin** :

- ajouter un perso, changer son statut (Chef, Officier, Membre) ou en faire l'**alt** d'un autre ;
- le mettre **en attente** (il n'est plus suivi mais garde son historique), corriger son pseudo ou son serveur, puis le réactiver. Un pseudo corrigé garde son historique, et l'ancien nom est retenu ;
- voir l'**état du suivi** : dernier relevé, prochain relevé, persos signalés ;
- **relancer** un relevé ;
- **évaluer** chaque joueur (onglet Évaluations) : 7 critères notés bien / moyen / à surveiller, alerte et commentaire. Le bouton « Importer le tableau Excel » reprend l'onglet « Suivi Global membres » ; le fichier est lu dans le navigateur, il n'est envoyé nulle part.

## Fonctionnement

| Fichier | Rôle |
|---|---|
| `supabase/schema.sql` | Tables et règles d'accès de la base (à coller dans Supabase → SQL Editor) |
| `scripts/update.py` | Relevé : interroge le site officiel pour chaque perso suivi et enregistre GS, CP et signalements |
| `scripts/supa.py` | Accès à la base depuis les scripts (clé secrète) |
| `scripts/migrate.py` | Reprise unique des anciennes données chiffrées du dépôt |
| `.github/workflows/update.yml` | Lance le relevé quand il le faut (voir ci-dessous) |
| `config.json` | Nom de la guilde, adresse et clé publique du projet Supabase |
| `index.html`, `admin.html`, `assets/` | Le site (GitHub Pages) |

**Relevés** : toutes les 30 minutes, GitHub vérifie dans la base s'il y a quelque chose à faire. Un relevé complet part si un gérant l'a demandé (bouton « Relancer », ajout ou correction d'un perso) ou si le dernier date de plus de 11 heures. GitHub retarde parfois ces passages : compter jusqu'à une heure. Le bouton « Run workflow » de l'onglet Actions lance un relevé immédiat.

**Secret GitHub** (*Settings → Secrets and variables → Actions*) : `SUPABASE_SECRET_KEY`, la clé secrète du projet (Supabase → Settings → API Keys → Secret keys). Elle donne tous les droits sur la base : elle ne doit jamais être écrite dans le dépôt ni dans le site.

## Surveillance

- Chaque passage affiche un résumé dans l'onglet **Actions** de GitHub (nombre de persos lus et de signalements, sans pseudo ni valeur : ces pages sont publiques) ; le détail est dans la page Admin.
- Signalements automatiques : perso **introuvable** (pseudo changé ?), **serveur inconnu**, **hors légion** (a changé de guilde), **GS en baisse** de plus de 30 points.
- Si moins de la moitié des persos sont lus, le passage échoue et GitHub envoie un e-mail : le site officiel a sans doute changé.
- Si les données ont plus de 36 h, le classement affiche un bandeau d'avertissement.

Les adresses du site officiel utilisées (page « Character Info ») ne sont pas documentées par NCSoft et peuvent changer sans prévenir.
