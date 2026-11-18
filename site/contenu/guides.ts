/** Les guides de la documentation, dans l'ordre du sommaire. Le texte de chacun est dans contenu/guides/<slug>.mdx. */
export type Guide = { slug: string; titre: string; resume: string; description: string; duree: string; icone: IconeGuide };
export type IconeGuide = "reception" | "approbation" | "anomalie" | "circuit" | "branchement" | "api";

export const GUIDES: Guide[] = [
  { slug: "recevoir-des-factures", titre: "Recevoir et déposer des factures", resume: "Adresse mail dédiée, dépôt, formats acceptés", description: "Recevoir les factures fournisseurs dans Verifac : adresse mail dédiée, transfert depuis Gmail ou Outlook, dépôt, API, formats acceptés (Factur-X, PDF, scans).", duree: "3 min", icone: "reception" },
  { slug: "approuver", titre: "Approuver ou rejeter", resume: "Depuis un mail, dans Verifac, à plusieurs niveaux", description: "Approuver ou rejeter une facture fournisseur dans Verifac : niveaux d’approbation, validation depuis un mail, relances automatiques et journal des décisions.", duree: "2 min", icone: "approbation" },
  { slug: "anomalies", titre: "Comprendre une anomalie", resume: "Ce que signifie chaque alerte, et que faire", description: "Toutes les anomalies que Verifac détecte sur une facture fournisseur, bloquantes ou non : calculs, SIRET, TVA, IBAN, doublons, bon de commande. Et que faire.", duree: "4 min", icone: "anomalie" },
  { slug: "circuit", titre: "Régler le circuit d’approbation", resume: "Niveaux, seuils, relances, publication", description: "Régler le circuit d’approbation des factures dans Verifac : conditions, niveaux, brouillon, test sur une facture, publication, versions et relances.", duree: "5 min", icone: "circuit" },
  { slug: "odoo-et-claude", titre: "Brancher Odoo et Claude", resume: "Connexion pas à pas, droits accordés", description: "Brancher Verifac à Odoo (bons de commande, factures en brouillon) et à Claude (questions sur vos factures, en lecture seule), pas à pas.", duree: "4 min", icone: "branchement" },
  { slug: "api", titre: "API pour les développeurs", resume: "Clés, dépôt de factures, webhooks signés", description: "API de Verifac : clés, dépôt et lecture des factures, webhooks signés et vérification de la signature HMAC. Exemples curl et Python.", duree: "Référence", icone: "api" },
];

export const guide = (slug: string) => GUIDES.find((g) => g.slug === slug);
