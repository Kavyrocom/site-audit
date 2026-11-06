# Audit de http://127.0.0.1:18940/

Date: 2026-11-05 · Périmètre: site complet (échantillon : 16 pages) · Appareil: mobile  
Profondeur: externe + interne (accès en lecture : wp)  
Lecture seule : rien n'a été modifié sur le site.

**Objectif de la page** : Amener les visiteurs à rejoindre la communauté gratuite, puis à passer à la formule complète (donné)

## 1. Verdict

Le site est sain sur le plan technique (aucune page cassée, aucun traceur avant consentement, CLS nul), mais le parcours gratuit puis payant est abîmé : prix contradictoires (29 € contre 39 €), formule gratuite sans bouton, page de paiement sans moyen de payer, et lien d'inscription du menu qui contient un gabarit non remplacé.

## 2. Score global : 73/100

Scores indicatifs, calculés à partir des constats (méthode en bas de page).

Domaines audités : 10 sur 10. Si les 4 constats déduits ou hypothétiques se confirment tous : 70/100 (contre 73/100 aujourd'hui).

| Domaine | Score | |
|---|---|---|
| Technique et indexation | 72/100 | `███████░░░` |
| SEO | 72/100 | `███████░░░` |
| Rapidité | 72/100 | `███████░░░` |
| Accessibilité | 92/100 | `█████████░` |
| UX et mobile | 92/100 | `█████████░` |
| Conversion (CRO) | 41/100 | `████░░░░░░` |
| Copywriting | 57/100 | `██████░░░░` |
| Sécurité | 97/100 | `██████████` |
| Tracking et consentement | 86/100 | `█████████░` |
| Visibilité IA | 97/100 | `██████████` |

## 3. Ce qui marche

**Technique et indexation**
- Les 16 pages explorées répondent 200, sans lien cassé ni chaîne de redirections, avec un robots.txt propre qui déclare le sitemap. _(Preuve : crawl/summary.json: status_counts 200=16, pages_crawled=16, cap_reached=false; facts.json: site_level.robots.txt status 200, sitemap déclaré)_

**SEO**
- Lighthouse SEO à 100/100 sur la page d'accueil, langue fr déclarée, viewport présent, canonique de l'accueil auto-référente. _(Preuve : lh/summary.json: scores.seo median 100 (3 runs); facts.json: html_lang=fr, canonical_is_self=true)_

**Rapidité**
- Hors image d'en-tête, la page est légère pour le navigateur : aucun décalage de mise en page, blocage du thread principal très faible, aucun tiers. _(Preuve : lh/summary.json: cls median 0, tbt_ms median 31; devtools/devtools.json: third_party count 0, main_thread busy_ms 35, failed_requests vide)_

**Accessibilité**
- Lighthouse accessibilité à 92/100, avec langue de page, champs de formulaire entourés d'un label et titres hiérarchisés. _(Preuve : lh/summary.json: scores.accessibility median 92; facts.json: html_lang=fr; HTML de /communaute-gratuite/: deux balises label autour des champs)_

**UX et mobile**
- La première vue annonce une promesse claire (titre H1) avec un seul bouton principal vert, une navigation courte de 5 liens et un en-tête stable. _(Preuve : shots/mobile-01.png: logo, 5 liens, bouton Rejoindre, titre; shots/mobile-02.png: bouton Commencer gratuitement)_

**Conversion (CRO)**
- L'offre est lisible : démarrage gratuit, prix affiché, et les réassurances 'Satisfait ou remboursé sous 14 jours' et 'Sans engagement' figurent sur la page des formules. _(Preuve : shots/rendered-mobile.txt: 'Accès gratuit pour démarrer, formule complète'; HTML de /formules/: 'Satisfait ou remboursé sous 14 jours. Sans engagement.')_

**Copywriting**
- Le texte est concret et tutoie le lecteur de façon constante : atelier en direct chaque semaine, corrections de portfolio par des professionnels, défis hebdomadaires. _(Preuve : shots/rendered-mobile.txt lignes 4 à 12; consistency/consistency.json: name_variants vide (nom de marque écrit de la même façon partout))_

**Sécurité**
- Aucune ressource en contenu mixte, aucun tiers chargé, X-Content-Type-Options à nosniff, et /wp-admin/ exclu dans robots.txt. _(Preuve : devtools/devtools.json: mixed_content vide, third_party count 0; facts.json: headers.x-content-type-options=nosniff, robots.txt 'Disallow: /wp-admin/')_

**Tracking et consentement**
- Lors d'une première visite, aucun traceur ni cookie ne part avant interaction, le bouton Refuser est aussi visible que Tout accepter, et rien de nouveau ne se déclenche après un refus. _(Preuve : devtools/devtools.json: before_any_interaction.tracker_requests vide, cookie_summary.total 0; after_refuse.refuse_visible=true, verdict 'nothing new fired after refusing')_

**Visibilité IA**
- robots.txt autorise tous les robots et le contenu principal est présent dans le HTML initial (150 mots lisibles sans JavaScript). _(Preuve : facts.json: site_level.robots.txt 'User-agent: * Allow: /', robots_disallow_all=false, word_count_visible_raw_html=150)_

## 4. Les priorités

### 1. Deux prix différents pour la formule complète (29 € et 39 €)  
`Critique` · Copywriting

L'accueil annonce la formule complète à 29 € par mois, mais la page des formules et la page de paiement affichent 39 € par mois. Un visiteur qui clique sur 'Choisir' voit un prix supérieur de 10 € à celui qui l'a attiré : c'est un risque d'abandon et de confiance, au moment même où la conversion se joue. Le script de cohérence relève ce conflit : il propose les deux passages, le jugement reste humain.

- **Preuve** : shots/rendered-mobile.txt ligne 7 (accueil): 'formule complète à 29 € par mois'; HTML de /formules/: 'Complet ... 39 € par mois, ateliers illimités'; HTML de /paiement/: 'Formule complète, 39 € par mois.'
- **Action** : Décider du vrai prix et l'écrire à l'identique sur l'accueil, les formules et le paiement.
- **Effort** : faible · **Impact** : élevé · **Confiance** : mesuré
- **Pages** : /, /formules/, /paiement/

### 2. Le bouton 'Rejoindre' de l'en-tête contient un gabarit non remplacé  
`Élevée` · Conversion (CRO)

Le bouton principal de l'en-tête, présent sur les 16 pages, pointe vers /communaute-gratuite/?ref={source} : le texte {source} n'est jamais remplacé. La page s'ouvre quand même, mais la mesure de provenance des inscrits est faussée et le paramètre pollue l'adresse.

- **Preuve** : HTML de /, /formules/, /contact/, /paiement/, /communaute-gratuite/: <a class="cta" href="/communaute-gratuite/?ref={source}">Rejoindre</a>; crawl: 16 pages avec le même lien
- **Action** : Remplacer le gabarit par une valeur réelle ou retirer le paramètre.
- **Effort** : faible · **Impact** : élevé · **Confiance** : mesuré
- **Pages** : toutes les pages (en-tête)

### 3. 15 pages sur 16 déclarent la page d'accueil comme canonique  
`Élevée` · SEO

Chaque page autre que l'accueil porte une balise canonique vers http://127.0.0.1:18940/. Google peut donc ignorer /formules/, /communaute-gratuite/ et les articles du blog au profit de l'accueil : ces pages risquent de ne jamais apparaître dans les résultats. Trois extensions SEO sont actives en même temps, ce qui peut expliquer la balise.

- **Preuve** : crawl/summary.json: issue counts canonical_points_elsewhere=15; crawl/pages.jsonl: canonical_is_self=false sur /formules/, /communaute-gratuite/, /blog/article-1/ à /blog/article-6/, etc.; internal/wp-plugins.txt: pixel-seo, pixel-seo-16 actifs
- **Action** : Faire que chaque page déclare sa propre adresse comme canonique.
- **Effort** : faible · **Impact** : élevé · **Confiance** : mesuré
- **Pages** : /communaute-gratuite/, /formules/, /blog/, /a-propos/, /contact/, /blog/article-1/ à article-6

### 4. L'image d'en-tête de 2,1 Mo rend le chargement très lent en simulation mobile  
`Élevée` · Rapidité

En laboratoire Lighthouse (mobile simulé), le plus grand élément affiché met 15,8 s et le score performance est 64/100. L'élément en cause est hero.png, un PNG de 2,1 Mo, soit les trois quarts des 2,9 Mo de la page. Mesure de laboratoire en simulation, pas une mesure de visiteurs réels. Le test sans bridage (devtools) donne 80 ms, ce qui confirme que le coût vient du poids sur réseau mobile.

- **Preuve** : lh/summary.json: lcp_ms median 15751 (min 15750, max 15752), performance median 64, total_bytes 2957209; digest image-delivery-insight 'Est savings of 2,075 KiB'; devtools/devtools.json: lcp_element img /assets/hero.png, Image 2111 KB
- **Action** : Remplacer hero.png par une image WebP ou AVIF d'environ 100 Ko, aux bonnes dimensions.
- **Effort** : faible · **Impact** : élevé · **Confiance** : mesuré
- **Pages** : /

### 5. La page de paiement n'offre aucun moyen de payer et la formule gratuite n'a pas de bouton  
`Critique` · Conversion (CRO)

Sur /formules/, seule la carte 'Complet' a un bouton 'Choisir'; la carte 'Gratuit' n'en a aucun, alors que l'objectif numéro un est l'inscription gratuite. Le bouton 'Choisir' mène à /paiement/, qui ne contient qu'un titre et une phrase : ni formulaire, ni bouton de paiement, ni récapitulatif, ni réassurance. Le parcours gratuit puis payant s'arrête donc là. Aucune action de paiement n'a été tentée (lecture seule).

- **Preuve** : HTML de /formules/: bloc 'Gratuit' avec '0 €' sans lien, bloc 'Complet' avec <a class="btn" href="/paiement/">Choisir</a>; HTML de /paiement/: <main><h1>Paiement</h1><p>Formule complète, 39 € par mois.</p></main>, aucun formulaire (crawl/pages.jsonl: forms=0)
- **Action** : Ajouter un bouton à la formule gratuite et un vrai tunnel de paiement sur /paiement/.
- **Effort** : moyen · **Impact** : élevé · **Confiance** : déduit
- **Pages** : /formules/, /paiement/

## 5. Détail par domaine

### Technique et indexation : 72/100

**Problèmes à traiter**

- `Élevée` **Les adresses inexistantes répondent 200 et le sitemap contient une page 'n'existe pas'** : Une adresse inventée renvoie un code 200 avec une page d'accueil allégée au lieu d'un 404 (soft 404). /sitemap_index.xml, /wp-sitemap.xml et /llms.txt renvoient eux aussi cette page HTML. Le sitemap liste /ancienne-page/ (titre 'Cercle Pixel', H1 'Cette page n'existe pas') ainsi que /espace-membres/, qui est en noindex. _(Preuve : facts.json: site_level.soft_404_test status 200 (attendu 404); crawl/pages.jsonl: /ancienne-page/ in_sitemap=true, h1_first='Cette page n'existe pas'; /espace-membres/ noindex=true in_sitemap=true)_ → Faire renvoyer un vrai 404, retirer les pages mortes et non indexables du sitemap.
- `Moyenne` **29 extensions actives, dont des doublons (cache, SEO, sécurité, consentement)** : Pour un site de 16 pages, 29 extensions sont actives. Plusieurs fonctions sont assurées en double ou plus : 3 extensions de cache (pixel-cache, pixel-cache-15, pixel-cache-30), 4 de sécurité, 2 de SEO, 2 de consentement, 2 d'analytique, 2 de sauvegarde, 2 de redirections. Ces doublons expliquent probablement les canoniques erronées (F4), le cache désactivé (F7) et le consentement ambigu (F8), et élargissent la surface d'attaque. 2 autres extensions (pixel-shop, pixel-forms-19) sont installées mais inactives. La disponibilité de mises à jour n'est pas exposée par l'API : non vérifiée. _(Preuve : internal/wp-plugins.txt: total 31, 29 actives; pixel-cache, pixel-cache-15, pixel-cache-30 actives; pixel-seo et pixel-seo-16; pixel-consent et pixel-consent-23; access-wp.json: plugins_total 31, plugins_active 29)_ → Garder une extension par fonction et supprimer les autres, après sauvegarde.

### SEO : 72/100

**Problèmes à traiter**

- `Élevée` **15 pages sur 16 déclarent la page d'accueil comme canonique** : Chaque page autre que l'accueil porte une balise canonique vers http://127.0.0.1:18940/. Google peut donc ignorer /formules/, /communaute-gratuite/ et les articles du blog au profit de l'accueil : ces pages risquent de ne jamais apparaître dans les résultats. Trois extensions SEO sont actives en même temps, ce qui peut expliquer la balise. _(Preuve : crawl/summary.json: issue counts canonical_points_elsewhere=15; crawl/pages.jsonl: canonical_is_self=false sur /formules/, /communaute-gratuite/, /blog/article-1/ à /blog/article-6/, etc.; internal/wp-plugins.txt: pixel-seo, pixel-seo-16 actifs)_ → Faire que chaque page déclare sa propre adresse comme canonique.
- `Moyenne` **Titres trop longs, descriptions manquantes ou génériques, et deux H1 sur l'accueil** : 7 titres dépassent 65 caractères (l'accueil en compte 137) et seront coupés dans les résultats. 4 pages n'ont pas de description et 6 articles du blog utilisent la même phrase 'Un article du blog Cercle Pixel.'. L'accueil a deux H1 ('Apprends la retouche photo...' et 'Cercle Pixel'), et /espace-membres/ n'en a aucun. Aucune image Open Graph sur les 16 pages, et 3 images sans attribut alt (À propos, article 3). Une partie des titres d'articles est longue et un contient 'en 2025', déjà daté. _(Preuve : crawl/summary.json: title_too_long_over_65=7, missing_meta_description=4, duplicate_meta_descriptions=1, multiple_h1=1, missing_h1=1, missing_og_image=16, images_missing_alt=3; facts.json: title_len=137, h1_count_raw=2)_ → Réécrire les titres et descriptions, garder un seul H1 par page et ajouter les alt et l'image de partage.

