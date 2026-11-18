/** Les règles SEO du site, en un seul endroit, testées (lib/seo.test.ts) et vérifiées après chaque construction
 *  (scripts/verifier-seo.mjs). Même principe que comparetelecom. */

export const LANGUE = "fr-FR";
export const NOM_SITE = "Verifac";

/** Le suffixe ajouté par le gabarit des titres (app/layout.tsx : « %s, Verifac »). */
export const SUFFIXE_TITRE = `, ${NOM_SITE}`;
export const TITRE_MAX = 60;
export const DESCRIPTION_MIN = 70;
export const DESCRIPTION_MAX = 160;

/** Coupe un texte trop long sur un mot entier, avec des points de suspension. */
function couper(texte: string, maximum: number): string {
  if (texte.length <= maximum) return texte;
  return `${texte.slice(0, maximum - 1).replace(/[\s,;:–-]+\S*$/, "")}…`;
}

/** Le premier titre qui tient en 60 caractères avec « , Verifac » ; à défaut, le premier, coupé. */
export function titre(...candidats: string[]): string {
  const place = TITRE_MAX - SUFFIXE_TITRE.length;
  return candidats.find((c) => c.length <= place) ?? couper(candidats[0], place);
}

/** La première description entre 70 et 160 caractères ; à défaut, la première, coupée. */
export function description(...candidats: string[]): string {
  return candidats.find((c) => c.length >= DESCRIPTION_MIN && c.length <= DESCRIPTION_MAX) ?? couper(candidats[0], DESCRIPTION_MAX);
}

/** Canonique et langue d'une page. À passer tel quel dans `alternates` : la fusion des métadonnées est
 *  superficielle, une page qui écrit sa propre canonique efface celle de la mise en page. */
export function alternatives(chemin: string) {
  return { canonical: chemin, languages: { [LANGUE]: chemin, "x-default": chemin } };
}
