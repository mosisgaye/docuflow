# Stratégie SEO du site vitrine de Verifac

Le site vitrine (`site/`, Next.js 16) vit sur **verifac.company**. Le tableau de bord est sur
**app.verifac.company**, la démo sur **demo.verifac.company**. Ce document dit ce qui est en place,
où cela se trouve dans le code, et ce qui reste à faire. Mis à jour le 18 novembre 2026.

## 1. Les principes

- **Une page par intention de recherche, mesurée.** Les mots-clés et leur page sont dans
  [`mots-cles.csv`](mots-cles.csv) (OpenSEO, France, novembre 2026). Les recherches « produit » pures
  (« logiciel factures fournisseurs », 10 par mois) n'ont presque pas de volume : le trafic vient des
  outils, des guides et du glossaire, qui renvoient vers le produit.
- **Aucun texte de remplissage.** L'IA aide à rédiger, mais chaque page est relue, et chaque
  affirmation sur le produit est vérifiée dans le code du moteur (`moteur/controles.py`,
  `moteur/catalogue_circuit.py`…). Un fait qu'on ne peut pas vérifier ne s'écrit pas.
- **Rien de faux dans les données structurées** : pas de note inventée, pas de téléphone fictif,
  pas de témoignage tant qu'il n'y en a pas de vrai. Elles décrivent seulement ce que la page affiche.
- **Pas de prix affiché** : « mise en place et forfait mensuel, chiffrés selon votre volume ».

## 2. SEO technique (en place)

| Règle | Où |
| --- | --- |
| Titre ≤ 60 caractères avec « , Verifac », description 70-160 | `lib/seo.ts` : `titre()`, `description()` |
| Canonique et langue (`fr-FR`, `x-default`) sur chaque page | `lib/seo.ts` : `alternatives()` |
| Tests des règles et des contenus (articles, guides, glossaire) | `lib/seo.test.ts`, `npm test` |
| **Vérification de chaque page après la construction** : titre, description, un seul h1, canonique, langue, JSON-LD valide, texte alternatif des images, liens internes. Une faute fait échouer `npm run build`, donc le déploiement Vercel. | `scripts/verifier-seo.mjs` (script `postbuild`) |
| Plan du site, dates réelles | `app/sitemap.ts` |
| `robots.txt` (tout permis sauf `/api/`) | `app/robots.ts` |
| Une seule adresse : www, `verifac-site.vercel.app` → verifac.company (308) | `next.config.ts`, `redirects()` |
| Anciennes adresses du tableau de bord (`/?connexion=`, `/connexion`) → app.verifac.company | `next.config.ts` |
| IndexNow (Bing, Yandex…) | `app/indexnow/[cle]/route.ts`, `scripts/indexnow.mjs` |
| Flux RSS des ressources, annoncé dans l'en-tête | `app/ressources/rss.xml/route.ts` |
| `llms.txt` pour les assistants IA | `app/llms.txt/route.ts` |
| Page 404 ; adresse inconnue d'article, de guide ou de terme → 404 | `app/not-found.tsx`, `dynamicParams = false` |
| Image de partage, icône, icône iPhone | `app/opengraph-image.tsx`, `app/icon.svg`, `app/apple-icon.tsx` |
| Mesure d'audience et vitesse réelle, sans cookie ; conversions (pilote, démo, connexion) | `app/layout.tsx`, `app/composants/Conversions.tsx` |

**Vitesse mesurée** (Lighthouse par OpenSEO, aperçu Vercel, 18/11/2026) : performance 99 sur mobile et
100 sur ordinateur, LCP 1,3 à 2,1 s sur mobile, CLS 0. Le CSS en ligne de Next a été essayé et retiré :
il dégradait le LCP (texte affiché avant la police, puis déplacé).

## 3. SEO de la page

