/** Le glossaire : chaque terme a sa page (/glossaire/<slug>).
 *  « definition » : une ou deux phrases, reprises en tête de page et dans les données structurées.
 *  « sections » : le texte de la page. Les liens « voir » pointent vers d'autres termes ou pages du site. */
export type Terme = {
  slug: string;
  terme: string;
  definition: string;
  sections: { titre: string; paragraphes: string[] }[];
  voir: { texte: string; lien: string }[];
};

export const GLOSSAIRE: Terme[] = [
  {
    slug: "autoliquidation",
    terme: "Autoliquidation de la TVA",
    definition:
      "L’autoliquidation est un mécanisme où c’est l’acheteur, et non le vendeur, qui déclare et paie la TVA d’une opération. Le vendeur facture alors hors taxe.",
    sections: [
      {
        titre: "Quand s’applique-t-elle ?",
        paragraphes: [
          "Elle s’applique notamment aux achats de services auprès d’un prestataire établi dans un autre pays de l’Union européenne, aux acquisitions intracommunautaires de biens, et à certains secteurs en France, comme la sous-traitance dans le bâtiment.",
          "L’acheteur déclare la TVA due et, s’il y a droit, la déduit sur la même déclaration : l’opération est souvent neutre pour sa trésorerie.",
        ],
      },
      {
        titre: "Sur une facture fournisseur",
        paragraphes: [
          "La facture ne porte pas de TVA, mais la mention « Autoliquidation ». Une facture hors taxe sans cette mention, pour une opération qui ne relève pas de l’autoliquidation, doit être vérifiée avant le paiement.",
        ],
      },
    ],
    voir: [
      { texte: "Numéro de TVA intracommunautaire", lien: "/glossaire/numero-tva-intracommunautaire" },
      { texte: "Mentions obligatoires d’une facture", lien: "/ressources/mentions-obligatoires-facture" },
    ],
  },
  {
    slug: "avoir",
    terme: "Avoir",
    definition: "Un avoir est une facture rectificative, de montant négatif, qui annule tout ou partie d’une facture déjà émise : retour de marchandise, erreur de prix, remise accordée après coup.",
    sections: [
      {
        titre: "Ce qu’il doit contenir",
        paragraphes: [
          "Un avoir porte les mêmes mentions obligatoires qu’une facture, un numéro dans la séquence de facturation, et la référence de la facture qu’il corrige.",
          "Une facture déjà émise ne se modifie jamais et ne se supprime pas : on la corrige par un avoir.",
        ],
      },
      {
        titre: "Sur une facture fournisseur",
        paragraphes: [
          "Un avoir reçu réduit ce que vous devez au fournisseur. Vérifiez qu’il renvoie bien à une facture que vous avez reçue, et qu’il est pris en compte avant de payer cette facture.",
        ],
      },
    ],
    voir: [
      { texte: "Facture d’acompte", lien: "/glossaire/facture-acompte" },
      { texte: "Doublon de facture", lien: "/glossaire/doublon-facture" },
    ],
  },
  {
    slug: "facture-acompte",
    terme: "Facture d’acompte",
    definition: "Une facture d’acompte est émise pour un paiement partiel versé avant la livraison ou la fin d’une prestation. Elle porte les mêmes mentions qu’une facture ordinaire.",
    sections: [
      {
        titre: "Comment elle s’articule avec la facture finale",
        paragraphes: [
          "À la fin de la commande, la facture finale reprend le montant total, puis déduit les acomptes déjà facturés. Seul le solde reste à payer.",
        ],
      },
      {
        titre: "Sur une facture fournisseur",
        paragraphes: [
          "Le risque classique : payer la facture finale en entier, en oubliant l’acompte déjà réglé. Rapprochez toujours la facture finale des acomptes reçus pour la même commande.",
        ],
      },
    ],
    voir: [
      { texte: "Bon de commande", lien: "/glossaire/bon-de-commande" },
      { texte: "Avoir", lien: "/glossaire/avoir" },
    ],
  },
  {
    slug: "bon-de-commande",
    terme: "Bon de commande",
    definition: "Le bon de commande est le document par lequel l’acheteur confirme ce qu’il achète : produits ou services, quantités, prix et conditions. Il engage l’acheteur.",
    sections: [
      {
        titre: "À quoi il sert dans le contrôle des factures",
        paragraphes: [
          "C’est la référence pour vérifier une facture : ce qui est facturé a-t-il été commandé, aux quantités et au prix convenus ? Une facture sans commande, ou au-dessus du prix commandé, mérite un regard avant le paiement.",
        ],
      },
      {
        titre: "Dans Verifac",
        paragraphes: [
          "Avec Odoo branché, Verifac cherche le bon de commande correspondant à chaque facture. Un écart de prix ou de quantité, ou l’absence de commande, est signalé et peut demander une approbation de plus.",
        ],
      },
    ],
    voir: [
      { texte: "Rapprochement à trois voies", lien: "/glossaire/rapprochement-trois-voies" },
      { texte: "Odoo et factures fournisseurs", lien: "/ressources/odoo-factures-fournisseurs" },
    ],
  },
  {
    slug: "rapprochement-trois-voies",
    terme: "Rapprochement à trois voies",
    definition:
      "Le rapprochement à trois voies (en anglais, three-way matching) consiste à comparer trois documents avant de payer : le bon de commande, le bon de réception et la facture.",
    sections: [
      {
        titre: "Pourquoi trois documents",
        paragraphes: [
          "La commande dit ce qui a été acheté, la réception ce qui est réellement arrivé, la facture ce qui est demandé. Si les trois concordent, la facture peut être payée. Sinon, l’écart doit être expliqué : livraison partielle, erreur de prix, article non commandé.",
          "Le rapprochement à deux voies, plus simple, compare seulement la commande et la facture.",
        ],
      },
    ],
    voir: [
      { texte: "Bon de commande", lien: "/glossaire/bon-de-commande" },
      { texte: "Circuit de validation", lien: "/glossaire/circuit-de-validation" },
    ],
  },
  {
    slug: "circuit-de-validation",
    terme: "Circuit de validation des factures",
    definition:
      "Le circuit de validation (ou workflow d’approbation) est l’ensemble des règles qui disent qui doit approuver une facture avant son paiement, dans quel ordre, et selon quels critères.",
    sections: [
      {
        titre: "Un exemple courant",
        paragraphes: [
          "Le comptable approuve toutes les factures ; le directeur financier, en plus, au-dessus de 1 000 € ou quand l’IBAN a changé ; le gérant, en plus, au-dessus de 5 000 €.",
        ],
      },
      {
        titre: "Ce qui fait un bon circuit",
        paragraphes: [
          "Des règles écrites et appliquées automatiquement, une validation possible depuis un mail, des relances quand personne ne répond, et une trace de chaque décision.",
        ],
      },
    ],
    voir: [
      { texte: "Régler le circuit dans Verifac", lien: "/documentation/circuit" },
      { texte: "Dématérialisation des factures fournisseurs", lien: "/ressources/dematerialisation-factures-fournisseurs" },
    ],
  },
  {
    slug: "factur-x",
    terme: "Factur-X",
    definition: "Factur-X est un format de facture électronique franco-allemand : un PDF lisible par une personne, qui contient en pièce jointe un fichier XML avec les données de la facture.",
    sections: [
      {
        titre: "En pratique",
        paragraphes: [
          "C’est l’un des trois formats acceptés par la réforme de la facturation électronique, avec UBL et CII. Il est identique à la norme allemande ZUGFeRD depuis sa version 2.1.",
          "Une personne lit le PDF ; un logiciel lit le XML, sans erreur de lecture.",
        ],
      },
    ],
    voir: [
      { texte: "Factur-X expliqué simplement", lien: "/ressources/factur-x" },
      { texte: "UBL et CII", lien: "/glossaire/ubl-cii" },
    ],
  },
  {
    slug: "ubl-cii",
    terme: "UBL et CII",
    definition:
      "UBL (Universal Business Language) et CII (Cross Industry Invoice) sont deux formats de facture électronique entièrement en XML, lisibles par les logiciels mais pas directement par une personne.",
    sections: [
      {
        titre: "Leur place dans la réforme",
        paragraphes: [
          "Avec Factur-X, ce sont les trois formats du socle de la facturation électronique en France. Factur-X utilise d’ailleurs la syntaxe CII pour son XML intégré.",
        ],
      },
    ],
    voir: [
      { texte: "Factur-X", lien: "/glossaire/factur-x" },
      { texte: "Facturation électronique 2026", lien: "/ressources/facturation-electronique-2026" },
    ],
  },
  {
    slug: "plateforme-agreee",
    terme: "Plateforme agréée (ex-PDP)",
    definition:
      "Une plateforme agréée est un prestataire immatriculé par l’administration fiscale pour émettre, recevoir et transmettre les factures électroniques des entreprises. On parlait avant de plateforme de dématérialisation partenaire (PDP).",
    sections: [
      {
        titre: "Pourquoi en choisir une",
        paragraphes: [
          "Avec la réforme, les factures entre entreprises établies en France passent par ces plateformes. Chaque entreprise doit en choisir une pour recevoir ses factures, depuis septembre 2026.",
          "La liste des plateformes immatriculées est publiée sur impots.gouv.fr.",
        ],
      },
    ],
    voir: [
      { texte: "Portail public de facturation (PPF)", lien: "/glossaire/portail-public-facturation" },
      { texte: "Facturation électronique 2026", lien: "/ressources/facturation-electronique-2026" },
    ],
  },
  {
    slug: "portail-public-facturation",
    terme: "Portail public de facturation (PPF)",
    definition:
      "Le portail public de facturation est la plateforme de l’administration fiscale dans la réforme de la facturation électronique. Il tient l’annuaire des entreprises et reçoit les données transmises par les plateformes agréées.",
    sections: [
      {
        titre: "Ce qui a changé en 2024",
        paragraphes: [
          "Le PPF devait d’abord permettre d’échanger gratuitement des factures. Depuis une décision de 2024, il ne le fait plus : les factures circulent par les plateformes agréées, et le PPF tient l’annuaire et centralise les données fiscales.",
        ],
      },
    ],
    voir: [
      { texte: "Plateforme agréée", lien: "/glossaire/plateforme-agreee" },
      { texte: "E-reporting", lien: "/glossaire/e-reporting" },
    ],
  },
  {
    slug: "e-reporting",
    terme: "E-reporting",
    definition:
      "L’e-reporting est la transmission à l’administration des données des opérations qui ne passent pas par une facture électronique : ventes aux particuliers, échanges avec l’étranger, et données de paiement de certaines prestations.",
    sections: [
      {
        titre: "Le calendrier",
        paragraphes: ["Il suit celui de l’émission des factures électroniques : septembre 2026 pour les grandes entreprises et les ETI, septembre 2027 pour les PME et micro-entreprises."],
      },
    ],
    voir: [
      { texte: "Facturation électronique 2026", lien: "/ressources/facturation-electronique-2026" },
      { texte: "Plateforme agréée", lien: "/glossaire/plateforme-agreee" },
    ],
  },
  {
    slug: "siren-siret",
    terme: "SIREN et SIRET",
    definition:
      "Le SIREN (9 chiffres) identifie une entreprise. Le SIRET (14 chiffres) identifie l’un de ses établissements : ce sont les 9 chiffres du SIREN suivis de 5 chiffres propres à l’établissement.",
    sections: [
      {
        titre: "Les clés de contrôle",
        paragraphes: [
          "Les deux numéros contiennent une clé calculée avec l’algorithme de Luhn : une faute de frappe la rend fausse. Les établissements de La Poste suivent une règle particulière.",
        ],
      },
      {
        titre: "Sur une facture fournisseur",
        paragraphes: [
          "Le SIREN ou le SIRET du vendeur est une mention obligatoire. Avec la réforme de la facturation électronique, le SIREN du client le devient aussi.",
        ],
      },
    ],
    voir: [
      { texte: "Vérifier un SIRET ou un numéro de TVA", lien: "/outils/verifier-numero-tva-intracommunautaire" },
      { texte: "Numéro de TVA intracommunautaire", lien: "/glossaire/numero-tva-intracommunautaire" },
    ],
  },
  {
    slug: "numero-tva-intracommunautaire",
    terme: "Numéro de TVA intracommunautaire",
    definition:
      "Le numéro de TVA intracommunautaire identifie une entreprise pour la TVA dans l’Union européenne. En France, il s’écrit FR, suivi d’une clé de deux chiffres, suivie des 9 chiffres du SIREN.",
    sections: [
      {
        titre: "Comment se calcule la clé",
        paragraphes: ["Clé = (12 + 3 × (SIREN modulo 97)) modulo 97. Par exemple, le SIREN 732 829 320 donne le numéro FR44 732 829 320."],
      },
      {
        titre: "Sur une facture fournisseur",
        paragraphes: [
          "Le numéro du vendeur est une mention obligatoire, sauf franchise en base de TVA. Un numéro qui ne correspond pas au SIREN de la même facture doit être vérifié avant le paiement.",
        ],
      },
    ],
    voir: [
      { texte: "Vérifier un numéro de TVA", lien: "/outils/verifier-numero-tva-intracommunautaire" },
      { texte: "SIREN et SIRET", lien: "/glossaire/siren-siret" },
    ],
  },
  {
    slug: "iban-rib",
    terme: "IBAN et RIB",
    definition:
      "Le RIB (relevé d’identité bancaire) est le document qui donne les coordonnées d’un compte. L’IBAN est le numéro international du compte : 27 caractères en France, qui reprennent le code banque, le code guichet, le numéro de compte et la clé RIB.",
    sections: [
      {
        titre: "La clé de contrôle",
        paragraphes: [
          "Les deux chiffres après le code pays forment une clé : une faute de frappe la rend fausse. Mais un IBAN valide peut tout de même appartenir à un fraudeur.",
        ],
      },
      {
        titre: "Sur une facture fournisseur",
        paragraphes: [
          "Un IBAN différent de celui que vous connaissez pour ce fournisseur est le signe classique de la fraude au faux RIB. Confirmez tout changement par téléphone, au numéro que vous connaissez déjà.",
        ],
      },
    ],
    voir: [
      { texte: "Vérifier un IBAN", lien: "/outils/verifier-iban" },
      { texte: "Faux RIB et fraude à l’IBAN", lien: "/ressources/faux-rib-fraude-iban" },
    ],
  },
  {
    slug: "franchise-en-base-tva",
    terme: "Franchise en base de TVA",
    definition:
      "La franchise en base de TVA dispense les petites entreprises, sous un certain chiffre d’affaires, de facturer la TVA. Leurs factures portent alors la mention « TVA non applicable, article 293 B du CGI ».",
    sections: [
      {
        titre: "Sur une facture fournisseur",
        paragraphes: [
          "Une facture sans TVA d’un fournisseur en franchise est normale, à condition de porter la mention de l’article 293 B. Vous ne pouvez évidemment pas déduire de TVA sur cette facture.",
        ],
      },
    ],
    voir: [
      { texte: "Mentions obligatoires d’une facture", lien: "/ressources/mentions-obligatoires-facture" },
      { texte: "Autoliquidation", lien: "/glossaire/autoliquidation" },
    ],
  },
  {
    slug: "tva-sur-les-debits",
    terme: "TVA sur les débits",
    definition:
      "Pour les prestations de services, la TVA est normalement due à l’encaissement du prix. Le prestataire peut choisir de la payer d’après les débits, c’est-à-dire dès la facturation.",
    sections: [
      {
        titre: "Pourquoi c’est sur la facture",
        paragraphes: [
          "Avec la réforme de la facturation électronique, l’option pour le paiement de la TVA d’après les débits devient une mention de la facture, quand le prestataire l’a choisie.",
        ],
      },
    ],
    voir: [{ texte: "Mentions obligatoires d’une facture", lien: "/ressources/mentions-obligatoires-facture" }],
  },
  {
    slug: "delai-de-paiement",
    terme: "Délai de paiement entre entreprises",
    definition:
      "Entre professionnels, le délai de paiement convenu ne peut pas dépasser 60 jours à compter de la date de la facture, ou 45 jours fin de mois. À défaut d’accord, il est de 30 jours après la réception des marchandises ou la fin de la prestation.",
    sections: [
      {
        titre: "Sur une facture fournisseur",
        paragraphes: [
          "La date d’échéance est une mention obligatoire. Une échéance antérieure à la date de facture est une erreur ; une échéance très courte, présentée comme urgente, est un signe fréquent de fraude.",
        ],
      },
    ],
    voir: [
      { texte: "Pénalités de retard et indemnité de 40 €", lien: "/glossaire/penalites-de-retard" },
      { texte: "Escompte", lien: "/glossaire/escompte" },
    ],
  },
  {
    slug: "penalites-de-retard",
    terme: "Pénalités de retard et indemnité de 40 €",
    definition:
      "Entre professionnels, un paiement en retard entraîne des pénalités, dont le taux doit figurer sur la facture, et une indemnité forfaitaire de 40 € pour frais de recouvrement.",
    sections: [
      {
        titre: "Ce qu’il faut savoir",
        paragraphes: [
          "Les pénalités courent dès le lendemain de l’échéance, sans relance nécessaire. Payer à temps les factures fournisseurs évite donc des frais, en plus de préserver la relation.",
        ],
      },
    ],
    voir: [
      { texte: "Délai de paiement", lien: "/glossaire/delai-de-paiement" },
      { texte: "Mentions obligatoires d’une facture", lien: "/ressources/mentions-obligatoires-facture" },
    ],
  },
  {
    slug: "escompte",
    terme: "Escompte",
    definition: "L’escompte est une réduction accordée pour un paiement avant l’échéance. Les conditions d’escompte, ou leur absence, sont une mention obligatoire de la facture.",
    sections: [
      {
        titre: "Sur une facture fournisseur",
        paragraphes: [
          "Un escompte peut valoir la peine de payer plus tôt : encore faut-il que la facture soit vérifiée et approuvée à temps. Un circuit de validation rapide permet d’en profiter.",
        ],
      },
    ],
    voir: [
      { texte: "Délai de paiement", lien: "/glossaire/delai-de-paiement" },
      { texte: "Circuit de validation", lien: "/glossaire/circuit-de-validation" },
    ],
  },
  {
    slug: "doublon-facture",
    terme: "Doublon de facture",
    definition:
      "Un doublon est une même facture reçue ou enregistrée deux fois : par mail puis par courrier, sous un autre nom de fichier, ou relancée par le fournisseur. Payé deux fois, il est difficile à récupérer.",
    sections: [
      {
        titre: "Comment le repérer",
        paragraphes: [
          "Même fournisseur et même numéro de facture : c’est un doublon, même si le fichier est différent. Un même fichier reçu deux fois aussi.",
        ],
      },
      {
        titre: "Dans Verifac",
        paragraphes: ["Un fichier déjà reçu n’est pas traité deux fois, et une facture avec le même fournisseur et le même numéro qu’une facture existante est arrêtée."],
      },
    ],
    voir: [
      { texte: "Comprendre une anomalie", lien: "/documentation/anomalies" },
      { texte: "Avoir", lien: "/glossaire/avoir" },
    ],
  },
  {
    slug: "ocr-facture",
    terme: "OCR et lecture automatique des factures",
    definition:
      "L’OCR (reconnaissance optique de caractères) transforme l’image d’un document en texte. Pour les factures, la lecture automatique va plus loin : elle relève le fournisseur, les montants, l’échéance et l’IBAN, aujourd’hui souvent avec une intelligence artificielle.",
    sections: [
      {
        titre: "Ses limites",
        paragraphes: [
          "Une lecture automatique peut se tromper sur un scan de mauvaise qualité. Les informations lues doivent donc rester vérifiables à côté du document, et contrôlées : un total qui ne tombe pas juste signale souvent une erreur de lecture.",
          "Avec une facture électronique (Factur-X, UBL, CII), il n’y a plus rien à lire : les données arrivent déjà structurées.",
        ],
      },
    ],
    voir: [
      { texte: "Factur-X", lien: "/glossaire/factur-x" },
      { texte: "Dématérialisation des factures fournisseurs", lien: "/ressources/dematerialisation-factures-fournisseurs" },
    ],
  },
];

export const terme = (slug: string) => GLOSSAIRE.find((t) => t.slug === slug);
