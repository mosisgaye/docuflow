import { SITE } from "@/contenu/site";

/** Les données structurées communes à tout le site. */
export const ORGANISATION = {
  "@type": "Organization",
  "@id": `${SITE.adresse}/#organisation`,
  name: "Verifac",
  url: SITE.adresse,
  logo: `${SITE.adresse}/logo/verifac-icone-512.png`,
  email: SITE.support,
  founder: { "@type": "Person", name: "Moussa Gaye" },
  contactPoint: { "@type": "ContactPoint", contactType: "customer support", email: SITE.support, availableLanguage: ["French"] },
};

export const SITE_WEB = {
  "@type": "WebSite",
  "@id": `${SITE.adresse}/#site`,
  name: "Verifac",
  url: SITE.adresse,
  inLanguage: "fr-FR",
  publisher: { "@id": `${SITE.adresse}/#organisation` },
};

export const LOGICIEL = {
  "@type": "SoftwareApplication",
  "@id": `${SITE.adresse}/#logiciel`,
  name: "Verifac",
  applicationCategory: "BusinessApplication",
  applicationSubCategory: "Traitement des factures fournisseurs",
  operatingSystem: "Web",
  inLanguage: "fr-FR",
  url: SITE.adresse,
  description: SITE.description,
  featureList: [
    "Lecture des factures PDF, scans, photos et Factur-X",
    "Détection des IBAN changés ou inconnus",
    "Détection des doublons et des erreurs de calcul",
    "Contrôle du SIRET et du numéro de TVA intracommunautaire",
    "Rapprochement avec les bons de commande Odoo",
    "Circuit d’approbation à plusieurs niveaux, par mail",
    "Connecteur Claude et API avec webhooks signés",
  ],
  publisher: { "@id": `${SITE.adresse}/#organisation` },
};

export const graphe = (...noeuds: Record<string, unknown>[]) => ({ "@context": "https://schema.org", "@graph": noeuds });

/** Fil d'Ariane : [libellé, chemin] du site à la page. */
export function filAriane(etapes: [string, string][]) {
  return {
    "@type": "BreadcrumbList",
    itemListElement: etapes.map(([nom, chemin], rang) => ({ "@type": "ListItem", position: rang + 1, name: nom, item: `${SITE.adresse}${chemin}` })),
  };
}

export function questions(liste: { question: string; reponse: string }[]) {
  return {
    "@type": "FAQPage",
    mainEntity: liste.map(({ question, reponse }) => ({ "@type": "Question", name: question, acceptedAnswer: { "@type": "Answer", text: reponse } })),
  };
}
