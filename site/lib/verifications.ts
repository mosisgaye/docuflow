/** Les vérifications des outils gratuits. Mêmes règles que le moteur de Verifac (moteur/controles.py).
 *  Tout se calcule dans le navigateur : rien n'est envoyé à un serveur. */

/** Longueur de l'IBAN par pays (registre SWIFT ISO 13616), pour les pays les plus courants en Europe. */
export const LONGUEURS_IBAN: Record<string, { pays: string; longueur: number }> = {
  FR: { pays: "France", longueur: 27 },
  MC: { pays: "Monaco", longueur: 27 },
  BE: { pays: "Belgique", longueur: 16 },
  LU: { pays: "Luxembourg", longueur: 20 },
  CH: { pays: "Suisse", longueur: 21 },
  DE: { pays: "Allemagne", longueur: 22 },
  ES: { pays: "Espagne", longueur: 24 },
  IT: { pays: "Italie", longueur: 27 },
  PT: { pays: "Portugal", longueur: 25 },
  NL: { pays: "Pays-Bas", longueur: 18 },
  AT: { pays: "Autriche", longueur: 20 },
  IE: { pays: "Irlande", longueur: 22 },
  GB: { pays: "Royaume-Uni", longueur: 22 },
  PL: { pays: "Pologne", longueur: 28 },
  LT: { pays: "Lituanie", longueur: 20 },
  LV: { pays: "Lettonie", longueur: 21 },
  EE: { pays: "Estonie", longueur: 20 },
  MT: { pays: "Malte", longueur: 31 },
  CY: { pays: "Chypre", longueur: 28 },
  GR: { pays: "Grèce", longueur: 27 },
  DK: { pays: "Danemark", longueur: 18 },
  SE: { pays: "Suède", longueur: 24 },
  FI: { pays: "Finlande", longueur: 18 },
  NO: { pays: "Norvège", longueur: 15 },
  RO: { pays: "Roumanie", longueur: 24 },
  BG: { pays: "Bulgarie", longueur: 22 },
  HR: { pays: "Croatie", longueur: 21 },
  SI: { pays: "Slovénie", longueur: 19 },
  SK: { pays: "Slovaquie", longueur: 24 },
  CZ: { pays: "Tchéquie", longueur: 24 },
  HU: { pays: "Hongrie", longueur: 28 },
  MA: { pays: "Maroc", longueur: 28 },
  TN: { pays: "Tunisie", longueur: 24 },
  SN: { pays: "Sénégal", longueur: 28 },
};

export type ResultatIban =
  | { valide: true; iban: string; pays: string | null; banque: string | null; groupes: string }
  | { valide: false; iban: string; raison: string };

export const normaliserIban = (saisie: string) => saisie.replace(/[\s-]/g, "").toUpperCase();

/** Reste de la division par 97 d'un très grand nombre écrit en chiffres, morceau par morceau. */
function modulo97(chiffres: string): number {
  let reste = 0;
  for (let i = 0; i < chiffres.length; i += 7) reste = Number(`${reste}${chiffres.slice(i, i + 7)}`) % 97;
  return reste;
}

export function verifierIban(saisie: string): ResultatIban {
  const iban = normaliserIban(saisie);
  if (!iban) return { valide: false, iban, raison: "Saisissez un IBAN." };
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]+$/.test(iban)) return { valide: false, iban, raison: "Un IBAN commence par deux lettres (le pays), puis deux chiffres (la clé), puis des chiffres et des lettres." };
  const fiche = LONGUEURS_IBAN[iban.slice(0, 2)];
  if (fiche && iban.length !== fiche.longueur)
    return { valide: false, iban, raison: `Un IBAN ${fiche.pays === "France" ? "français" : `de ce pays (${fiche.pays})`} compte ${fiche.longueur} caractères ; celui-ci en compte ${iban.length}.` };
  if (iban.length < 15 || iban.length > 34) return { valide: false, iban, raison: "Un IBAN compte entre 15 et 34 caractères." };
  const chiffres = [...(iban.slice(4) + iban.slice(0, 4))].map((c) => parseInt(c, 36).toString()).join("");
  if (modulo97(chiffres) !== 1) return { valide: false, iban, raison: "La clé de contrôle est fausse : au moins un caractère est erroné, ou l’IBAN a été inventé." };
  const groupes = iban.match(/.{1,4}/g)?.join(" ") ?? iban;
  // En France, les 5 chiffres après la clé sont le code de la banque.
  const banque = iban.startsWith("FR") || iban.startsWith("MC") ? iban.slice(4, 9) : null;
  return { valide: true, iban, pays: fiche?.pays ?? null, banque, groupes };
}

