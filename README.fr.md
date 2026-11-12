# Site Audit

🇫🇷 **Français** · 🇬🇧 [English](README.md)

**Un seul skill qui audite une page ou un site entier, te dit ce qui marche et ce qui ne va pas, te remet un rapport noté avec une preuve pour chaque ligne, puis applique le plan de correction avec ton GO.**

Technique, SEO, rapidité, UX, accessibilité, conversion (CRO), copywriting, sécurité, tracking, visibilité IA. Il demande si tu veux auditer une page ou tout le site, mesure avec de vrais outils, et refuse d'écrire un constat qu'il ne peut pas prouver.

> Un skill ouvert, créé par **[Kavyro.com](https://kavyro.com)**, la communauté pour apprendre à travailler avec des agents IA.

Exemples (sur des sites fictifs) : [audit complet, externe + interne](examples/community-site/) · [l'agent applique un plan](examples/fix-session/)

## Pourquoi celui-ci

La plupart des prompts d'audit te donnent une longue liste de conseils génériques, puis te laissent seul. Ce skill repose sur cinq règles :

- **Mesurer d'abord, juger ensuite.** Des scripts collectent les faits (HTML, en-têtes, Lighthouse, vrai crawl, écrans rendus). Le modèle n'interprète que des données mesurées.
- **Preuve ou refus.** Chaque constat porte une valeur et un fichier source, une gravité, un effort, un impact et un niveau de confiance (`measured`, `deduced`, `hypothesis`). Un script de validation rejette le rapport si un constat n'a pas de preuve.
- **Ce qui marche fait partie de l'audit.** Chaque domaine audité liste au moins un point fort vérifié. Pas de rapport fait uniquement de reproches.
- **Un rapport et un plan d'action, toujours la même forme.** Le rapport : verdict en une phrase, scores, 5 priorités, détail par domaine, ce qui n'a pas été mesuré, méthode. Le plan : gains rapides cette semaine, chantiers du mois, le reste ensuite, numérotés par priorité, chacun avec un responsable, des étapes, un moyen de vérifier, le risque, le retour arrière et ce dont l'agent a besoin pour l'appliquer. Les scores sont calculés par un script : les mêmes constats donnent toujours le même score.
- **L'agent corrige, mais jamais sans toi.** Il applique le plan par ordre de priorité, **une action à la fois, avec ton GO**, et **seulement s'il a tout ce qu'il lui faut**. Sinon il te demande le complément, en une seule fois, avant d'agir.

## Ce qu'il audite

| Domaine | Regarde |
|---|---|
| Technique | codes HTTP, redirections, hôte canonique, robots.txt, sitemaps, noindex, soft 404, rendu JavaScript |
| SEO | title, meta description, titres, doublons, liens internes, images, données structurées, balises de partage |
| Rapidité | Lighthouse x3 (médiane), **données Google fraîches (PageSpeed Insights) et données de vrais visiteurs (CrUX) avec leur date et leur périmètre**, plusieurs pages d'un coup (Unlighthouse), vue DevTools du réseau, scripts et tiers coupables, images |
| UX et mobile | vrais écrans mobile au scroll, bandeaux qui masquent la page, cibles tactiles, formulaires |
| Accessibilité | contraste, labels, alt, structure (contrôles automatiques uniquement) |
| Conversion | promesse, appel à l'action, preuve, clarté de l'offre, objections, friction |
| Copywriting | accroche, clarté, focus lecteur, précision, ton, promesses, **incohérences** (même prestation à deux prix, délais ou durées qui se contredisent, téléphones ou adresses multiples, nom de marque écrit de plusieurs façons, année de création qui ne colle pas) |
| Sécurité | en-têtes HTTP, contenu mixte, scripts tiers (passif, aucune intrusion) ; **avec un accès en lecture au back end** : versions, plugins périmés, journaux d'erreurs, fichiers oubliés, permissions, sauvegardes |
| Tracking et consentement | traceurs présents, outil de consentement, **ce qui se charge avant tout choix, puis après un clic sur « Tout refuser »** (vrai navigateur, rien n'est accepté) |
| Visibilité IA | règles pour les robots IA, lisibilité sans JavaScript, balisage d'entité, `llms.txt` |

## Comment ça marche

| Étape | Ce qui se passe |
|---|---|
| 1. Questions | Une page ou tout le site ? Quel objectif pour le visiteur ? Mobile ou desktop ? **Vue extérieure seulement, ou extérieure + intérieure (accès en lecture au back end) ?** Veux-tu que je corrige ensuite, et à quoi ai-je accès ? |
| 2. Mesure | `facts.py`, `lh_median.py` (Lighthouse x3 en série, médiane), `psi.py` (Google : mesure fraîche + vrais visiteurs, avec dates), `devtools.py` (réseau, cookies, console, avant et après consentement), `crawl.py` (site entier), `consistency.py` (incohérences), `lh_site.py` (plusieurs pages), `render.py` (écrans, texte et boutons après JavaScript), `access_check.py` (preuve qu'un accès marche) |
| 3. Jugement | Une référence par domaine : quoi vérifier, seuils, pièges |
| 4. Constats | `findings.json` : preuve obligatoire pour chaque ligne, plus qui peut appliquer la correction et ce qu'il lui faut |
| 5. Rapport et plan | `build_report.py` valide, note, classe et écrit `report.md` et `action-plan.md` |
| 6. Correction (sur demande) | `fix_tracker.py` fait respecter l'ordre de priorité, le GO, et l'absence de tout élément manquant |

| Script | Rôle |
|---|---|
| `doctor.py` | un contrôle en lecture seule avant le premier audit : ce que cette machine sait exécuter (Python, Chrome, Lighthouse, Unlighthouse, une clé Google par le nom de la variable), ce que coûte chaque élément absent et comment l'installer |
| `facts.py` | head, titres, images, liens, formulaires, en-têtes, traqueurs, robots, sitemaps, redirections, faux 404 |
| `lh_median.py` | Lighthouse en série, médiane, écart, coupables (machine au repos seulement : une machine occupée fausse la mesure) |
| `psi.py` | la mesure fraîche de Google plus les données de vrais visiteurs (CrUX), avec leur portée (cette page ou tout le site), leur période de 28 jours, leur âge et leur tendance ; demande une clé d'API gratuite |
| `devtools.py` | ce que montrent les DevTools du navigateur à la première visite : réseau par catégorie, cookies, console, ce qui part avant tout consentement, ce qui part encore après « Tout refuser » |
| `lh_site.py` | Lighthouse sur plusieurs pages via [Unlighthouse](https://github.com/harlan-zw/unlighthouse), avec le ralentissement CPU mobile rétabli et contrôlé |
| `crawl.py` | parcours poli (robots.txt respecté), doublons, liens cassés, chaînes de redirections, pages orphelines, trous du sitemap |
| `consistency.py` | contradictions candidates avec les passages exacts : le même service à deux prix, des délais différents, plusieurs téléphones ou adresses, une marque écrite de plusieurs façons, une année de fondation qui ne tient pas |
| `access_check.py` | preuve en lecture seule qu'un accès ssh, WordPress, FTP ou dossier fonctionne, et ce qu'il permet |
| `redact.py` | masque secrets, adresses e-mail, adresses IP, numéros de téléphone et adresses postales dans la sortie d'une commande avant qu'elle soit gardée comme preuve |
| `render.py` | vrais écrans à plusieurs positions de défilement, texte et boutons après JavaScript, bandeaux fixes et part de l'écran qu'ils couvrent |
| `botwall.py` | utilisé par `facts.py`, `crawl.py` et `render.py` : reconnaît une page de protection anti-bot (défi, blocage, vérification) pour qu'elle ne soit jamais auditée comme si c'était le site. Il n'essaie jamais de contourner la protection |
| `build_report.py` | refuse les constats sans preuve, calcule les notes, classe les priorités, écrit `report.md` et `action-plan.md` |
| `fix_tracker.py` | l'arbitre du mode correction : ordre de priorité, un GO par action, rien ne démarre s'il manque quelque chose, aucun secret stocké |

Tout est en bibliothèque standard Python. Rien à installer, sauf la CLI Lighthouse et un Chrome.

Tout est en bibliothèque standard Python. Rien à installer à part la CLI Lighthouse et un Chrome.

## Installation

Prérequis : Python 3.9+, Node.js, Chrome ou Chromium, et la CLI Lighthouse :

```
npm install -g lighthouse
```

### Dans Hermes Agent

```
hermes skills install Kavyrocom/site-audit/skills/site-audit --category marketing --yes --force
```

**Pourquoi `--force`.** Hermes analyse tout skill qui ne vient pas de son propre catalogue. Sans `--force`, l'installation s'arrête sur un verdict `CAUTION` avec 18 constats, dont 4 classés HIGH. C'est normal pour un outil qui lance Chrome et Lighthouse, peut appeler `ssh` si tu lui donnes un accès au back end, et transmet son environnement aux outils qu'il démarre. Les 4 constats HIGH sont des copies de l'environnement données à Lighthouse, Unlighthouse ou `git` (`lh_median.py`, `lh_site.py`, `safenet.py`) et un contrôle sur le nom d'une variable (`fix_tracker.py`) ; aucun n'envoie quoi que ce soit sur le réseau. Ne le crois pas sur parole : lance d'abord la commande **sans** `--force` pour lire la liste complète, puis ouvre les scripts dans `skills/site-audit/scripts/`.

Si GitHub répond « rate limit », connecte-toi avec `gh auth login` ou renseigne `GITHUB_TOKEN` : sans identification, la limite est de 60 requêtes par heure.

Vérifie qu'il est installé et actif :

```
hermes skills list | grep site-audit
```

Si une session Hermes est déjà ouverte, tape `/reload-skills` pour qu'elle le voie. Le skill est installé dans `~/.hermes/skills/marketing/site-audit/`. Pour le mettre à jour plus tard : `hermes skills update`.

### Dans un autre agent

**Avec la CLI skills**

```
npx skills add Kavyrocom/site-audit
```

**À la main** (tout agent qui lit les Agent Skills, un dossier avec un `SKILL.md`) : copie `skills/site-audit/` dans son dossier de skills.

```
Claude Code   ~/.claude/skills/site-audit/            (ou .claude/skills/ dans un projet)
OpenCode      ~/.config/opencode/skills/site-audit/   (il lit aussi .claude/skills/ et .agents/skills/)
Autres        .agents/skills/site-audit/              (la convention partagée)
```

Le skill suit le [format ouvert Agent Skills](https://agentskills.io/specification) (vérifié avec `skills-ref validate`) : `SKILL.md` ne nomme aucun outil d'un agent, et les scripts sont du Python simple que l'agent lance depuis un shell. Il a été chargé, avec son contrôle préalable exécuté, depuis un projet vide dans Claude Code et dans OpenCode, et installé dans Hermes Agent.

## Utilisation

### 1. Lancer un audit

Dans une conversation Hermes, demande simplement :

```
Audite https://example.com avec le skill site-audit.
```

Ou depuis le terminal, en chargeant le skill d'emblée :

```
hermes chat -s site-audit -q "Audite https://example.com"
```

L'agent pose ses questions en un message : **cette page seulement ou tout le site** (et un plafond de pages), **ce que le visiteur doit faire**, mobile ou desktop, **vue extérieure seulement ou extérieure + intérieure**, **si tu veux qu'il corrige ensuite** et ce qu'il peut atteindre (WordPress, fichiers du site, CDN, gestionnaire de balises, dépôt de code). Il travaille ensuite seul et termine par le verdict, le score, les 3 priorités et le chemin des fichiers.

### Audit extérieur ou intérieur

- **Extérieur** (par défaut) : ce que voit un visiteur et Google. Aucun accès nécessaire.
- **Extérieur + intérieur** : si tu donnes un accès en **lecture** au back end (`ssh`, administration WordPress par mot de passe d'application, FTPS/SFTP, dossier du site sur la machine), l'agent regarde aussi le *pourquoi* : versions de PHP et de WordPress, plugins périmés ou abandonnés, journaux d'erreurs, fichiers oubliés (`.git`, `.env`, sauvegardes), permissions, poids de la base, tâches planifiées, sauvegardes.
- L'agent **teste chaque accès avant de s'en servir** (`access_check.py`, lecture seule). S'il en manque ou s'il ne marche pas, il te demande **tout ce qu'il lui faut en un seul message**, **sans attendre** pour lancer l'audit extérieur. Sans accès vérifié, le rapport dit « extérieur seulement » et classe la partie intérieure dans « non mesuré ».
- **Aucun secret dans le chat.** Tu mets le mot de passe ou la clé dans l'environnement de l'agent et tu lui donnes **le nom** de la variable. Les sorties de commandes passent par `redact.py` avant d'être gardées comme preuve.

L'audit est **en lecture seule** : il n'envoie aucun formulaire, n'achète rien, ne modifie rien. Il ne se connecte que si tu lui donnes un accès pour la vue intérieure, et uniquement pour lire. N'audite qu'un site qui t'appartient ou que tu as le droit d'auditer.

### 2. Lire le résultat

Le dossier `site-audit-<site>-<date>/` contient :

| Fichier | Contenu |
|---|---|
| `report.md` | verdict, scores par domaine, points forts, 5 priorités, constats avec preuve, ce qui n'a pas été mesuré |
| `action-plan.md` | les actions numérotées par priorité, avec cases à cocher |
| `findings.json` | les constats structurés (la source des deux fichiers ci-dessus) |
| `crawl/`, `lh/`, `shots/` | les mesures brutes et les écrans, pour vérifier |

### 3. Faire appliquer le plan

Dis : **« applique le plan d'action »**.

Ce que fait l'agent, dans cet ordre :

1. Il monte le suivi (`fix-state.json`) avec toutes les actions, par priorité.
2. Il liste **en un seul message** tout ce qui lui manque : accès, informations, contenus à fournir, décisions. Chaque élément indique quelle action il débloque. Il demande aussi s'il s'agit de la production ou d'un test, s'il y a une sauvegarde récente et s'il y a des choses à ne pas toucher.
3. Il traite les actions **une par une, de la plus urgente à la moins urgente**. Pour chaque action prête, il te montre ce qu'il change, le risque et le retour arrière, puis attend ton **GO**.
4. Il applique, **vérifie** avec la mesure prévue dans le plan, coche la case et note la preuve dans `fix-log.md`.
5. Une action à laquelle il manque un élément **n'est jamais commencée** : il te redemande l'élément et passe à la suivante qui est prête, si tu es d'accord.

À la fin, il te propose de relancer l'audit sur les mêmes pages pour comparer avec le score de départ. C'est ce second passage qui prouve que les corrections ont fonctionné.

## Les règles du mode correction

Elles sont appliquées par un script (`fix_tracker.py`), pas seulement demandées au modèle : le script refuse (code de sortie 2) ce qui les enfreint.

| Règle | Ce que le script refuse |
|---|---|
| Ordre de priorité | approuver une action alors qu'une plus urgente est encore ouverte, sauf si tu as choisi de sauter et que ta réponse est notée ; sauter (`defer`) sans ton nom ni tes mots |
| Un GO par action | cocher une action jamais approuvée ; approuver au nom de l'agent ; approuver une seconde action tant qu'une autre est approuvée et pas terminée |
| Rien ne démarre avec un manque | approuver une action dont un élément n'a pas été fourni |
| Pas de secret dans le chat ni dans les fichiers | enregistrer un mot de passe ou un jeton : on ne garde que le nom de la variable d'environnement |
| Un accès est testé avant d'être accepté | enregistrer un accès sans résultat frais, marqué par le script et du bon type de `access_check.py` (la marque repère un fichier modifié à la main, elle n'empêche pas une falsification volontaire) (ou, pour un accès qu'aucun script ne sait tester, sans note indiquant un test réussi) |
| Pas de « fait » sans preuve | cocher sans avoir noté ce qui a été vérifié |

Qui applique quoi :

| Mode | Sens |
|---|---|
| `agent` | l'agent applique après ton GO, par un accès déclaré (API WordPress, fichiers, CDN, gestionnaire de balises, dépôt) |
| `assisted` | l'agent prépare le texte, le code ou les réglages, et quelqu'un d'autre les applique |
| `human` | décision juridique, de marque ou de budget, ou travail de spécialiste : à faire par une personne |

Risque : **faible** (réversible en un clic, invisible pour les visiteurs), **moyen** (visible, réversible avec une sauvegarde), **élevé** (paiement, DNS, redirections globales, règles d'indexation, texte légal). Un GO couvre une action, quel que soit son risque : l'agent demande chaque action à son tour et attend la réponse.

L'agent **n'invente jamais** un témoignage, un chiffre, un nom ou un résultat : un contenu de preuve est un élément à te demander.

## Résultat mesuré du mode correction

Test réel sur un petit site fictif servi en local (4 pages), avec des défauts volontaires ([détail et journal](examples/fix-session/), chiffres bruts dans [`examples/benchmark/`](examples/benchmark/) : les deux `report.json` et `findings.json`, et `runs.json`).

| | Avant | Après |
|---|---|---|
| Score indicatif | 87/100 | 91/100 |
| Constats de gravité élevée | 4 | 2 |
| Constats de gravité moyenne | 5 | 3 |

- 4 échanges avec l'agent. **6 actions appliquées et vérifiées sur 12**, 5 en attente d'un élément que seule la personne peut fournir (photos réelles, avis, adresse de réception du formulaire, coordonnées, ton), 1 confiée à un humain (en-têtes du serveur).
- Quand la personne a répondu à une question de décision sans dire GO, l'agent n'a **rien modifié** et a redemandé le GO.
- Le second audit a révélé un effet de bord : le score SEO a baissé (73 puis 69), parce que le canonical pointait vers un domaine fictif qui n'existe pas encore. Le second passage sert aussi à ça.
- Les mêmes constats donnent toujours le même score, mais deux passages d'audit sur le même site peuvent remarquer des choses différentes : un écart de quelques points est du bruit. **Regarde la liste des constats, pas seulement le score.**
- Un seul site de test, une seule conversation : c'est une démonstration, pas une garantie.

## Ce que ça coûte et prend

Mesuré avec Claude Sonnet via Claude Code, environnement propre, un run par cas (chiffres bruts : [`examples/benchmark/runs.json`](examples/benchmark/runs.json)) :

| Opération | Durée | Coût équivalent API |
|---|---|---|
| Audit de 20 pages, vue externe + interne, [site communautaire fictif](examples/community-site/) | environ 4 min 30 s | 0,69 $ |
| Audit de 20 pages, vue externe, deux vrais sites | environ 3 min 50 s et 5 min 30 s | 0,39 $ et 0,44 $ |
| Audit du site de test (4 pages) | environ 2 min 45 s | 0,37 $ |
| Conversation de correction (4 échanges, 6 actions appliquées) | environ 2 min 50 s au total | environ 0,50 $ |
| Nouvel audit du site de test | environ 2 min 40 s | 0,35 $ |

Les scripts de mesure ne coûtent rien et tournent en quelques secondes (Lighthouse x3 est la partie lente). Seule l'interprétation utilise le modèle. Ce sont des runs uniques : un ordre de grandeur, pas un benchmark.

## Usage responsable

- **N'audite que ton site, ou un site que tu as le droit d'auditer.** Les scripts visitent des pages et parcourent le site jusqu'au plafond de pages, 4 requêtes à la fois au plus et au moins 0,1 s d'écart, en respectant `robots.txt` (ils répondent au nom `SiteAuditSkill` ; les jokers `*` et `$`, la règle la plus longue et une règle visant ce nom sont lus comme le dit la RFC 9309 ; un robots.txt qui répond 5xx ou 429, ou qu'on ne peut pas joindre, arrête le parcours, sitemaps compris, et un lien que robots.txt interdit n'est pas demandé du tout). Ne fais pas tourner le skill en boucle sur des listes de sites qui ne sont pas à toi : c'est un outil d'audit, pas un scanner. `devtools.py` ouvre un vrai Chrome et peut cliquer sur le bouton refuser d'un bandeau de cookies qu'il a trouvé, jamais sur un formulaire ni un lien. Après ce clic il bloque les navigations et les envois de formulaire, mais les scripts de la page continuent de tourner et peuvent encore envoyer leurs propres requêtes (mesure d'audience, balises).
- **Le site audité est traité comme non fiable.** Les scripts ne récupèrent que `http` et `https`, et refusent une redirection vers une adresse privée, un service local ou `file://`. Chaque navigateur que le skill démarre (`render.py`, `devtools.py`, Lighthouse, Unlighthouse) passe par un petit proxy local (`netguard.py`) qui résout lui-même chaque nom d'hôte, refuse toute adresse privée, locale ou de métadonnées cloud, et se connecte à l'adresse qu'il a contrôlée : une page ne peut pas atteindre un service interne par une iframe d'un autre site, un service worker, un WebSocket ou une réponse DNS qui change, et les requêtes refusées sont listées dans la sortie (Chrome reçoit aussi l'ordre de n'envoyer aucun trafic UDP hors du proxy, et chaque navigateur est arrêté pour de bon après un délai dépassé). Non couvert : les requêtes que le processus d'Unlighthouse fait lui-même hors de son navigateur (il ne peut pas passer par le proxy), donc chaque page qu'on lui donne est contrôlée juste avant, et une page qui redirige hors du site ou vers une adresse refusée est écartée ; un site qui répond autrement la seconde fois n'est pas couvert. Un audit qui démarre sur une adresse privée littérale, sur `localhost` ou sur un nom que tu déclares toi-même dans `SITE_AUDIT_ALLOW_PRIVATE_HOST` (un nom de préproduction qui ne se résout que dans ton réseau) ne peut atteindre que cet hôte, et le reste du loopback s'il démarre là ; les adresses de métadonnées cloud et link-local ne sont jamais joignables. Un nom qui se résout simplement vers une adresse privée ne désactive pas la garde. Les navigateurs du skill se connectent en direct : derrière un proxy d'entreprise obligatoire, l'audit ne peut pas tourner. C'est un filet, pas un bac à sable : le code de la page tourne quand même dans ton Chrome. **Lance les audits avec un utilisateur normal, sur une machine qui ne détient aucun secret et n'a pas accès à ton réseau interne.**
- **Chrome en root.** Chrome ne démarre en root que sans son bac à sable, ce qui rend une page hostile plus dangereuse. Les scripts le disent quand cela arrive.
- **Vue intérieure.** Lecture seule, secrets uniquement par nom de variable. `redact.py` masque des motifs connus (jetons, mots de passe, clés, cookies, chaînes de connexion) et des données personnelles (adresses e-mail, adresses IP hors boucle locale, numéros de téléphone, champs comme `user_login` ou `billing_email`). Il ne peut pas masquer le nom d'une personne dans un texte libre ou dans un tableau comme `wp user list` : compte plutôt. C'est un filet, pas une garantie. Relis un fichier de preuve avant de le partager. `build_report.py` refuse un rapport qui contient un secret, et refuse des données personnelles quand l'audit a une vue intérieure.
- **Garde le dossier d'audit hors de git.** L'audit écrit `site-audit-<hôte>-<date>/` (preuves, captures, sorties de la vue intérieure). Crée-le hors de tout dépôt, et ne publie jamais ce dossier ni le rapport d'un site qui n'est pas le tien. Les scripts ajoutent un `.gitignore` contenant `*` à la racine d'un dossier nommé ainsi (`site-audit-<hôte>-<date>`), et uniquement celui-là : ils ne touchent jamais un autre dossier, et ils avertissent quand le dossier est dans un dépôt qui ne l'ignore pas.
- **Données personnelles.** Avec la vue intérieure, l'audit peut lire des données sur des personnes (utilisateurs, visiteurs, clients). Tu en deviens responsable au sens du RGPD : demande des comptes et des rôles, pas des noms, et supprime le dossier quand tu as fini. La question d'autorisation de l'étape 0 est une déclaration dans la conversation : aucun script ne peut vérifier que tu as le droit d'auditer un site.
- **Mode correction.** `fix_tracker.py` impose l'ordre, le GO et les éléments manquants. `init` exige `--owner NOM`, la personne qui donne le GO ; `approve` et `defer` (sauter une action) n'acceptent que ce nom, et refusent les noms d'agent et les mots de rôle (`owner`, `client`, `oui`...). Un GO couvre une action : le suivi refuse un second `approve` tant qu'une autre action est approuvée et pas terminée, mais il ne sait pas si tu as vraiment été interrogé avant chacune : un GO pour plusieurs actions d'un coup (« go pour P1 et P2 ») n'est pas un GO, et cette partie-là reste à l'agent. Le contrôle des noms n'attrape que les noms évidents (agents, outils, mots de rôle) : le GO doit quand même venir d'une personne. Un accès n'est accepté que depuis un fichier frais de `access_check.py --out` (marqué par le script : un fichier modifié à la main est repéré, pas une falsification volontaire ; du type que le besoin déclare), et `--ref` doit être le nom d'une variable qui existe dans l'environnement. C'est un garde-fou pour un agent honnête, pas une frontière de sécurité : un agent qui peut lancer n'importe quelle commande peut encore modifier le fichier d'état, et la preuve d'un accès est déclarative. La trace, c'est le nom écrit dans `fix-log.md`. Fais une sauvegarde avant toute action de risque moyen ou élevé.
- **Rien ici ne certifie une conformité ni ne prédit un gain.** Le rapport dit ce qui a été mesuré, ce qui a été lu et ce qui n'a pas été regardé.

## Limites, dites franchement

- Les chiffres Lighthouse sont des mesures **labo**, faites au moment de l'audit. Les données de vrais visiteurs (CrUX) sont un agrégat sur 28 jours : elles ne sont **pas fraîches**, elles ne changent que lentement après une correction, et elles n'existent que si la page a assez de trafic (sinon on n'a que le site entier, et le rapport le dit). `psi.py` demande une **clé API Google gratuite** ; sans elle, ces données sont « non mesurées ». L'INP n'existe que dans ces données réelles.
- Un site dont la protection (Cloudflare, Sucuri, Akamai et équivalents) arrête la machine d'audit ne peut pas être audité de l'extérieur : les scripts reconnaissent la page de défi ou de blocage, le disent et s'arrêtent. Ils n'essaient jamais de la contourner. Demande au propriétaire d'autoriser l'adresse de la machine d'audit, ou audite une copie du site.
- Le crawl lit le HTML initial. Les sites rendus en JavaScript sont signalés, et `render.py` lit la page rendue pour l'URL auditée uniquement.
- Les constats de conversion et de copy sont des **jugements** (`deduced`), pas des mesures. Ils viennent avec une citation ou un écran, et un test pour les confirmer.
- Les scores sont indicatifs : un modèle de pénalités transparent (critique 40, élevée 20, moyenne 8, faible 3, réduites à 70 % si déduit et 40 % si hypothèse), pas une norme. Deux passages sur le même site peuvent différer de quelques points.
- Les contrôles d'accessibilité sont automatiques et partiels. Rien ici ne certifie une conformité légale (RGAA, RGPD, EAA).
- Le tracking avant consentement est observé par `devtools.py` dans un vrai Chrome, en une seule passe, depuis la machine qui fait l'audit : un bandeau peut changer selon le pays du visiteur. Ce n'est pas un avis juridique.
- Les incohérences (`consistency.py`) sont des **candidats avec les deux passages cités** : l'agent les relit et ne garde que les vraies contradictions. Sur un site rendu en JavaScript, seul le HTML initial est lu.
- Unlighthouse (`lh_site.py`) sert à **repérer** les pages lentes, avec une seule mesure par page ; les deux ou trois pires se confirment avec `lh_median.py`.
- Le mode correction a été testé sur des fichiers HTML statiques. Sur un site WordPress ou un CDN réel, la fiabilité dépend de l'accès que tu donnes : sans accès, toutes les actions deviennent des consignes prêtes à appliquer (`assisted`).
- Tu restes responsable de ce que l'agent change sur ton site : garde une sauvegarde récente avant une action de risque moyen ou élevé.

## Développer

```
python3 -I -m unittest discover -s tests
```

320 tests hors ligne : un faux site local pour le crawler et le script de faits, le validateur, le calcul des scores et le plan d'action, les règles du mode correction (ordre, GO, éléments manquants, secrets), le détecteur d'incohérences (contradictions plantées, et choses qui y ressemblent sans en être), un faux serveur Google pour `psi.py` (fraîcheur, périmètre page ou site, données périmées, clé absente), un vrai Chrome pour `devtools.py` (cookies, tiers, test du bouton « refuser ») et pour le rendu (ignoré si Chrome est absent), les contrôles d'accès (un `sshd` jetable si disponible), et le masquage des secrets. Une suite d'entrées hostiles couvre les redirections vers `file://` et les adresses privées (par redirection, par script, par sitemap), une règle robots visant le crawler, un bouton « refuser » dans un formulaire ou relié à un formulaire, les secrets dans les notes, et une page hostile qui tente d'atteindre un service interne depuis un vrai Chrome (iframe d'un autre site, service worker, WebSocket, préchargement) ou une règle robots.txt conçue pour bloquer le crawler. `python3 -I tests/mutation_check.py` casse 96 règles une à une sur une copie du dépôt, vérifie d'abord que la copie intacte est verte, et ne compte un mutant comme détecté que si un test échoue sur une vérification, pas parce que le code a simplement planté.

## Crédits

**Créé par [Kavyro.com](https://kavyro.com)**, la communauté pour apprendre à travailler avec des agents IA.

La structure et les checklists par domaine s'appuient sur la lecture de ces excellents projets. Aucun code ni texte n'a été copié : les références sont écrites de zéro.

- [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills)
- [addyosmani/web-quality-skills](https://github.com/addyosmani/web-quality-skills)
- [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)
- [seo-skills/seo-audit-skill](https://github.com/seo-skills/seo-audit-skill)
- [squirrelscan/squirrelscan](https://github.com/squirrelscan/squirrelscan)

Les données de vitesse viennent de [Lighthouse](https://github.com/GoogleChrome/lighthouse), de l'[API PageSpeed Insights](https://developers.google.com/speed/docs/insights/v5/get-started) et du Chrome UX Report de Google, et, pour plusieurs pages à la fois, de [Unlighthouse](https://github.com/harlan-zw/unlighthouse) (suggestion d'un membre de la communauté). Aucun n'est inclus.

## Licence

MIT. Fait par [Kavyro.com](https://kavyro.com).
