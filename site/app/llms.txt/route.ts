import { ARTICLES } from "@/contenu/ressources";
import { GLOSSAIRE } from "@/contenu/glossaire";
import { GUIDES } from "@/contenu/guides";
import { SITE } from "@/contenu/site";

export const dynamic = "force-static";

/** llms.txt : le résumé du site pour les assistants IA (ChatGPT, Claude, Perplexity…). */
export function GET() {
  const lignes = [
    "# Verifac",
    "",
    `> ${SITE.description}`,
    "",
    "Verifac s’adresse aux PME françaises. Il reçoit les factures fournisseurs (mail, dépôt, API), les lit (Factur-X sans IA, PDF et scans avec), contrôle les calculs, le SIRET, la TVA, les doublons, le bon de commande et l’IBAN, les fait approuver par niveaux (comptable, directeur financier, gérant) par mail, puis les enregistre dans Odoo. Programme pilote : 5 places, deux mois offerts.",
    "",
    "## Produit",
    `- [Accueil](${SITE.adresse}/): présentation, contrôles, circuit d’approbation, programme pilote`,
    `- [Fonctionnalités](${SITE.adresse}/fonctionnalites): réception, lecture, contrôles, circuit d’approbation, Odoo, Claude, API`,
    `- [Démo en un clic](${SITE.demo}): fausses factures, remises à zéro chaque nuit`,
    `- [Contact](${SITE.adresse}/contact): ${SITE.support}`,
    "",
    "## Outils gratuits",
    `- [Vérifier un IBAN](${SITE.adresse}/outils/verifier-iban): format, longueur, clé de contrôle`,
    `- [Vérifier un numéro de TVA, SIREN ou SIRET](${SITE.adresse}/outils/verifier-numero-tva-intracommunautaire): clés, calcul du numéro de TVA`,
    "",
    "## Ressources",
    ...ARTICLES.map((a) => `- [${a.titre}](${SITE.adresse}/ressources/${a.slug}): ${a.description}`),
    "",
    "## Glossaire",
    ...GLOSSAIRE.map((t) => `- [${t.terme}](${SITE.adresse}/glossaire/${t.slug})`),
    "",
    `Flux RSS des ressources : ${SITE.adresse}/ressources/rss.xml`,
    "",
    "## Documentation",
    ...GUIDES.map((g) => `- [${g.titre}](${SITE.adresse}/documentation/${g.slug}): ${g.resume}`),
    "",
  ];
  return new Response(lignes.join("\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
