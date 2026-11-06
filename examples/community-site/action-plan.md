# Plan d'action : http://127.0.0.1:18940/

Basé sur l'audit du 2026-11-05. Score actuel : 73/100. 17 actions : 10 cette semaine, 4 ce mois-ci, 3 ensuite. Coche chaque case une fois la correction faite et vérifiée.

## Faire appliquer ce plan par l'agent

1. Dis : « applique le plan d'action ».
2. L'agent traite les actions par ordre de priorité (le numéro devant chaque action).
3. Il ne commence une action que s'il a tout ce qu'il lui faut. Sinon il te demande le complément, avec la liste ci-dessous.
4. Pour chaque action prête, il te montre ce qu'il va changer, le risque et le retour arrière, et attend ton GO. Rien n'est appliqué sans GO.
5. Après chaque action, il vérifie le résultat avec « Comment vérifier » puis coche la case.

## Ce que l'agent doit recevoir de toi

Pour appliquer le plan, l'agent a besoin de ces éléments. Il te les demande en une fois avant de commencer. Si un élément manque ou ne marche plus en cours de route, il s'arrête sur cette action, te le redemande et passe aux suivantes seulement si tu le décides.

- **décision** · `ref_tracking_choice` : Le suivi de provenance ?ref= est-il utilisé, et avec quelles valeurs (action 2)
- **décision** · `seo_plugin_choice` : Quelle extension SEO conserver parmi pixel-seo et pixel-seo-16 (action 3)
- **contenu à fournir** · `hero_source_image` : L'image d'origine de l'en-tête, ou le feu vert pour en choisir une autre (action 4)
- **décision** · `consent_rules` : Quels outils de mesure peuvent se lancer avant consentement, et lesquels seulement après (action 6)
- **décision** · `old_page_target` : Vers quelle page rediriger /ancienne-page/, ou la supprimer (action 7)
- **contenu à fournir** · `og_image` : Une image de partage 1200 x 630 px au nom de la marque (action 10)
- **information** · `signup_promise` : Confirmer que l'inscription gratuite ne demande pas de carte bancaire et ce que reçoit le membre (action 11)
- **contenu à fournir** · `real_testimonials` : Deux témoignages réels de membres, avec leur accord de publication (action 12)
- **information** · `bundle_owner` : Quelle extension ou quel thème dépend de vendor-bundle.js (action 13)
- **décision** · `plugin_keep_list` : Quelle extension garder pour chaque fonction en double (action 14)
- **accès** · `staging_site` : Un site de test (copie) pour essayer les désactivations avant la production (action 14)
- **décision** · `real_phone` : Le numéro de téléphone à afficher (actions 15, 17)
- **accès** · `server_config_access` : Accès à la configuration du serveur ou du CDN (action 16)

## Cette semaine : gains rapides

### - [ ] 1. Deux prix différents pour la formule complète (29 € et 39 €) (F1)

`Critique` · Copywriting · **Responsable** : Propriétaire du site · Effort faible · Impact élevé

**Objectif** : Décider du vrai prix et l'écrire à l'identique sur l'accueil, les formules et le paiement.

**Pourquoi** : L'accueil annonce la formule complète à 29 € par mois, mais la page des formules et la page de paiement affichent 39 € par mois. Un visiteur qui clique sur 'Choisir' voit un prix supérieur de 10 € à celui qui l'a attiré : c'est un risque d'abandon et de confiance, au moment même où la conversion se joue. Le script de cohérence relève ce conflit : il propose les deux passages, le jugement reste humain.

**À faire**

1. Confirmer le prix mensuel réel de la formule complète (29 € ou 39 €) et s'il est TTC.
2. Corriger la phrase de l'accueil 'formule complète à 29 € par mois' ou le bloc 'Complet' de /formules/ et la ligne de /paiement/, selon la décision.
3. Chercher dans le blog, les e-mails de bienvenue et les pages internes toute autre mention de 29 € ou 39 €.
4. Ajouter la mention 'TTC' derrière chaque prix.

