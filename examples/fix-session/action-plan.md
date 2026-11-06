# Plan d'action : http://127.0.0.1:18931/

Basé sur l'audit du 2026-11-05. Score actuel : 87/100. 12 actions : 8 cette semaine, 2 ce mois-ci, 2 ensuite. Coche chaque case une fois la correction faite et vérifiée.

## Faire appliquer ce plan par l'agent

1. Dis : « applique le plan d'action ».
2. L'agent traite les actions par ordre de priorité (le numéro devant chaque action).
3. Il ne commence une action que s'il a tout ce qu'il lui faut. Sinon il te demande le complément, avec la liste ci-dessous.
4. Pour chaque action prête, il te montre ce qu'il va changer, le risque et le retour arrière, et attend ton GO. Rien n'est appliqué sans GO.
5. Après chaque action, il vérifie le résultat avec « Comment vérifier » puis coche la case.

## Ce que l'agent doit recevoir de toi

Pour appliquer le plan, l'agent a besoin de ces éléments. Il les demande en une fois avant d'agir, et jamais en cours de route.

- **accès** · `acces_fichiers_site` : Accès en écriture aux fichiers HTML du site dans <work-folder>/site (déjà déclaré) (actions 1, 2, 4, 5, 6, 8, 11)
- **décision** · `champs_devis` : Quels champs du formulaire sont indispensables pour chiffrer un devis (garder ou supprimer Entreprise et Budget) (actions 2)
- **contenu à fournir** · `photos_portfolio` : 6 photos de réalisations avec autorisation de publication (actions 3)
- **contenu à fournir** · `avis_clients` : 2 ou 3 avis réels de clients avec prénom et accord de publication (l'agent n'en invente jamais) (actions 3)
- **décision** · `decision_noindex_about` : La page À propos doit-elle être indexée par Google (oui ou non) ? (actions 5)
- **information** · `url_publique` : L'adresse publique définitive du site (domaine) pour le canonical et le sitemap (actions 6)
- **contenu à fournir** · `photo_hero` : Une vraie photo de présentation (fichier image) que le studio a le droit de publier (actions 7, 11)
- **décision** · `service_formulaire` : Le service ou le script serveur qui recevra les demandes, et l'adresse email du studio qui les reçoit (actions 9)
- **accès** · `acces_boite_test` : Une personne qui peut soumettre un test et confirmer la réception (l'agent ne soumet jamais de formulaire) (actions 9)
- **décision** · `ton_je_nous` : Le studio parle-t-il à la première personne du singulier (je) ou du pluriel (nous) ? (actions 10)
- **information** · `prix_entreprise` : Un prix de départ réel pour la prestation Entreprise, ou la décision de ne pas en afficher (actions 10)
- **information** · `coordonnees_studio` : Téléphone, email public et, si souhaité, adresse du studio à publier (actions 11)

## Cette semaine : gains rapides

### - [x] 1. Le bouton principal de l'accueil est un lien « Cliquez ici » sous la ligne de flottaison (F1)

`Élevée` · Conversion (CRO) · **Responsable** : Développeur ou agence web · Effort faible · Impact élevé

**Objectif** : Remplacer le lien par un vrai bouton « Demander un devis gratuit » visible dès le premier écran mobile.

**Pourquoi** : Sur mobile, l'unique appel au devis de l'accueil est un simple lien bleu « Cliquez ici », placé à 829 px sur une page de 1 420 px, après un grand espace vide. Il ne dit pas ce qu'on obtient et n'a pas l'aspect d'un bouton, alors que la classe de bouton existe déjà dans le CSS.

**À faire**

1. Ouvrir index.html et repérer <a href="contact.html">Cliquez ici</a>.
2. Le remplacer par <a class="btn" href="contact.html">Demander un devis gratuit</a> (la classe btn existe déjà dans le <style>).
3. Déplacer ce bouton juste sous le second titre, avant le premier paragraphe, pour qu'il soit visible sans défilement sur un écran de 390 x 844 px.
4. Ajouter sous le bouton une ligne de réassurance : « Réponse sous 48 heures, sans engagement ».

**Comment vérifier** : Rerun render.py sur l'accueil : dans rendered.json le bouton a top inférieur à 700 et h d'au moins 44 ; sur mobile-01.png le bouton est visible sans défilement.

**Exécution** : l'agent applique après ton GO · risque moyen
**Il faut** : `acces_fichiers_site` (accès)
**Retour arrière** : Copier index.html en index.html.bak avant modification ; pour annuler, remettre la copie.

**Pages** : /, /index.html

### - [x] 2. Formulaire de devis : 8 champs, aucun obligatoire, aucun type adapté (F2)

`Élevée` · Conversion (CRO) · **Responsable** : Développeur ou agence web · Effort faible · Impact élevé

**Objectif** : Réduire le formulaire à l'essentiel, rendre email obligatoire, utiliser les bons types de champs et un bouton explicite.

**Pourquoi** : Le formulaire demande nom, email, téléphone, entreprise, date, lieu, budget et message, sans aucun champ marqué obligatoire. Une demande sans email valide peut être envoyée, le téléphone et la date sont des champs texte libres (pas de clavier adapté sur mobile), et rien n'indique le délai de réponse sur la page. Le bouton se contente de « Envoyer ».

**À faire**

1. Dans contact.html, ajouter required et autocomplete="email" au champ email, et required au champ nom.
2. Passer le champ téléphone en type="tel" autocomplete="tel" et le champ date en type="date".
3. Rendre « Entreprise » et « Budget » facultatifs en l'indiquant dans le label (« Entreprise (facultatif) ») ; envisager de supprimer « Budget » si le propriétaire n'en a pas besoin pour chiffrer.
4. Remplacer le texte du bouton par « Recevoir mon devis gratuit » et ajouter au-dessus « Réponse sous 48 heures. »

**Comment vérifier** : Ouvrir contact.html sur mobile : envoyer le formulaire vide est refusé par le navigateur sur nom et email, et le clavier téléphonique s'affiche sur le champ téléphone. Relire le HTML : required présent sur 2 champs au moins.

**Exécution** : l'agent applique après ton GO · risque moyen
**Il faut** : `acces_fichiers_site` (accès), `champs_devis` (décision)
**Retour arrière** : Copier contact.html en contact.html.bak avant modification ; pour annuler, remettre la copie.

**Pages** : /contact.html

### - [x] 4. Titre de 125 caractères répété sur l'accueil et Prestations (F4)

`Moyenne` · SEO · **Responsable** : Développeur ou agence web · Effort faible · Impact moyen

**Objectif** : Donner à chaque page un titre unique de 60 caractères ou moins.

**Pourquoi** : L'accueil, index.html et la page Prestations ont le même titre de 125 caractères, bourré de mots-clés, qui sera coupé dans Google. Les deux pages se concurrencent et la page Prestations n'est pas identifiable.

**À faire**

1. Dans index.html, remplacer le <title> par « Studio Zorbul | Photographe à Lyon : portrait, mariage, entreprise » (moins de 65 caractères).
2. Dans services.html, le remplacer par « Prestations et tarifs photo à Lyon | Studio Zorbul ».
3. Vérifier que chaque titre fait 60 caractères ou moins et reste unique.

**Comment vérifier** : Rerun crawl.py : title_too_long_over_65 et duplicate_titles ne sont plus dans issue counts.

**Exécution** : l'agent applique après ton GO · risque moyen
**Il faut** : `acces_fichiers_site` (accès)
**Retour arrière** : Copier index.html et services.html en .bak avant modification ; remettre les copies pour annuler.

**Pages** : /, /services.html

### - [x] 5. Page À propos exclue de Google (noindex) et sans titre H1 (F5)

`Moyenne` · SEO · **Responsable** : Propriétaire du site · Effort faible · Impact moyen

**Objectif** : Confirmer si la page doit être indexée, puis retirer le noindex, ajouter un H1 et un contenu de confiance.

**Pourquoi** : about.html porte <meta name="robots" content="noindex">, donc Google ne l'affichera pas, alors que c'est la page de confiance qui présente la photographe. Elle n'a aucun H1 et seulement 26 mots. La suppression du noindex est une décision de propriétaire : il peut être voulu.

**À faire**

1. Confirmer si la page À propos doit apparaître dans Google.
2. Si oui, supprimer <meta name="robots" content="noindex"> dans about.html.
3. Ajouter <h1>À propos du Studio Zorbul</h1> en haut de page.
4. Ajouter une photo de Camille et 2 ou 3 phrases de preuve (nombre de séances, type de clients) ; voir F9.

**Comment vérifier** : curl http://127.0.0.1:18931/about.html ne contient plus « noindex » et rerun crawl.py : noindex_pages absent, missing_h1 réduit d'une page.

**Exécution** : l'agent applique après ton GO · risque élevé
**Il faut** : `acces_fichiers_site` (accès), `decision_noindex_about` (décision)
**Retour arrière** : Copier about.html en about.html.bak ; pour annuler, remettre la copie (règle d'indexation : à surveiller).

**Pages** : /about.html

### - [x] 6. Deux H1 sur l'accueil, pas de description, pas de canonical ni de sitemap (F6)

`Moyenne` · SEO · **Responsable** : Développeur ou agence web · Effort faible · Impact moyen

**Objectif** : Un seul H1, une description, un canonical, un sitemap, pour que l'accueil se présente bien dans les résultats.

**Pourquoi** : L'accueil a deux H1 (« Studio Zorbul » et « Photographe à Lyon »), pas de meta description ni de canonical, et il existe aussi en double sous /index.html. Le site n'a pas de sitemap.xml. Lighthouse SEO : 83 sur 100.

**À faire**

1. Dans index.html, fusionner les titres en <h1>Studio Zorbul, photographe à Lyon</h1>.
2. Ajouter <meta name="description" content="Photographe à Lyon : portraits, mariages et événements d'entreprise. Demandez votre devis gratuit, réponse sous 48 heures."> (moins de 160 caractères).
3. Ajouter <link rel="canonical" href="http://127.0.0.1:18931/"> ; adapter l'adresse au domaine réel en ligne.
4. Créer sitemap.xml à la racine avec les pages indexables et ajouter la ligne Sitemap: dans robots.txt.

**Comment vérifier** : Rerun crawl.py : missing_meta_description, multiple_h1 et canonical_missing disparaissent pour l'accueil ; curl /sitemap.xml renvoie 200.

**Exécution** : l'agent applique après ton GO · risque moyen
**Il faut** : `acces_fichiers_site` (accès), `url_publique` (information)
**Retour arrière** : Copier index.html et robots.txt en .bak avant modification ; supprimer sitemap.xml pour annuler.

**Pages** : /, /index.html

### - [ ] 7. Image d'accueil sans texte alternatif, très petite, et page sans zone principale (F7)

`Moyenne` · Accessibilité · **Responsable** : Rédaction ou contenu · Effort faible · Impact moyen

**Objectif** : Mettre une vraie photo avec un alt descriptif, entourer le contenu d'une balise main.

**Pourquoi** : L'image hero.jpg n'a pas d'attribut alt et ne pèse que 134 octets pour une zone de 640 x 360 px : elle ressemble à un fichier vide ou de remplacement, et laisse un grand vide blanc sur mobile (voir capture). Lighthouse relève aussi l'absence de balise main, une erreur dans la console et une image de trop faible résolution. Accessibilité Lighthouse : 83 sur 100.

**À faire**

1. Remplacer hero.jpg par une vraie photo du studio ou d'une séance, d'au moins 1 280 px de large, en JPEG ou WebP léger (moins de 200 Ko).
2. Ajouter alt="Séance portrait en studio à Lyon" (adapter à la photo réelle) sur la balise img.
3. Envelopper le contenu de index.html dans <main> ... </main>.
4. Ajouter les attributs width et height déjà présents et max-width:100%;height:auto dans le style.

**Comment vérifier** : Rerun lh_median.py : accessibility à 95 ou plus, les audits image-alt et landmark-one-main ne sont plus en échec ; mobile-01.png montre une photo à la place du vide.

**Exécution** : l'agent prépare, quelqu'un applique · risque moyen
**Il faut** : `photo_hero` (contenu à fournir)
**Retour arrière** : Garder l'ancien hero.jpg et index.html en .bak ; les remettre pour annuler.

**Pages** : /, /index.html

### - [x] 8. Liens de navigation trop petits et sans menu commun (F8)

`Moyenne` · UX et mobile · **Responsable** : Développeur ou agence web · Effort faible · Impact moyen

**Objectif** : Ajouter un petit menu en haut de chaque page, avec des liens d'au moins 44 px de haut.

**Pourquoi** : Sur mobile, les 3 liens de l'accueil mesurent 17 px de haut (cible minimale recommandée : 44 px, 24 px au strict minimum). « Nos prestations » et « À propos » sont collés sur une même ligne en bas de page, et il n'y a pas de menu : les pages Contact et À propos ne proposent qu'un retour à l'accueil. Aucun lien vers Contact depuis À propos.

**À faire**

1. Ajouter en haut de chaque page un <nav> avec Prestations, À propos et un lien « Devis » vers contact.html.
2. Ajouter dans le style : nav a{display:inline-block;padding:.8rem 1rem} pour atteindre 44 px de haut.
3. Reprendre le même bloc nav sur les 5 fichiers HTML.

**Comment vérifier** : Rerun render.py : small_tap_targets égal à 0 sur l'accueil ; chaque page propose un lien vers Contact.

**Exécution** : l'agent applique après ton GO · risque moyen
**Il faut** : `acces_fichiers_site` (accès)
**Retour arrière** : Copier chaque fichier HTML en .bak avant modification ; remettre les copies pour annuler.

**Pages** : /, /services.html, /about.html, /contact.html

### - [ ] 10. Accroche sans bénéfice et page Prestations sans prix d'entreprise (F10)

`Faible` · Copywriting · **Responsable** : Marketing · Effort faible · Impact moyen

**Objectif** : Écrire une accroche orientée résultat, harmoniser « nous » ou « je », et indiquer un ordre de prix pour l'entreprise.

**Pourquoi** : Le titre « Studio Zorbul / Photographe à Lyon » décrit le métier mais ne dit pas ce que le visiteur obtient ni ce qu'il doit faire. Le paragraphe est long (3 lignes de texte compact) et commence par « Nous » alors que la page À propos parle de « Je » (une personne) : le ton est incohérent. La prestation Entreprise n'a pas de prix de départ, contrairement aux deux autres.

**À faire**

1. Remplacer le second titre par une phrase de bénéfice, par exemple « Des photos qui vous ressemblent, livrées sous 10 jours ».
2. Choisir « je » (Camille) ou « nous » et l'appliquer sur les 3 pages.
3. Dans services.html, ajouter à Entreprise « à partir de X euros » avec le vrai tarif, ou « sur devis selon le nombre de personnes ».

**Comment vérifier** : Relire l'accueil en 5 secondes sur mobile : une personne extérieure peut dire ce que propose le studio, pour qui et à quel délai.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : `ton_je_nous` (décision), `prix_entreprise` (information)

**Pages** : /, /services.html, /about.html

## Ce mois-ci

### - [ ] 3. Aucune preuve : pas de photo, avis, nom de client ni réalisation (F9)

`Élevée` · Copywriting · **Responsable** : Rédaction ou contenu · Effort moyen · Impact élevé

**Objectif** : Ajouter un petit portfolio et 2 ou 3 avis vérifiables, avec prénom, sur l'accueil et sous le formulaire.

**Pourquoi** : Un site de photographe qui ne montre aucune photo (l'image d'accueil est vide), aucun avis et aucun client cité demande au visiteur de faire confiance sans preuve. La page À propos tient en 2 phrases. Les 5 pages ne contiennent ni témoignage, ni portfolio, ni logo.

**À faire**

1. Choisir 6 photos représentatives (portrait, mariage, entreprise) que les personnes photographiées ont autorisé à publier.
2. Demander à 2 ou 3 clients un avis court avec prénom et autorisation de publication.
3. Ajouter sur l'accueil, sous le bouton, une section « Quelques séances » avec les photos (alt renseigné) et une section « Ils nous ont fait confiance » avec les avis.
4. Sur about.html, ajouter une photo de Camille, le nombre de séances réalisées et la durée d'expérience réelle.

**Comment vérifier** : Ouvrir l'accueil sur mobile : au moins 3 photos et 2 avis nommés sont visibles en moins de 3 écrans ; render.py montre plus de 200 mots rendus.

**Exécution** : l'agent prépare, quelqu'un applique · risque faible
**Il faut** : `photos_portfolio` (contenu à fournir), `avis_clients` (contenu à fournir)

**Pages** : /, /about.html, /contact.html

### - [ ] 9. Le formulaire envoie vers /devis, une cible non vérifiée sur un serveur de fichiers statiques (F3)

`Élevée` · Technique et indexation · **Responsable** : Propriétaire du site · Effort moyen · Impact élevé

**Objectif** : Vérifier qu'une demande de test arrive bien, et sinon brancher le formulaire sur un service qui la transmet par email.

**Pourquoi** : Le formulaire envoie en POST vers /devis. Le site est servi par un serveur de fichiers statiques (SimpleHTTP) et aucun fichier devis n'apparaît dans l'exploration : rien ne prouve qu'une demande soit reçue. Je n'ai pas soumis le formulaire (audit en lecture seule), c'est donc à tester par le propriétaire.

**À faire**

1. Envoyer une demande de test depuis contact.html avec un faux nom et vérifier qu'elle arrive dans la boîte du studio.
2. Si rien n'arrive, choisir un service de réception de formulaires (ou un script serveur) et obtenir son URL.
3. Remplacer action="/devis" par cette URL dans contact.html.
4. Ajouter une page de confirmation « Merci, réponse sous 48 heures » et la déclarer comme redirection du service.

**Comment vérifier** : Refaire une demande de test : un email arrive en moins de 5 minutes et la personne voit une page de confirmation.

**Exécution** : l'agent prépare, quelqu'un applique · risque élevé
**Il faut** : `service_formulaire` (décision), `acces_boite_test` (accès)
**Retour arrière** : Garder l'ancienne valeur de action notée avant modification ; la remettre pour annuler.

**Pages** : /contact.html

## Ensuite

### - [ ] 11. Pas de partage social, pas de données structurées locales (F11)

`Faible` · SEO · **Responsable** : Développeur ou agence web · Effort faible · Impact faible

**Objectif** : Ajouter les balises Open Graph et un bloc JSON-LD de type entreprise locale.

**Pourquoi** : Aucune des 5 pages n'a d'image de partage (Open Graph), aucune donnée structurée n'existe, alors que le studio est une entreprise locale à Lyon (adresse, téléphone et horaires sont absents du site).

**À faire**

1. Ajouter og:title, og:description, og:image et og:url dans le <head> de chaque page.
2. Ajouter un bloc <script type="application/ld+json"> de type Photographer avec nom, ville, zone desservie, téléphone et adresse email réels.
3. Ajouter une ligne de contact (email ou téléphone cliquable) sur l'accueil et sur contact.html.

**Comment vérifier** : Rerun crawl.py : missing_og_image à 0 ; facts.json : jsonld_types contient Photographer et tel_mailto_links est supérieur à 0.

**Exécution** : l'agent applique après ton GO · risque faible
**Il faut** : `acces_fichiers_site` (accès), `coordonnees_studio` (information), `photo_hero` (contenu à fournir)
**Retour arrière** : Copier les fichiers HTML en .bak avant modification ; remettre les copies pour annuler.

**Pages** : /

### - [ ] 12. Aucun en-tête de sécurité renvoyé par le serveur (F12)

`Faible` · Sécurité · **Responsable** : Hébergeur ou CDN · Effort élevé · Impact faible

**Objectif** : Au moment de la mise en ligne, configurer ces en-têtes sur le serveur ou l'hébergeur.

**Pourquoi** : Les réponses n'ont aucun en-tête CSP, X-Content-Type-Options, Referrer-Policy ni Permissions-Policy, et le serveur affiche sa version. Ces en-têtes se règlent côté serveur, pas dans les fichiers HTML ; l'absence de HTTPS et de CDN n'est pas comptée, comme demandé (site de test local).

**À faire**

1. Au déploiement, ouvrir la configuration du serveur ou de l'hébergeur (règles d'en-têtes).
2. Ajouter X-Content-Type-Options: nosniff et Referrer-Policy: strict-origin-when-cross-origin.
3. Ajouter une Content-Security-Policy de type default-src 'self' (le site n'utilise aucune ressource externe).
4. Masquer l'en-tête Server si l'hébergeur le permet.

**Comment vérifier** : curl -I sur la page : les 3 en-têtes ajoutés apparaissent dans la réponse.

**Exécution** : à faire par un humain · risque élevé
**Il faut** : `acces_serveur` (accès)
**Retour arrière** : Retirer la règle d'en-tête ajoutée dans la configuration du serveur.

**Pages** : /

## Après les corrections

Relance l'audit sur les mêmes pages avec le même périmètre et compare : les constats corrigés doivent disparaître et les scores monter. Score avant : 87/100.
