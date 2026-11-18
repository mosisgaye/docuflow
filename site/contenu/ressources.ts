/** Les articles de la section Ressources. Le texte de chacun est dans contenu/ressources/<slug>.mdx.
 *  « cible » : la recherche Google visée (docs/mots-cles.csv). « enBref » : 3 points affichés en tête d'article.
 *  « sources » : affichées en fin d'article ; uniquement des sources consultées, officielles quand c'est possible. */
export type Source = { titre: string; url: string };
export type Article = {
  slug: string;
  titre: string; // le titre affiché (h1)
  titreSeo: string; // la balise <title>, 51 caractères au plus (« , Verifac » est ajouté)
  description: string; // 70 à 160 caractères
  cible: string;
  publie: string; // AAAA-MM-JJ
  modifie: string;
  lecture: string;
  enBref: string[];
  sources: Source[];
  liees: string[];
};

const LEFEBVRE_LF2026: Source = {
  titre: "Éditions Francis Lefebvre : loi de finances pour 2026, du nouveau pour la facturation électronique",
  url: "https://www.efl.fr/actualite/loi-finances-2026-nouveau-facturation-electronique-transmission-donnees_faf90213b-88d6-4a24-b6ed-22a3884ef066",
};
const IMPOTS_CAP: Source = { titre: "impots.gouv.fr : facturation électronique, un cap déterminant est franchi", url: "https://www.impots.gouv.fr/actualite/facturation-electronique-un-cap-determinant-est-franchi" };
const ECO_101: Source = {
  titre: "economie.gouv.fr : la liste des 101 premières plateformes agréées est disponible",
  url: "https://www.economie.gouv.fr/actualites/facturation-electronique-la-liste-des-101-premieres-plateformes-agreees",
};
const IMPOTS_FICHE_EMISSION: Source = {
  titre: "impots.gouv.fr : fiche « l’émission de factures électroniques » (PDF)",
  url: "https://www.impots.gouv.fr/sites/default/files/media/1_metier/2_professionnel/EV/2_gestion/290_facturation_electronique/fiches_reforme/fiche-e-invoicing.pdf",
};
const REGLEMENT_VOP: Source = { titre: "Règlement (UE) 2024/886 sur les virements instantanés en euros (EUR-Lex)", url: "https://eur-lex.europa.eu/eli/reg/2024/886/oj" };
const FINANCE_POUR_TOUS_VOP: Source = {
  titre: "La finance pour tous : la vérification du bénéficiaire devient obligatoire",
  url: "https://www.lafinancepourtous.com/2025/09/29/virement-la-verification-du-beneficiaire-par-la-banque-devient-obligatoire/",
};
const CYBERMALVEILLANCE: Source = { titre: "Cybermalveillance.gouv.fr : assistance et prévention", url: "https://www.cybermalveillance.gouv.fr" };