**Comment vérifier** : Rouvrir l'accueil, /formules/ et /paiement/ : le même montant, avec la même mention TTC, est affiché partout; relancer consistency.py : 0 conflit de prix.

**Exécution** : à faire par un humain · risque moyen
**Il faut** : `real_price` (décision)
**Retour arrière** : Remettre l'ancien texte depuis l'historique de révisions de la page WordPress.

**Pages** : /, /formules/, /paiement/

### - [ ] 2. Le bouton 'Rejoindre' de l'en-tête contient un gabarit non remplacé (F3)

`Élevée` · Conversion (CRO) · **Responsable** : Développeur ou agence web · Effort faible · Impact élevé

**Objectif** : Remplacer le gabarit par une valeur réelle ou retirer le paramètre.

**Pourquoi** : Le bouton principal de l'en-tête, présent sur les 16 pages, pointe vers /communaute-gratuite/?ref={source} : le texte {source} n'est jamais remplacé. La page s'ouvre quand même, mais la mesure de provenance des inscrits est faussée et le paramètre pollue l'adresse.

**À faire**

1. Ouvrir le fichier d'en-tête du thème (header.php) ou le menu WordPress qui contient le lien 'Rejoindre'.
2. Remplacer href="/communaute-gratuite/?ref={source}" par href="/communaute-gratuite/" si le suivi de provenance n'est pas utilisé.
3. Si le suivi est voulu, générer la valeur par page (par exemple ?ref=header) et la lire dans l'outil de mesure.

**Comment vérifier** : curl sur /formules/ : le lien 'Rejoindre' ne contient plus '{source}'.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : `ref_tracking_choice` (décision)

**Pages** : toutes les pages (en-tête)

### - [ ] 3. 15 pages sur 16 déclarent la page d'accueil comme canonique (F4)

`Élevée` · SEO · **Responsable** : Développeur ou agence web · Effort faible · Impact élevé

**Objectif** : Faire que chaque page déclare sa propre adresse comme canonique.

**Pourquoi** : Chaque page autre que l'accueil porte une balise canonique vers http://127.0.0.1:18940/. Google peut donc ignorer /formules/, /communaute-gratuite/ et les articles du blog au profit de l'accueil : ces pages risquent de ne jamais apparaître dans les résultats. Trois extensions SEO sont actives en même temps, ce qui peut expliquer la balise.

**À faire**

1. Ne garder qu'une seule extension SEO active (voir F13) et ouvrir ses réglages de balise canonique.
2. Désactiver toute règle qui force la canonique vers l'accueil, ou la remplacer par l'adresse de la page courante.
3. Vider le cache de page, puis contrôler les balises sur /formules/ et un article.

**Comment vérifier** : crawl.py : issue canonical_points_elsewhere à 0, et chaque page a canonical_is_self=true.

**Exécution** : l'agent prépare, quelqu'un applique · risque élevé
**Il faut** : `seo_plugin_choice` (décision)
**Retour arrière** : Réactiver l'extension SEO précédente et restaurer la sauvegarde de ses réglages.

**Pages** : /communaute-gratuite/, /formules/, /blog/, /a-propos/, /contact/, /blog/article-1/ à article-6

### - [ ] 4. L'image d'en-tête de 2,1 Mo rend le chargement très lent en simulation mobile (F6)

`Élevée` · Rapidité · **Responsable** : Rédaction ou contenu · Effort faible · Impact élevé

**Objectif** : Remplacer hero.png par une image WebP ou AVIF d'environ 100 Ko, aux bonnes dimensions.

**Pourquoi** : En laboratoire Lighthouse (mobile simulé), le plus grand élément affiché met 15,8 s et le score performance est 64/100. L'élément en cause est hero.png, un PNG de 2,1 Mo, soit les trois quarts des 2,9 Mo de la page. Mesure de laboratoire en simulation, pas une mesure de visiteurs réels. Le test sans bridage (devtools) donne 80 ms, ce qui confirme que le coût vient du poids sur réseau mobile.