### Rapidité : 72/100

**Problèmes à traiter**

- `Élevée` **L'image d'en-tête de 2,1 Mo rend le chargement très lent en simulation mobile** : En laboratoire Lighthouse (mobile simulé), le plus grand élément affiché met 15,8 s et le score performance est 64/100. L'élément en cause est hero.png, un PNG de 2,1 Mo, soit les trois quarts des 2,9 Mo de la page. Mesure de laboratoire en simulation, pas une mesure de visiteurs réels. Le test sans bridage (devtools) donne 80 ms, ce qui confirme que le coût vient du poids sur réseau mobile. _(Preuve : lh/summary.json: lcp_ms median 15751 (min 15750, max 15752), performance median 64, total_bytes 2957209; digest image-delivery-insight 'Est savings of 2,075 KiB'; devtools/devtools.json: lcp_element img /assets/hero.png, Image 2111 KB)_ → Remplacer hero.png par une image WebP ou AVIF d'environ 100 Ko, aux bonnes dimensions.
- `Moyenne` **724 Ko de JavaScript inutilisé et aucune mise en cache** : Le fichier vendor-bundle.js (environ 724 Ko) est chargé sur chaque page alors que presque rien n'y sert, et le CSS fait 35 Ko non minifiés. Toutes les réponses portent Cache-Control: no-store : le navigateur retélécharge tout à chaque page, y compris l'image de 2,1 Mo. Trois extensions de cache sont actives (voir F13). _(Preuve : lh/summary.json: unused-javascript 'Est savings of 724 KiB', unused-css-rules et unminified-css 34 KiB, cache-insight 'Est savings of 2,763 KiB'; facts.json: headers.cache-control=no-store; devtools/devtools.json: Script 738 KB)_ → Retirer le script inutilisé, minifier le CSS et autoriser la mise en cache des fichiers statiques.

