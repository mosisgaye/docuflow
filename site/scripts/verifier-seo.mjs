// Vérifie chaque page générée par `next build`, comme le ferait un audit SEO, et fait échouer la
// construction (donc le déploiement Vercel) si une règle n'est pas tenue. Lancé par `npm run build`
// (script postbuild). Mêmes limites que lib/seo.ts.
//
// Règles : titre ≤ 60 caractères, description 70-160, un seul h1, canonique = l'adresse de la page,
// langue fr-FR et x-default déclarées, données structurées JSON valides, images avec un texte alternatif,
// liens internes vers des pages qui existent.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const RACINE = ".next/server/app";
const SITE = "https://verifac.company";
const IGNOREES = new Set(["/_not-found", "/_global-error"]);
// Adresses servies hors de ce site (redirections, tableau de bord, moteur) : non vérifiées comme pages.
const HORS_SITE = /^\/(api\/|connexion$|ressources\/rss\.xml$|sitemap\.xml$|robots\.txt$|llms\.txt$|opengraph-image|icon|apple-icon)/;

const fichiers = (dossier) =>
  readdirSync(dossier).flatMap((nom) => {
    const chemin = join(dossier, nom);
    return statSync(chemin).isDirectory() ? fichiers(chemin) : chemin.endsWith(".html") ? [chemin] : [];
  });

const decoder = (texte) =>
  texte.replace(/&amp;/g, "&").replace(/&#x27;|&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">");
const premier = (html, motif) => decoder(html.match(motif)?.[1] ?? "");

const pages = new Map();
for (const fichier of fichiers(RACINE)) {
  const route = "/" + relative(RACINE, fichier).replace(/\.html$/, "").replace(/(^|\/)index$/, "");
  const chemin = route === "/" ? "/" : route.replace(/\/$/, "");
  if (!IGNOREES.has(chemin)) pages.set(chemin, readFileSync(fichier, "utf8"));
}

const problemes = [];
const liens = new Set();
for (const [chemin, html] of pages) {
  const alerte = (texte) => problemes.push(`${chemin} : ${texte}`);
  const titre = premier(html, /<title>([^<]*)<\/title>/);
  const description = premier(html, /<meta name="description" content="([^"]*)"/);
  const canonique = premier(html, /<link rel="canonical" href="([^"]*)"/);
  if (!titre || titre.length > 60) alerte(`titre de ${titre.length} caractères (60 au plus)`);
  if (description.length < 70 || description.length > 160) alerte(`description de ${description.length} caractères (70 à 160)`);
  const h1 = (html.match(/<h1[\s>]/g) ?? []).length;
  if (h1 !== 1) alerte(`${h1} titres h1 (1 attendu)`);
  if (canonique !== `${SITE}${chemin === "/" ? "" : chemin}`) alerte(`canonique « ${canonique} »`);
  if (!/hrefLang="fr-FR"/i.test(html) || !/hrefLang="x-default"/i.test(html)) alerte("langue fr-FR ou x-default non déclarée");
  for (const [, bloc] of html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)) {
    try {
      JSON.parse(bloc);
    } catch {
      alerte("données structurées JSON invalides");
    }
  }
  for (const [balise] of html.matchAll(/<img\b[^>]*>/g)) if (!/\balt="/.test(balise)) alerte("image sans texte alternatif");
  for (const [, href] of html.matchAll(/<a\b[^>]*href="(\/[^"#?]*)/g)) liens.add(href.replace(/\/$/, "") || "/");
}
for (const lien of liens) if (!pages.has(lien) && !HORS_SITE.test(lien)) problemes.push(`lien interne cassé : ${lien}`);

if (problemes.length) {
  console.error(`SEO : ${problemes.length} problème(s) sur ${pages.size} pages\n  ${problemes.join("\n  ")}`);
  process.exit(1);
}
console.log(`SEO : ${pages.size} pages vérifiées, ${liens.size} liens internes, aucun problème.`);