**À faire**

1. Récupérer l'image source de hero.png et l'exporter en WebP ou AVIF à 800 px de large pour mobile (cible : 150 Ko au plus).
2. La remplacer dans la médiathèque WordPress, ou via l'extension d'images (pixel-images) en activant la conversion.
3. Ajouter les attributs width, height et fetchpriority="high" sur cette image, sans lazy-load.
4. Ajouter un texte alternatif décrivant l'image (elle a aujourd'hui un alt vide).

**Comment vérifier** : Relancer lh_median.py : LCP médian sous 4 s en lab et poids total sous 1 Mo.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : `hero_source_image` (contenu à fournir)
**Retour arrière** : Remettre l'ancienne image depuis la médiathèque.

**Pages** : /

### - [ ] 6. Le code déclare le consentement analytique 'accordé' par défaut et le bandeau valide par la simple poursuite (F8)

`Élevée` · Tracking et consentement · **Responsable** : Développeur ou agence web · Effort faible · Impact moyen

**Objectif** : Passer le consentement par défaut à 'denied' et ne l'accorder qu'après un clic sur Tout accepter.

**Pourquoi** : Dans l'en-tête de chaque page, gtag('consent','default',{analytics_storage:'granted'}) accorde la mesure avant tout choix. Le bandeau affirme de plus 'En continuant, vous acceptez leur utilisation', formule qui ne vaut pas consentement. Au test réel, aucune requête de traceur ne part avant interaction (ce qui est bon), donc le risque dépend de ce que charge gtm-loader.js une fois en conditions réelles. Deux outils de consentement sont actifs (voir F13).

**À faire**

1. Dans le script d'en-tête (extension pixel-snippets ou pixel-consent), remplacer analytics_storage:'granted' par 'denied'.
2. Faire que le bouton Tout accepter appelle gtag('consent','update',{analytics_storage:'granted'}).
3. Réécrire la phrase du bandeau, par exemple : 'Nous mesurons l'audience uniquement si vous acceptez.' et retirer 'En continuant, vous acceptez'.
4. Ne garder qu'un seul outil de consentement actif.

**Comment vérifier** : Relancer devtools.py --after-refuse : aucun signal de consentement 'granted' avant clic, et aucune requête de traceur avant Tout accepter.

**Exécution** : l'agent prépare, quelqu'un applique · risque moyen
**Il faut** : `consent_rules` (décision)
**Retour arrière** : Restaurer l'ancien extrait de code depuis l'historique de l'extension de snippets.

**Pages** : toutes les pages

### - [ ] 8. Le bandeau de cookies couvre 43 % du premier écran mobile (F9)

`Moyenne` · UX et mobile · **Responsable** : Développeur ou agence web · Effort faible · Impact moyen

**Objectif** : Réduire le bandeau à une barre compacte en bas d'écran.

**Pourquoi** : Sur mobile, le bandeau noir masque le bas du titre et tout ce qui suit, y compris le bouton 'Commencer gratuitement' qui n'apparaît qu'en descendant. Le visiteur doit trancher le bandeau avant de voir l'offre.

**À faire**

1. Dans les réglages de l'extension de consentement, passer la présentation en barre basse compacte.
2. Raccourcir le texte à 2 lignes et garder les trois boutons sur une ligne.
3. Viser moins de 20 % de la hauteur d'écran sur mobile 390 px.

**Comment vérifier** : Rerun render.py : fixed_or_sticky sous 20 % et le bouton principal visible dans la première vue.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : rien de plus

**Pages** : toutes les pages

### - [ ] 9. Contrastes insuffisants et 13 zones tactiles trop petites (F10)

`Moyenne` · Accessibilité · **Responsable** : Développeur ou agence web · Effort faible · Impact moyen

**Objectif** : Foncer le vert des boutons et agrandir les zones tactiles à 44 px au moins.