### Accessibilité : 92/100

**Problèmes à traiter**

- `Moyenne` **Contrastes insuffisants et 13 zones tactiles trop petites** : Lighthouse signale un contraste insuffisant (le texte blanc sur le vert clair des boutons en est un exemple visible) et des cibles tactiles trop petites ou trop serrées. Le rendu mobile en liste 13, dont les liens du menu qui se touchent. Le champ e-mail du formulaire est de plus un champ texte simple, sans type e-mail ni autocomplétion (voir aussi F11). _(Preuve : lh/summary.json: digest.failed_audits color-contrast et target-size, accessibilité 92; shots/rendered.json: small tap targets 13; shots/mobile-01.png: boutons vert clair à texte blanc)_ → Foncer le vert des boutons et agrandir les zones tactiles à 44 px au moins.

### UX et mobile : 92/100

**Problèmes à traiter**

- `Moyenne` **Le bandeau de cookies couvre 43 % du premier écran mobile** : Sur mobile, le bandeau noir masque le bas du titre et tout ce qui suit, y compris le bouton 'Commencer gratuitement' qui n'apparaît qu'en descendant. Le visiteur doit trancher le bandeau avant de voir l'offre. _(Preuve : shots/rendered.json: fixed_or_sticky share_of_screen 43 %; devtools/devtools.json: consent_banner share_of_screen_pct 43; shots/mobile-01.png: titre coupé après 'répond')_ → Réduire le bandeau à une barre compacte en bas d'écran.

