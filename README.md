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

**Premier admin** : tant qu'il n'y a aucun admin, l'écran d'attente propose « Tu es l'administrateur du site ? » avec la ligne SQL à coller dans Supabase → SQL Editor.

**Sécurité** : seuls l'admin et les gérants peuvent modifier la liste ; les GS, CP et classes ne sont écrits que par le relevé automatique, et l'auteur d'une évaluation ou d'une demande est enregistré par la base elle-même. Le site refuse les bibliothèques modifiées (contrôle d'intégrité) et ne peut envoyer de données qu'à la base Supabase.

## Capture du jeu (mise à jour quotidienne)

La source normale des GS et CP est la **liste de légion du jeu**, lue par l'outil **IvalysCapture** (Windows) :

1. Installer [Npcap](https://npcap.com) une fois (il est déjà là si Wireshark est installé).
2. Télécharger [IvalysCapture.exe](https://github.com/Axel-Dls/aion2-guilde/releases/download/capture/IvalysCapture.exe) et le lancer, Aion 2 ouvert et perso connecté.
3. En jeu, ouvrir la fenêtre de légion (onglet des membres) : l'outil crée un fichier `legion-….json` à côté de lui et ouvre la page Admin.
4. Admin → **Importer une capture du jeu** : l'aperçu propose les arrivées (avec « Alt de… » deviné pour les rerolls), les départs et les changements de grade ; on décoche ce qu'on ne veut pas, puis « Appliquer ».

L'outil écoute seulement le trafic réseau, comme les compteurs de dégâts : il ne touche ni au jeu ni à ses fichiers, et n'envoie rien sur Internet. Le fichier est importé avec la connexion Discord du gérant ; aucune clé n'est stockée sur le PC. Le code est dans `capture/`, le programme est fabriqué et testé par GitHub (`.github/workflows/capture.yml`).

Tant qu'une capture a été importée dans les 48 dernières heures, le site officiel d'Aion n'est plus interrogé automatiquement ; il reste en secours, et le bouton « Relancer » de l'admin le force.

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
| `capture/` | Outil IvalysCapture : lecture de la liste de légion dans le trafic du jeu |
| `scripts/update.py` | Relevé de secours : interroge le site officiel pour chaque perso suivi |
| `scripts/supa.py` | Accès à la base depuis les scripts (clé secrète) |
| `.github/workflows/update.yml` | Lance le relevé quand il le faut (voir ci-dessous) |
| `config.json` | Nom de la guilde, adresse et clé publique du projet Supabase |
| `index.html`, `admin.html`, `assets/` | Le site (GitHub Pages) |

**Relevés du site officiel** : toutes les 30 minutes, GitHub vérifie dans la base s'il y a quelque chose à faire. Un relevé part si un gérant l'a demandé (bouton « Relancer », ajout ou correction d'un perso à la main) ou si aucune capture n'a été importée depuis 48 h et que le dernier relevé date de plus de 11 heures. GitHub retarde parfois ces passages : compter jusqu'à une heure. Le bouton « Run workflow » de l'onglet Actions lance un relevé immédiat.

**Secret GitHub** (*Settings → Secrets and variables → Actions*) : `SUPABASE_SECRET_KEY`, la clé secrète du projet (Supabase → Settings → API Keys → Secret keys). Elle donne tous les droits sur la base : elle ne doit jamais être écrite dans le dépôt ni dans le site.

## Surveillance

- Chaque passage affiche un résumé dans l'onglet **Actions** de GitHub (nombre de persos lus et de signalements, sans pseudo ni valeur : ces pages sont publiques) ; le détail est dans la page Admin.
- Signalements automatiques : perso **introuvable** (pseudo changé ?), **serveur inconnu**, **hors légion** (a changé de guilde), **GS en baisse** de plus de 30 points.
- Si moins de la moitié des persos sont lus, le passage échoue et GitHub envoie un e-mail : le site officiel a sans doute changé.
- Si les données ont plus de 36 h, le classement affiche un bandeau d'avertissement.

Les adresses du site officiel utilisées (page « Character Info ») ne sont pas documentées par NCSoft et peuvent changer sans prévenir.