/** Algorithme de Luhn, utilisé pour les numéros SIREN et SIRET. */
export function luhnValide(chiffres: string): boolean {
  let total = 0;
  [...chiffres].reverse().forEach((caractere, rang) => {
    let chiffre = Number(caractere);
    if (rang % 2 === 1) {
      chiffre *= 2;
      if (chiffre > 9) chiffre -= 9;
    }
    total += chiffre;
  });
  return total % 10 === 0;
}

const SIREN_LA_POSTE = "356000000";

export function sirenValide(siren: string): boolean {
  return /^\d{9}$/.test(siren) && (siren === SIREN_LA_POSTE || luhnValide(siren));
}

export function siretValide(siret: string): boolean {
  if (!/^\d{14}$/.test(siret)) return false;
  // Exception officielle : les établissements de La Poste suivent une autre règle.
  if (siret.startsWith(SIREN_LA_POSTE)) return [...siret].reduce((somme, c) => somme + Number(c), 0) % 5 === 0;
  return luhnValide(siret) && luhnValide(siret.slice(0, 9));
}

/** Clé à deux chiffres du numéro de TVA français, calculée à partir du SIREN. */
export function cleTva(siren: string): string {
  return String((12 + 3 * (Number(siren) % 97)) % 97).padStart(2, "0");
}

export type ResultatIdentifiant =
  | { valide: true; genre: "siren" | "siret" | "tva"; siren: string; siret: string | null; tva: string }
  | { valide: false; raison: string };

/** Accepte un SIREN (9 chiffres), un SIRET (14 chiffres) ou un numéro de TVA français (FR + 2 caractères + SIREN). */
export function verifierIdentifiant(saisie: string): ResultatIdentifiant {
  const valeur = saisie.replace(/[\s.-]/g, "").toUpperCase();
  if (!valeur) return { valide: false, raison: "Saisissez un numéro de TVA, un SIREN ou un SIRET." };
  if (valeur.startsWith("FR")) {
    if (!/^FR[0-9A-Z]{2}\d{9}$/.test(valeur)) return { valide: false, raison: "Un numéro de TVA français s’écrit FR, puis 2 caractères (la clé), puis les 9 chiffres du SIREN : 13 caractères en tout." };
    const siren = valeur.slice(4);
    if (!sirenValide(siren)) return { valide: false, raison: `Le SIREN contenu dans ce numéro (${siren}) n’est pas valide.` };
    const attendue = cleTva(siren);
    if (/^\d{2}$/.test(valeur.slice(2, 4)) && valeur.slice(2, 4) !== attendue)
      return { valide: false, raison: `La clé est fausse : pour le SIREN ${siren}, le numéro de TVA est FR${attendue}${siren}.` };
    return { valide: true, genre: "tva", siren, siret: null, tva: valeur };
  }
  if (/^[A-Z]{2}/.test(valeur)) return { valide: false, raison: "Cet outil vérifie les numéros français. Pour un autre pays de l’Union européenne, utilisez le service VIES de la Commission européenne." };
  if (/^\d{9}$/.test(valeur)) return sirenValide(valeur) ? { valide: true, genre: "siren", siren: valeur, siret: null, tva: `FR${cleTva(valeur)}${valeur}` } : { valide: false, raison: "Ce SIREN n’est pas valide : sa clé de contrôle est fausse." };
  if (/^\d{14}$/.test(valeur)) {
    const siren = valeur.slice(0, 9);
    return siretValide(valeur) ? { valide: true, genre: "siret", siren, siret: valeur, tva: `FR${cleTva(siren)}${siren}` } : { valide: false, raison: "Ce SIRET n’est pas valide : sa clé de contrôle est fausse." };
  }
  return { valide: false, raison: "Un SIREN compte 9 chiffres, un SIRET 14 chiffres, un numéro de TVA français 13 caractères (FR + clé + SIREN)." };
}