### Conversion (CRO) : 41/100

**Problèmes à traiter**

- `Critique` **La page de paiement n'offre aucun moyen de payer et la formule gratuite n'a pas de bouton** : Sur /formules/, seule la carte 'Complet' a un bouton 'Choisir'; la carte 'Gratuit' n'en a aucun, alors que l'objectif numéro un est l'inscription gratuite. Le bouton 'Choisir' mène à /paiement/, qui ne contient qu'un titre et une phrase : ni formulaire, ni bouton de paiement, ni récapitulatif, ni réassurance. Le parcours gratuit puis payant s'arrête donc là. Aucune action de paiement n'a été tentée (lecture seule). _(Preuve : HTML de /formules/: bloc 'Gratuit' avec '0 €' sans lien, bloc 'Complet' avec <a class="btn" href="/paiement/">Choisir</a>; HTML de /paiement/: <main><h1>Paiement</h1><p>Formule complète, 39 € par mois.</p></main>, aucun formulaire (crawl/pages.jsonl: forms=0))_ → Ajouter un bouton à la formule gratuite et un vrai tunnel de paiement sur /paiement/.
- `Élevée` **Le bouton 'Rejoindre' de l'en-tête contient un gabarit non remplacé** : Le bouton principal de l'en-tête, présent sur les 16 pages, pointe vers /communaute-gratuite/?ref={source} : le texte {source} n'est jamais remplacé. La page s'ouvre quand même, mais la mesure de provenance des inscrits est faussée et le paramètre pollue l'adresse. _(Preuve : HTML de /, /formules/, /contact/, /paiement/, /communaute-gratuite/: <a class="cta" href="/communaute-gratuite/?ref={source}">Rejoindre</a>; crawl: 16 pages avec le même lien)_ → Remplacer le gabarit par une valeur réelle ou retirer le paramètre.
- `Moyenne` **Le formulaire d'inscription gratuite est minimal mais mal typé et sans réassurance** : Le formulaire n'a que deux champs, ce qui est bien. Mais le champ e-mail est de type texte (le clavier mobile ne propose pas l'arobase), les champs s'appellent 'e' et 'p', sans autocomplétion, et rien ne dit ce qui se passe après l'envoi ni que la carte bancaire n'est pas demandée. Le formulaire n'a pas été envoyé (lecture seule). _(Preuve : HTML de /communaute-gratuite/: <input type="text" name="e"> et <input type="text" name="p">, <button>Je m'inscris</button>, aucun texte de réassurance; crawl/pages.jsonl: forms=1)_ → Typer les champs, ajouter l'autocomplétion et une ligne de réassurance sous le bouton.
- `Moyenne` **La section 'Ils en parlent' n'affiche aucune preuve** : Sur l'accueil, la section 'Ils en parlent' ne contient qu'une phrase générale ('Des membres de toute la francophonie progressent chaque mois') : ni témoignage, ni nom, ni résultat. L'affirmation 'Plus de 1 200 membres' n'est pas sourcée. La page entière ne fait que 129 mots rendus. _(Preuve : shots/rendered-mobile.txt lignes 12 à 16; shots/rendered.json: 129 mots rendus, aucun bloc citation; les 2 écrans mobiles lus (la page fait 2 écrans))_ → Ajouter deux vrais témoignages signés et un chiffre daté dans la section.