**Pourquoi** : Lighthouse signale un contraste insuffisant (le texte blanc sur le vert clair des boutons en est un exemple visible) et des cibles tactiles trop petites ou trop serrées. Le rendu mobile en liste 13, dont les liens du menu qui se touchent. Le champ e-mail du formulaire est de plus un champ texte simple, sans type e-mail ni autocomplétion (voir aussi F11).

**À faire**

1. Foncer la couleur des boutons .cta et .btn (theme.css) jusqu'à un contraste d'au moins 4,5:1 avec le texte blanc.
2. Donner aux liens du menu un espacement vertical et une hauteur minimale de 44 px.
3. Relancer Lighthouse et vérifier les audits color-contrast et target-size.

**Comment vérifier** : lh_median.py : accessibilité à 100 et audits color-contrast et target-size réussis.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : rien de plus

**Pages** : toutes les pages

### - [ ] 10. Titres trop longs, descriptions manquantes ou génériques, et deux H1 sur l'accueil (F14)

`Moyenne` · SEO · **Responsable** : Marketing · Effort faible · Impact moyen

**Objectif** : Réécrire les titres et descriptions, garder un seul H1 par page et ajouter les alt et l'image de partage.

**Pourquoi** : 7 titres dépassent 65 caractères (l'accueil en compte 137) et seront coupés dans les résultats. 4 pages n'ont pas de description et 6 articles du blog utilisent la même phrase 'Un article du blog Cercle Pixel.'. L'accueil a deux H1 ('Apprends la retouche photo...' et 'Cercle Pixel'), et /espace-membres/ n'en a aucun. Aucune image Open Graph sur les 16 pages, et 3 images sans attribut alt (À propos, article 3). Une partie des titres d'articles est longue et un contient 'en 2025', déjà daté.

**À faire**

1. Raccourcir le titre de l'accueil à 60 caractères au plus, par exemple : 'Cercle Pixel | Communauté de retouche photo, atelier gratuit'.
2. Raccourcir les 6 titres d'articles à 60 caractères et retirer 'en 2025' du titre de l'article 4.
3. Écrire une description unique de 120 à 155 caractères pour chaque page et article.
4. Sur l'accueil, transformer le second H1 'Cercle Pixel' en paragraphe ou en logo.
5. Ajouter un texte alternatif aux 3 images (À propos, article 3) et une image Open Graph par défaut dans l'extension SEO.

**Comment vérifier** : crawl.py : title_too_long_over_65, missing_meta_description, multiple_h1, images_missing_alt et missing_og_image tous à 0.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : `og_image` (contenu à fournir)
**Retour arrière** : Restaurer les révisions précédentes des pages.

**Pages** : /, /blog/article-1/ à article-6, /a-propos/, /espace-membres/

### - [ ] 11. Le formulaire d'inscription gratuite est minimal mais mal typé et sans réassurance (F11)

`Moyenne` · Conversion (CRO) · **Responsable** : Développeur ou agence web · Effort faible · Impact moyen

**Objectif** : Typer les champs, ajouter l'autocomplétion et une ligne de réassurance sous le bouton.

**Pourquoi** : Le formulaire n'a que deux champs, ce qui est bien. Mais le champ e-mail est de type texte (le clavier mobile ne propose pas l'arobase), les champs s'appellent 'e' et 'p', sans autocomplétion, et rien ne dit ce qui se passe après l'envoi ni que la carte bancaire n'est pas demandée. Le formulaire n'a pas été envoyé (lecture seule).

**À faire**

1. Passer le champ e-mail en type="email" avec autocomplete="email" et le champ prénom avec autocomplete="given-name".
2. Ajouter sous le bouton : 'Gratuit, sans carte bancaire. Tu reçois ton premier atelier par e-mail.' (à confirmer par le propriétaire).
3. Remplacer le libellé 'Je m'inscris' par 'Rejoindre gratuitement' pour garder le même mot que le menu.

**Comment vérifier** : Sur un téléphone, le clavier e-mail s'affiche sur le premier champ; la ligne de réassurance est visible sous le bouton sans défiler.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : `signup_promise` (information)