- Un seul h1, des sous-titres dans l'ordre (vérifié à chaque construction).
- **Données structurées** : `Organization` (avec le fondateur) et `WebSite` partout ;
  `SoftwareApplication` et `FAQPage` sur l'accueil ; `BreadcrumbList` sur toutes les pages
  intérieures ; `Article` sur les ressources ; `WebApplication` et `FAQPage` sur les outils ;
  `DefinedTermSet` et `DefinedTerm` sur le glossaire ; `ContactPage` ; `FAQPage` sur les fonctionnalités.
- Liens internes : fil d'Ariane, « À lire aussi », « Voir aussi » du glossaire, pied de page complet.

## 4. Les grappes de contenu

| Grappe | Pages | Ce qui les rend utiles |
| --- | --- | --- |
| Produit | accueil, fonctionnalités, démo, pilote | La description exacte de ce que fait Verifac |
| Outils | vérifier un IBAN, vérifier un numéro de TVA ou un SIRET | Le calcul est fait pour le visiteur, dans son navigateur |
| Ressources | facture électronique 2026, Factur-X, mentions obligatoires, faux RIB, dématérialisation, Odoo | Réponses précises, chiffres datés, liens vers les outils |
| Glossaire | 20 termes, une page chacun | Définition, ce qu'il faut vérifier sur une facture, exemples |
| Documentation | 6 guides d'utilisation | Pour les utilisateurs, et pour rassurer avant d'acheter |
| Confiance | à propos, contact, mentions légales, confidentialité | Qui est derrière, comment le joindre |

## 5. À faire

### À la mise en ligne
1. Poser `INDEXNOW_KEY` (`openssl rand -hex 16`) dans les variables du projet Vercel « verifac-site ».
2. Ajouter `www.verifac.company` au projet Vercel (la redirection est déjà dans le code).
3. **Google Search Console** : propriété de domaine verifac.company (enregistrement TXT dans le DNS
   Vercel), envoi de `https://verifac.company/sitemap.xml`. Donner l'accès au compte de service du
   MCP `gsc` pour suivre l'indexation depuis Claude.
4. **Bing Webmaster Tools** : importer la propriété depuis Search Console, puis lancer
   `INDEXNOW_KEY=… npm run indexnow` après chaque mise en ligne qui ajoute des pages.
5. Compléter les champs `[À COMPLÉTER]` (mentions légales, à propos) et relire tous les textes.

### Ensuite
- **Un article par semaine**, sur les recherches marquées « à faire » dans `mots-cles.csv`
  (fraude au président, IA et comptabilité, relance fournisseur), puis sur les nouvelles questions
  vues dans Search Console.
- **Pages de cas clients et témoignages**, seulement avec de vrais clients du pilote et leur accord.
- **Liens entrants** : une étude chiffrée (par exemple sur la fraude au faux RIB) à partir de données
  réelles du pilote, proposée à la presse spécialisée ; annuaires d'éditeurs de logiciels ; articles
  invités. Jamais de liens achetés.
- Un outil d'édition (CMS) le jour où le rythme de publication le demande.

## 6. Mesurer

| Quoi | Où |
| --- | --- |
| Pages indexées, erreurs d'exploration | Search Console, rapport Pages ; MCP `gsc` (`inspecter_url`) |
| Impressions, clics, position par requête | Search Console, rapport Performances |
| Vitesse réelle des visiteurs (LCP, INP, CLS) | Vercel Speed Insights, puis Search Console |
| Visites et conversions (`demande_pilote`, `essai_demo`, `connexion`) | Vercel Analytics |

Priorité d'amélioration : les pages qui ont des impressions mais peu de clics (revoir le titre et la
description), puis celles en position 8 à 20 (enrichir le contenu, ajouter des liens internes).

## Sources

- Google, guide de démarrage SEO : https://developers.google.com/search/docs/fundamentals/seo-starter-guide
- Google, contenu utile : https://developers.google.com/search/docs/fundamentals/creating-helpful-content
- Google, Core Web Vitals : https://developers.google.com/search/docs/appearance/core-web-vitals
- Next.js 16, métadonnées : `site/node_modules/next/dist/docs/01-app/01-getting-started/14-metadata-and-og-images.md`
- IndexNow : https://www.indexnow.org/documentation