### Copywriting : 57/100

**Problèmes à traiter**

- `Critique` **Deux prix différents pour la formule complète (29 € et 39 €)** : L'accueil annonce la formule complète à 29 € par mois, mais la page des formules et la page de paiement affichent 39 € par mois. Un visiteur qui clique sur 'Choisir' voit un prix supérieur de 10 € à celui qui l'a attiré : c'est un risque d'abandon et de confiance, au moment même où la conversion se joue. Le script de cohérence relève ce conflit : il propose les deux passages, le jugement reste humain. _(Preuve : shots/rendered-mobile.txt ligne 7 (accueil): 'formule complète à 29 € par mois'; HTML de /formules/: 'Complet ... 39 € par mois, ateliers illimités'; HTML de /paiement/: 'Formule complète, 39 € par mois.')_ → Décider du vrai prix et l'écrire à l'identique sur l'accueil, les formules et le paiement.
- `Faible` **Deux numéros de téléphone différents et une année de copyright périmée** : Le numéro de téléphone du pied de page (présent sur toutes les pages) diffère du numéro de la page Contact, par le dernier chiffre. Le copyright affiche 2022 alors que nous sommes en 2026, ce qui donne une impression de site abandonné. La page à propos annonce une existence depuis 2019, ce qui reste cohérent. _(Preuve : consistency/consistency.json: contacts.phones contient 2 numéros distincts (un sur 6 pages et plus, un seul sur /contact/); year_claims.issues: footer copyright year is 2022, current year is 2026)_ → Garder un seul numéro et rendre l'année du copyright automatique.