**Pages** : /communaute-gratuite/

### - [ ] 12. La section 'Ils en parlent' n'affiche aucune preuve (F12)

`Moyenne` · Conversion (CRO) · **Responsable** : Rédaction ou contenu · Effort faible · Impact moyen

**Objectif** : Ajouter deux vrais témoignages signés et un chiffre daté dans la section.

**Pourquoi** : Sur l'accueil, la section 'Ils en parlent' ne contient qu'une phrase générale ('Des membres de toute la francophonie progressent chaque mois') : ni témoignage, ni nom, ni résultat. L'affirmation 'Plus de 1 200 membres' n'est pas sourcée. La page entière ne fait que 129 mots rendus.

**À faire**

1. Choisir deux membres prêts à être cités, avec prénom, ville et résultat concret (par exemple un avant/après).
2. Écrire sous 'Ils en parlent' deux citations de 20 à 30 mots, avec photo et prénom.
3. Dater le chiffre '1 200 membres' ou le mettre à jour (par exemple 'au 1er novembre 2026').

**Comment vérifier** : Ouvrir l'accueil sur téléphone : au moins deux citations signées sont visibles dans la section.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : `real_testimonials` (contenu à fournir)

**Pages** : /

## Ce mois-ci

### - [ ] 5. La page de paiement n'offre aucun moyen de payer et la formule gratuite n'a pas de bouton (F2)

`Critique` · Conversion (CRO) · **Responsable** : Développeur ou agence web · Effort moyen · Impact élevé

**Objectif** : Ajouter un bouton à la formule gratuite et un vrai tunnel de paiement sur /paiement/.

**Pourquoi** : Sur /formules/, seule la carte 'Complet' a un bouton 'Choisir'; la carte 'Gratuit' n'en a aucun, alors que l'objectif numéro un est l'inscription gratuite. Le bouton 'Choisir' mène à /paiement/, qui ne contient qu'un titre et une phrase : ni formulaire, ni bouton de paiement, ni récapitulatif, ni réassurance. Le parcours gratuit puis payant s'arrête donc là. Aucune action de paiement n'a été tentée (lecture seule).

**À faire**

1. Dans le bloc 'Gratuit' de /formules/, ajouter le bouton 'Rejoindre gratuitement' vers /communaute-gratuite/.
2. Dans /paiement/, vérifier si le plugin boutique prévu (pixel-shop, actuellement inactif) doit afficher le formulaire; sinon intégrer le module de paiement.
3. Faire afficher sur la page de paiement : formule choisie, prix TTC, moyen de paiement, 'Satisfait ou remboursé sous 14 jours' et lien vers les mentions légales.
4. Tester un paiement de bout en bout en mode test du prestataire.

**Comment vérifier** : Sur mobile : /formules/ montre un bouton sur chaque carte, et /paiement/ affiche un formulaire utilisable; un paiement test aboutit.

**Exécution** : à faire par un humain · risque élevé
**Il faut** : `payment_provider` (décision), `real_price` (décision)
**Retour arrière** : Restaurer la sauvegarde du site faite avant la modification et désactiver le module de paiement.

**Pages** : /formules/, /paiement/

### - [ ] 7. Les adresses inexistantes répondent 200 et le sitemap contient une page 'n'existe pas' (F5)

`Élevée` · Technique et indexation · **Responsable** : Développeur ou agence web · Effort moyen · Impact moyen

**Objectif** : Faire renvoyer un vrai 404, retirer les pages mortes et non indexables du sitemap.