export const ARTICLES: Article[] = [
  {
    slug: "facture-electronique-bilan-fin-2026",
    titre: "Facture électronique : le bilan après deux mois, et ce qu’il faut faire avant le 31 décembre",
    titreSeo: "Facture électronique : que faire avant fin 2026",
    description: "20 millions de factures échangées, un quart des entreprises sans plateforme, pas de sanction avant fin 2026 : le bilan de la réforme et les actions à mener.",
    cible: "facture électronique septembre 2026",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "6 min",
    enBref: [
      "Au premier bilan officiel (8 octobre 2026), 75 % des entreprises qui déclarent la TVA avaient choisi une plateforme de réception.",
      "Le gouvernement a annoncé qu’aucune sanction ne serait prononcée avant la fin de 2026 : la règle, elle, est en vigueur.",
      "Avant le 31 décembre : choisir sa plateforme, vérifier qu’on reçoit bien ses factures, organiser leur contrôle.",
    ],
    sources: [
      IMPOTS_CAP,
      { titre: "Lexis Veille : un guide actualisé et une absence de sanctions annoncée jusqu’à la fin de l’année", url: "https://www.lexisveille.fr/facturation-electronique-un-guide-actualise-et-une-absence-de-sanctions-annoncee-jusqua-la-fin-de" },
      { titre: "MoneyVox : facturation électronique, un résultat « au-delà des attentes » selon David Amiel", url: "https://www.moneyvox.fr/banque-pro/actualites/110408/facturation-electronique-resultat-au-dela-des-attentes-selon-david-amiel" },
      LEFEBVRE_LF2026,
    ],
    liees: ["facturation-electronique-2026", "choisir-plateforme-agreee", "facture-electronique-rejetee-refusee"],
  },
  {
    slug: "facture-electronique-rejetee-refusee",
    titre: "Facture électronique rejetée ou refusée : les motifs, et que faire",
    titreSeo: "Facture électronique rejetée ou refusée : que faire",
    description: "Rejet technique ou refus du client : la différence, les motifs les plus fréquents, et comment éviter qu’un rejet ne retarde le paiement de vos factures.",
    cible: "facture électronique rejetée",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "6 min",
    enBref: [
      "Une facture « rejetée » est bloquée par une plateforme pour une raison technique ; une facture « refusée » l’est par le client, pour une raison commerciale.",
      "Les plateformes agréées doivent suivre au moins quatre statuts : déposée, rejetée, refusée, encaissée.",
      "Un refus doit toujours avoir un motif précis : c’est ce qui permet de corriger vite, et d’éviter les refus abusifs.",
    ],
    sources: [IMPOTS_FICHE_EMISSION, IMPOTS_CAP],
    liees: ["mentions-obligatoires-facture", "facture-electronique-bilan-fin-2026", "dematerialisation-factures-fournisseurs"],
  },
  {
    slug: "verification-beneficiaire-virement",
    titre: "Vérification du bénéficiaire : ce qu’elle arrête, et ce qu’elle laisse passer",
    titreSeo: "Vérification du bénéficiaire : ce qu’elle rate",
    description: "Depuis octobre 2025, la banque compare le nom du bénéficiaire et l’IBAN avant un virement. Utile, mais insuffisant contre la fraude au faux fournisseur.",
    cible: "vérification du bénéficiaire virement",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "6 min",
    enBref: [
      "Depuis le 9 octobre 2025, votre banque vérifie que le nom saisi correspond au titulaire de l’IBAN avant un virement SEPA.",
      "Elle ne vérifie pas que ce compte est bien celui de votre fournisseur : un fraudeur qui a ouvert un compte à son nom passe.",
      "En cas d’alerte, vous pouvez toujours valider le virement : la décision, et le risque, restent les vôtres.",
    ],
    sources: [REGLEMENT_VOP, FINANCE_POUR_TOUS_VOP],
    liees: ["faux-rib-fraude-iban", "fraude-faux-fournisseur-fin-annee", "mentions-obligatoires-facture"],
  },
  {
    slug: "fraude-faux-fournisseur-fin-annee",
    titre: "Fraude au faux fournisseur : la liste de contrôle de fin d’année",
    titreSeo: "Faux fournisseur : les contrôles de fin d’année",
    description: "Clôture, congés, factures en rafale : la fin d’année est le moment préféré des fraudeurs. Huit contrôles simples pour la comptabilité fournisseurs.",
    cible: "fraude au faux fournisseur",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "5 min",
    enBref: [
      "En fin d’année, les équipes sont réduites et pressées : c’est exactement ce que cherchent les fraudeurs.",
      "Huit contrôles couvrent l’essentiel : IBAN, doublons, commande, montant, urgence, expéditeur, double validation, trace.",
      "Le plus efficace reste le plus simple : confirmer tout changement de coordonnées par téléphone, au numéro connu.",
    ],
    sources: [REGLEMENT_VOP, CYBERMALVEILLANCE],
    liees: ["faux-rib-fraude-iban", "verification-beneficiaire-virement", "dematerialisation-factures-fournisseurs"],
  },
  {
    slug: "choisir-plateforme-agreee",
    titre: "Choisir sa plateforme agréée : les critères qui comptent pour une PME",
    titreSeo: "Choisir sa plateforme agréée : les critères",
    description: "Près de 150 plateformes agréées, des offres difficiles à comparer : les critères pour choisir celle qui reçoit vos factures, et les questions à poser.",
    cible: "plateforme agréée facture électronique",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "6 min",
    enBref: [
      "La liste officielle est passée de 101 plateformes en janvier 2026 à près de 150 : seule la liste publiée sur impots.gouv.fr fait foi.",
      "Le bon choix dépend d’abord de votre logiciel de comptabilité et de vos volumes, pas du prix affiché.",
      "Recevoir ses factures n’est que la première étape : il faut encore les vérifier et les faire approuver.",
    ],
    sources: [ECO_101, IMPOTS_CAP, { titre: "France Num : quelles plateformes agréées pour les TPE et PME ?", url: "https://www.francenum.gouv.fr/guides-et-conseils/pilotage-de-lentreprise/dematerialisation-des-documents/facturation-0" }],
    liees: ["facture-electronique-bilan-fin-2026", "facturation-electronique-2026", "dematerialisation-factures-fournisseurs"],
  },
  {
    slug: "facturation-electronique-2026",
    titre: "Facturation électronique 2026 : le calendrier et ce que doit faire une PME",
    titreSeo: "Facturation électronique 2026 : le calendrier",
    description: "Réception obligatoire depuis septembre 2026, émission en 2027 pour les PME : le calendrier, les formats, les plateformes agréées et la marche à suivre.",
    cible: "facturation électronique 2026",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "8 min",
    enBref: [
      "Depuis le 1er septembre 2026, toutes les entreprises doivent pouvoir recevoir des factures électroniques.",
      "Le 1er septembre 2027, les PME et micro-entreprises devront aussi en émettre.",
      "Un PDF envoyé par mail n’est pas une facture électronique : elle passe par une plateforme agréée, en Factur-X, UBL ou CII.",
    ],
    sources: [IMPOTS_CAP, LEFEBVRE_LF2026, ECO_101],
    liees: ["facture-electronique-bilan-fin-2026", "factur-x", "choisir-plateforme-agreee"],
  },
  {
    slug: "faux-rib-fraude-iban",
    titre: "Faux RIB : comment repérer une fraude à l’IBAN sur une facture fournisseur",
    titreSeo: "Faux RIB : repérer la fraude à l’IBAN",
    description: "Un fournisseur annonce un nouveau RIB par mail ? Les signes d’une arnaque au faux RIB, la procédure de contrôle à suivre, et que faire si vous avez payé.",
    cible: "faux rib",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "7 min",
    enBref: [
      "La fraude au faux RIB repose sur un IBAN valide : celui du fraudeur.",
      "La seule parade sûre : confirmer tout changement de coordonnées par téléphone, au numéro déjà connu.",
      "Si vous avez payé : appelez votre banque dans l’heure, puis portez plainte.",
    ],
    sources: [REGLEMENT_VOP, CYBERMALVEILLANCE],
    liees: ["verification-beneficiaire-virement", "fraude-faux-fournisseur-fin-annee", "mentions-obligatoires-facture"],
  },
  {
    slug: "factur-x",
    titre: "Factur-X : le format de facture électronique expliqué simplement",
    titreSeo: "Factur-X : le format de facture électronique",
    description: "Factur-X, UBL, CII : ce qu’est le format Factur-X, ses profils, comment le reconnaître et le lire, et ce qu’il change pour vos factures fournisseurs.",
    cible: "factur-x",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "6 min",
    enBref: [
      "Factur-X est un PDF lisible par une personne, avec les données de la facture en XML à l’intérieur.",
      "C’est l’un des trois formats de la réforme, avec UBL et CII.",
      "Préférez les profils BASIC, EN 16931 ou EXTENDED, qui décrivent les lignes de la facture.",
    ],
    sources: [IMPOTS_FICHE_EMISSION, { titre: "FNFE-MPE : le format Factur-X", url: "https://fnfe-mpe.org/factur-x/" }],
    liees: ["facturation-electronique-2026", "facture-electronique-rejetee-refusee", "odoo-factures-fournisseurs"],
  },
  {
    slug: "mentions-obligatoires-facture",
    titre: "Mentions obligatoires d’une facture : la liste complète",
    titreSeo: "Mentions obligatoires d’une facture",
    description: "Toutes les mentions obligatoires d’une facture en France, les nouvelles mentions de la facture électronique, et comment vérifier une facture fournisseur.",
    cible: "mentions obligatoires facture",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "6 min",
    enBref: [
      "Une facture doit identifier le vendeur, le client, ce qui est vendu, les montants et les conditions de paiement.",
      "La facture électronique ajoute quatre mentions, dont le SIREN du client et la nature de l’opération.",
      "Cette liste sert aussi à vérifier les factures que vous recevez, avant de les payer.",
    ],
    sources: [IMPOTS_FICHE_EMISSION, { titre: "Service-public.fr (entreprendre) : mentions obligatoires d’une facture", url: "https://entreprendre.service-public.fr/vosdroits/F31808" }],
    liees: ["facture-electronique-rejetee-refusee", "faux-rib-fraude-iban", "factur-x"],
  },
  {
    slug: "dematerialisation-factures-fournisseurs",
    titre: "Dématérialisation des factures fournisseurs : le guide pour une PME",
    titreSeo: "Dématérialisation des factures fournisseurs",
    description: "Réception, lecture, contrôles, circuit de validation, comptabilité : comment dématérialiser la gestion des factures fournisseurs d’une PME, étape par étape.",
    cible: "dématérialisation factures fournisseurs",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "8 min",
    enBref: [
      "Dématérialiser, ce n’est pas scanner : c’est faire suivre à chaque facture le même chemin, sans ressaisie.",
      "L’étape la plus oubliée est la plus utile : contrôler chaque facture avant de la faire approuver.",
      "Un bon outil s’adapte à votre circuit de validation et se branche à votre comptabilité.",
    ],
    sources: [IMPOTS_CAP, IMPOTS_FICHE_EMISSION],
    liees: ["facturation-electronique-2026", "faux-rib-fraude-iban", "odoo-factures-fournisseurs"],
  },
  {
    slug: "odoo-factures-fournisseurs",
    titre: "Odoo et factures fournisseurs : contrôler avant d’enregistrer",
    titreSeo: "Facture électronique Odoo : factures fournisseurs",
    description: "Factures fournisseurs dans Odoo : facture électronique, rapprochement avec les bons de commande, contrôles et circuit de validation avant la comptabilité.",
    cible: "facture électronique odoo",
    publie: "2026-11-18",
    modifie: "2026-11-18",
    lecture: "5 min",
    enBref: [
      "Odoo gère très bien une facture fournisseur une fois enregistrée.",
      "Les contrôles (doublon, IBAN, commande, approbation) doivent se faire avant l’enregistrement.",
      "Verifac s’appuie sur les données d’Odoo pour contrôler, puis y enregistre la facture en brouillon.",
    ],
    sources: [{ titre: "Documentation Odoo : factures fournisseurs", url: "https://www.odoo.com/documentation/latest/fr/applications/finance/accounting/vendor_bills.html" }],
    liees: ["dematerialisation-factures-fournisseurs", "factur-x", "facturation-electronique-2026"],
  },
];

export const article = (slug: string) => ARTICLES.find((a) => a.slug === slug);