### Sécurité : 97/100

**Problèmes à traiter**

- `Faible` **En-têtes de sécurité absents et version du serveur divulguée** : Content-Security-Policy, X-Frame-Options, Referrer-Policy et Permissions-Policy sont absents, et l'en-tête Server indique 'nginx Python/3.14.7'. HSTS n'est pas évalué (site servi en HTTP local). _(Preuve : facts.json: headers.content-security-policy null, x-frame-options null, referrer-policy null, permissions-policy null, server 'nginx Python/3.14.7')_ → Ajouter les en-têtes de base côté serveur et masquer la version.

### Tracking et consentement : 86/100

**Problèmes à traiter**

- `Élevée` **Le code déclare le consentement analytique 'accordé' par défaut et le bandeau valide par la simple poursuite** : Dans l'en-tête de chaque page, gtag('consent','default',{analytics_storage:'granted'}) accorde la mesure avant tout choix. Le bandeau affirme de plus 'En continuant, vous acceptez leur utilisation', formule qui ne vaut pas consentement. Au test réel, aucune requête de traceur ne part avant interaction (ce qui est bon), donc le risque dépend de ce que charge gtm-loader.js une fois en conditions réelles. Deux outils de consentement sont actifs (voir F13). _(Preuve : HTML de /formules/: gtag('consent','default',{analytics_storage:'granted',ad_storage:'denied'}); shots/rendered-mobile.txt ligne 20; devtools/devtools.json: before_any_interaction.tracker_requests vide; facts.json: trackers_detected google-analytics/gtag, google-tag-manager)_ → Passer le consentement par défaut à 'denied' et ne l'accorder qu'après un clic sur Tout accepter.

### Visibilité IA : 97/100

**Problèmes à traiter**

- `Faible` **Ni llms.txt, ni données structurées** : Il n'y a aucune donnée structurée (JSON-LD) : l'accueil ne se déclare ni comme organisation ni comme formation. /llms.txt renvoie une page HTML avec un code 200 au lieu d'un fichier texte (voir F5), et Lighthouse signale le fichier comme non conforme. _(Preuve : facts.json: structured_data.jsonld_blocks 0; site_level./llms.txt status 200, contenu '<!doctype html>'; lh/summary.json: audit llms-txt score 0)_ → Ajouter un JSON-LD Organization et un court llms.txt.

## 6. Plan d'action

Le plan détaillé, étape par étape, avec responsable et vérification, est dans `action-plan.md`.