**Pourquoi** : Une adresse inventée renvoie un code 200 avec une page d'accueil allégée au lieu d'un 404 (soft 404). /sitemap_index.xml, /wp-sitemap.xml et /llms.txt renvoient eux aussi cette page HTML. Le sitemap liste /ancienne-page/ (titre 'Cercle Pixel', H1 'Cette page n'existe pas') ainsi que /espace-membres/, qui est en noindex.

**À faire**

1. Configurer le thème (modèle 404.php) ou l'extension de redirections pour envoyer l'en-tête HTTP 404 sur les adresses inconnues.
2. Supprimer /ancienne-page/ ou la rediriger en 301 vers la page de remplacement.
3. Régénérer le sitemap sans /ancienne-page/ ni /espace-membres/ (noindex).
4. Vérifier que /sitemap_index.xml et /llms.txt renvoient 404 s'ils n'existent pas.

**Comment vérifier** : curl -I http://127.0.0.1:18940/zzz-inconnue renvoie 404; le sitemap ne contient plus de page en noindex ni de page morte.

**Exécution** : l'agent prépare, quelqu'un applique · risque moyen
**Il faut** : `old_page_target` (décision)
**Retour arrière** : Restaurer le gabarit du thème et la liste de redirections depuis la sauvegarde.

**Pages** : /ancienne-page/, /espace-membres/, /sitemap_index.xml, /llms.txt

### - [ ] 13. 724 Ko de JavaScript inutilisé et aucune mise en cache (F7)

`Moyenne` · Rapidité · **Responsable** : Développeur ou agence web · Effort moyen · Impact moyen

**Objectif** : Retirer le script inutilisé, minifier le CSS et autoriser la mise en cache des fichiers statiques.

**Pourquoi** : Le fichier vendor-bundle.js (environ 724 Ko) est chargé sur chaque page alors que presque rien n'y sert, et le CSS fait 35 Ko non minifiés. Toutes les réponses portent Cache-Control: no-store : le navigateur retélécharge tout à chaque page, y compris l'image de 2,1 Mo. Trois extensions de cache sont actives (voir F13).

**À faire**

1. Identifier quelle extension ou quel thème charge /assets/vendor-bundle.js et le désactiver sur les pages où il ne sert pas.
2. Minifier theme.css (cible : moins de 5 Ko inutilisés).
3. Régler le serveur ou l'extension de cache pour envoyer Cache-Control: public, max-age=31536000, immutable sur /assets/*.
4. Garder une seule extension de cache active.

**Comment vérifier** : curl -I /assets/hero.png montre un max-age d'au moins 1 an; lh_median.py : poids total sous 1 Mo.

**Exécution** : l'agent prépare, quelqu'un applique · risque moyen
**Il faut** : `bundle_owner` (information)
**Retour arrière** : Réactiver le script et remettre l'ancien réglage de cache.

**Pages** : toutes les pages

### - [ ] 14. 29 extensions actives, dont des doublons (cache, SEO, sécurité, consentement) (F13)

`Moyenne` · Technique et indexation · **Responsable** : Développeur ou agence web · Effort moyen · Impact moyen

**Objectif** : Garder une extension par fonction et supprimer les autres, après sauvegarde.

**Pourquoi** : Pour un site de 16 pages, 29 extensions sont actives. Plusieurs fonctions sont assurées en double ou plus : 3 extensions de cache (pixel-cache, pixel-cache-15, pixel-cache-30), 4 de sécurité, 2 de SEO, 2 de consentement, 2 d'analytique, 2 de sauvegarde, 2 de redirections. Ces doublons expliquent probablement les canoniques erronées (F4), le cache désactivé (F7) et le consentement ambigu (F8), et élargissent la surface d'attaque. 2 autres extensions (pixel-shop, pixel-forms-19) sont installées mais inactives. La disponibilité de mises à jour n'est pas exposée par l'API : non vérifiée.

**À faire**

1. Faire une sauvegarde complète (base et fichiers) et vérifier qu'elle se restaure.
2. Pour chaque fonction en double (cache, SEO, sécurité, consentement, analytique, sauvegarde, redirections), choisir l'extension à garder.
3. Désactiver les doublons un par un sur un site de test, puis en production, en contrôlant l'accueil, le formulaire et le blog après chacun.
4. Supprimer les extensions inactives (pixel-forms-19) et réexaminer pixel-shop avant d'en décider (voir F2).

**Comment vérifier** : wp plugin list ou l'écran Extensions : une seule extension par fonction, et une réexécution de l'audit sans régression.

**Exécution** : l'agent prépare, quelqu'un applique · risque élevé
**Il faut** : `plugin_keep_list` (décision), `staging_site` (accès)
**Retour arrière** : Restaurer la sauvegarde complète et réactiver les extensions retirées.

**Pages** : tout le site

## Ensuite

### - [ ] 15. Deux numéros de téléphone différents et une année de copyright périmée (F15)

`Faible` · Copywriting · **Responsable** : Propriétaire du site · Effort faible · Impact faible

**Objectif** : Garder un seul numéro et rendre l'année du copyright automatique.

**Pourquoi** : Le numéro de téléphone du pied de page (présent sur toutes les pages) diffère du numéro de la page Contact, par le dernier chiffre. Le copyright affiche 2022 alors que nous sommes en 2026, ce qui donne une impression de site abandonné. La page à propos annonce une existence depuis 2019, ce qui reste cohérent.

**À faire**

1. Confirmer le bon numéro de téléphone parmi les deux affichés (pied de page et page Contact).
2. Corriger la page Contact ou le pied de page.
3. Remplacer '© 2022' par '© 2026' ou par une année générée automatiquement dans footer.php.

**Comment vérifier** : consistency.py : 0 problème de contact et 0 problème d'année.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : `real_phone` (décision)

**Pages** : /contact/, pied de page de toutes les pages

### - [ ] 16. En-têtes de sécurité absents et version du serveur divulguée (F16)

`Faible` · Sécurité · **Responsable** : Hébergeur ou CDN · Effort faible · Impact faible

**Objectif** : Ajouter les en-têtes de base côté serveur et masquer la version.

**Pourquoi** : Content-Security-Policy, X-Frame-Options, Referrer-Policy et Permissions-Policy sont absents, et l'en-tête Server indique 'nginx Python/3.14.7'. HSTS n'est pas évalué (site servi en HTTP local).

**À faire**

1. Ajouter dans la configuration du serveur : X-Frame-Options: SAMEORIGIN, Referrer-Policy: strict-origin-when-cross-origin, Permissions-Policy: camera=(), microphone=(), geolocation=().
2. Mettre en place une Content-Security-Policy d'abord en mode Report-Only, puis la durcir.
3. Masquer la version avec server_tokens off.

**Comment vérifier** : curl -I sur l'accueil montre les quatre en-têtes et un Server sans numéro de version.

**Exécution** : l'agent prépare, quelqu'un applique · risque moyen
**Il faut** : `server_config_access` (accès)
**Retour arrière** : Retirer les lignes ajoutées dans la configuration du serveur et le recharger.

**Pages** : tout le site

### - [ ] 17. Ni llms.txt, ni données structurées (F17)

`Faible` · Visibilité IA · **Responsable** : Marketing · Effort faible · Impact faible

**Objectif** : Ajouter un JSON-LD Organization et un court llms.txt.

**Pourquoi** : Il n'y a aucune donnée structurée (JSON-LD) : l'accueil ne se déclare ni comme organisation ni comme formation. /llms.txt renvoie une page HTML avec un code 200 au lieu d'un fichier texte (voir F5), et Lighthouse signale le fichier comme non conforme.

**À faire**

1. Ajouter dans l'extension SEO un bloc JSON-LD Organization (nom, logo, adresse de Lyon, téléphone confirmé).
2. Créer un /llms.txt en texte brut qui résume le site et liste les 5 pages clés (formules, communauté, blog, à propos, contact).

**Comment vérifier** : Le test des résultats enrichis de Google valide le bloc, et curl /llms.txt renvoie un texte brut et non du HTML.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : `real_phone` (décision)

**Pages** : /, /llms.txt

## Après les corrections

Relance l'audit sur les mêmes pages avec le même périmètre et compare : les constats corrigés doivent disparaître et les scores monter. Score avant : 73/100.