**Cette semaine**
- Deux prix différents pour la formule complète (29 € et 39 €) (Responsable : Propriétaire du site, Effort faible, Impact élevé)
- Le bouton 'Rejoindre' de l'en-tête contient un gabarit non remplacé (Responsable : Développeur ou agence web, Effort faible, Impact élevé)
- 15 pages sur 16 déclarent la page d'accueil comme canonique (Responsable : Développeur ou agence web, Effort faible, Impact élevé)
- L'image d'en-tête de 2,1 Mo rend le chargement très lent en simulation mobile (Responsable : Rédaction ou contenu, Effort faible, Impact élevé)
- Le code déclare le consentement analytique 'accordé' par défaut et le bandeau valide par la simple poursuite (Responsable : Développeur ou agence web, Effort faible, Impact moyen)
- Le bandeau de cookies couvre 43 % du premier écran mobile (Responsable : Développeur ou agence web, Effort faible, Impact moyen)
- Contrastes insuffisants et 13 zones tactiles trop petites (Responsable : Développeur ou agence web, Effort faible, Impact moyen)
- Titres trop longs, descriptions manquantes ou génériques, et deux H1 sur l'accueil (Responsable : Marketing, Effort faible, Impact moyen)
- Le formulaire d'inscription gratuite est minimal mais mal typé et sans réassurance (Responsable : Développeur ou agence web, Effort faible, Impact moyen)
- La section 'Ils en parlent' n'affiche aucune preuve (Responsable : Rédaction ou contenu, Effort faible, Impact moyen)

**Ce mois-ci**
- La page de paiement n'offre aucun moyen de payer et la formule gratuite n'a pas de bouton (Responsable : Développeur ou agence web, Effort moyen, Impact élevé)
- Les adresses inexistantes répondent 200 et le sitemap contient une page 'n'existe pas' (Responsable : Développeur ou agence web, Effort moyen, Impact moyen)
- 724 Ko de JavaScript inutilisé et aucune mise en cache (Responsable : Développeur ou agence web, Effort moyen, Impact moyen)
- 29 extensions actives, dont des doublons (cache, SEO, sécurité, consentement) (Responsable : Développeur ou agence web, Effort moyen, Impact moyen)

**Ensuite**
- Deux numéros de téléphone différents et une année de copyright périmée (Responsable : Propriétaire du site, Effort faible, Impact faible)
- En-têtes de sécurité absents et version du serveur divulguée (Responsable : Hébergeur ou CDN, Effort faible, Impact faible)
- Ni llms.txt, ni données structurées (Responsable : Marketing, Effort faible, Impact faible)

## 7. Non mesuré et limites

- HTTPS, HSTS, redirection http vers https : le site est servi en HTTP sur la machine locale, donc non mesurables et non comptés comme défauts.
- PageSpeed Insights et données réelles CrUX : non mesurables sur un site local. L'INP n'est pas mesuré non plus (Lighthouse ne le fournit pas).
- Lighthouse (3 passages) mesuré sur l'accueil seulement; /formules/ et /communaute-gratuite/ ne sont pas des pages à image lourde, mais leur performance propre n'a pas été mesurée (unlighthouse non installé).
- Rendu en navigateur et captures : accueil seulement (2 écrans mobiles lus, couverture complète). Les autres pages ont été lues dans leur HTML, sans capture. Les captures bureau n'ont pas été regardées.
- Partie interne : accès WordPress via l'API REST en lecture seule (administrateur vérifié). Lisibles : liste des extensions. Non lisibles : thèmes, réglages et pages (l'API a répondu 404), mises à jour disponibles, version de PHP, journaux, poids de la base, fichiers exposés, sauvegardes (pas d'accès ssh ou fichiers).
- Formulaire d'inscription et paiement : jamais envoyés ni testés (audit en lecture seule); le comportement après envoi est inconnu.
- Contenu du conteneur Google Tag Manager et de gtm-loader.js : non lu, donc ce qui se lancerait après consentement est inconnu.
- Zones connectées (espace membres) : non auditées.

## 8. Méthode et preuves

Chaque constat porte une preuve, une gravité, un effort, un impact et un niveau de confiance. Score d'un domaine = 100 moins la somme des pénalités (critique 40, élevée 20, moyenne 8, faible 3), réduites à 70 % si le constat est déduit et à 40 % si c'est une hypothèse (le rapport donne aussi le score si tous ces constats incertains se confirmaient). Le score global est la moyenne pondérée des domaines audités. Une priorité est classée selon gravité x impact / effort, pondérée par la confiance.

Sources : `facts.json`, `lh/summary.json`, `devtools/devtools.json`, `shots/rendered.json`, `shots/rendered-mobile.txt`, `shots/mobile-01.png`, `shots/mobile-02.png`, `crawl/pages.jsonl`, `crawl/summary.json`, `consistency/consistency.json`, `access-wp.json`, `internal/wp-plugins.txt`
