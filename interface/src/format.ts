import type { Etat, FactureResume, Evenement } from './api'

const EUROS = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' })
const NOMBRE = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 4 })
const JOUR = new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
const HEURE = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export const euros = (montant: string | null, absent = 'Absent') => (montant === null ? absent : EUROS.format(Number(montant)))
export const nombre = (valeur: string | null, absent = 'Absent') => (valeur === null ? absent : NOMBRE.format(Number(valeur)))
export const jour = (iso: string | null, absent = 'Absente') => (iso === null ? absent : JOUR.format(new Date(iso)))
export const heure = (iso: string) => HEURE.format(new Date(iso))
export const jourEtHeure = (iso: string) => `${JOUR.format(new Date(iso))} à ${HEURE.format(new Date(iso))}`

export function siret(valeur: string | null) {
  if (valeur === null) return 'Absent'
  return valeur.length === 14 ? `${valeur.slice(0, 3)} ${valeur.slice(3, 6)} ${valeur.slice(6, 9)} ${valeur.slice(9)}` : valeur
}

/**
 * Ce qu'on affiche quand une information manque. Une facture lue dont un champ est vide :
 * l'information est absente du document. Une facture pas encore lue, ou illisible : on ne sait pas.
 */
export const manquant = (etat: Etat) => (etat === 'recue' ? 'Lecture en cours' : etat === 'echec' ? 'Non lu' : 'Absent')

export const LIBELLE_ETAT: Record<Etat, string> = {
  recue: 'Lecture en cours',
  extraite: 'Extraite',
  a_valider: 'À valider',
  en_approbation: 'En approbation',
  en_anomalie: 'En anomalie',
  validee: 'Validée',
  rejetee: 'Rejetée',
  exportee: 'En comptabilité',
  echec: 'Lecture impossible',
}

export const A_TRAITER: Etat[] = ['en_anomalie', 'echec', 'en_approbation', 'a_valider', 'recue', 'extraite']

export const LIBELLE_NIVEAU: Record<string, string> = { comptable: 'Comptable', directeur_financier: 'Directeur financier', gerant: 'Gérant' }

/** Phrase lisible pour une ligne du journal. */
export function raconter(evenement: Evenement): string {
  const detail = evenement.detail
  switch (evenement.type) {
    case 'RECEPTION':
      if (detail.source === 'mail') return `Reçue par mail de ${String(detail.expediteur)}${detail.objet ? `, objet « ${String(detail.objet)} »` : ''}`
      return 'Fichier reçu'
    case 'EXTRACTION':
      if (detail.source === 'factur-x') return 'Facture électronique Factur-X : données lues directement, sans IA'
      if (detail.source === 'ia-image')
        return `Facture scannée : lue sur l’image par l’IA en ${NOMBRE.format(Number(detail.duree_s))} s (${String(detail.pages_lues)} page${Number(detail.pages_lues) > 1 ? 's' : ''})`
      return `Données lues par l’IA en ${NOMBRE.format(Number(detail.duree_s))} s (${String(detail.modele)})`
    case 'FACTURX_ILLISIBLE':
      return `Factur-X illisible, lecture confiée à l’IA : ${String(detail.raison)}`
    case 'CONTROLE': {
      const anomalies = (detail.anomalies as string[] | undefined) ?? []
      if (anomalies.length === 0) return 'Contrôles passés sans anomalie'
      return anomalies.length === 1 ? 'Contrôles : 1 anomalie trouvée' : `Contrôles : ${anomalies.length} anomalies trouvées`
    }
    case 'DOUBLON_FICHIER':
      if (detail.source === 'mail') return `Même fichier renvoyé par mail (${String(detail.expediteur)}) : reconnu, rien n’a été refait`
      return 'Même fichier renvoyé : reconnu, rien n’a été refait'
    case 'NOUVEL_ESSAI':
      return 'Nouvel essai de lecture'
    case 'NOUVEL_ESSAI_PROGRAMME':
      return `IA momentanément indisponible : nouvel essai dans ${duree(Number(detail.dans_s))}`
    case 'EXTRACTION_ECHOUEE':
    case 'LECTURE_IMPOSSIBLE':
      return String(detail.raison ?? 'Lecture impossible')
    case 'NOTIFICATION': {
      // Le destinataire et « relance » : sans eux, deux mails au même niveau ressemblent à un envoi en double.
      const niveau = LIBELLE_NIVEAU[String(detail.niveau)]?.toLowerCase() ?? 'approbateur'
      const pour = detail.destinataire ? ` à ${String(detail.destinataire)}` : ''
      return detail.rappel ? `Relance envoyée par mail${pour} (${niveau})` : `Demande d’approbation envoyée par mail${pour} (${niveau})`
    }
    case 'NOTIFICATION_ECHOUEE':
      return `Mail d’approbation non envoyé : ${String(detail.raison)}`
    case 'APPROBATION':
      return `Approuvée par ${evenement.auteur} (${LIBELLE_NIVEAU[String(detail.niveau)]?.toLowerCase() ?? 'niveau'}) : au niveau suivant`
    case 'VALIDATION':
      return detail.niveau ? `Validée par ${evenement.auteur} (${LIBELLE_NIVEAU[String(detail.niveau)]?.toLowerCase()}), circuit terminé` : `Validée par ${evenement.auteur}`
    case 'REJET':
      return `Rejetée par ${evenement.auteur} : ${String(detail.motif)}`
    case 'EXPORT': {
      const envoi = detail.logiciel as { logiciel?: string; deja_envoyee?: boolean } | null
      if (envoi?.logiciel === 'odoo')
        return envoi.deja_envoyee
          ? `Déjà présente dans Odoo : rien n’a été recréé (${evenement.auteur})`
          : `Facture fournisseur créée dans Odoo par ${evenement.auteur}, PDF joint`
      return `Envoyée à la comptabilité par ${evenement.auteur}`
    }
    case 'FOURNISSEUR_ODOO':
      return detail.trouve ? `Fournisseur reconnu dans Odoo : ${String(detail.nom)}` : 'Fournisseur absent d’Odoo'
    case 'COMMANDE_ODOO':
      if (detail.statut === 'conforme') return `Conforme au bon de commande ${String(detail.commande)}`
      if (detail.statut === 'ecart') return `Écart avec le bon de commande ${String(detail.commande)}`
      return 'Aucun bon de commande dans Odoo'
    case 'ODOO_INDISPONIBLE':
      return `Odoo n’a pas répondu, fournisseur non vérifié : ${String(detail.raison)}`
    case 'EXPORT_ECHOUE':
      return `Envoi à la comptabilité échoué : ${String(detail.raison)}`
    default:
      return evenement.type
  }
}

/** « il y a 5 min », « il y a 2 h », puis la date. */
export function ilYA(iso: string, maintenant = Date.now()) {
  const secondes = Math.max(0, Math.round((maintenant - new Date(iso).getTime()) / 1000))
  if (secondes < 60) return 'à l’instant'
  if (secondes < 3600) return `il y a ${Math.floor(secondes / 60)} min`
  if (secondes < 86400) return `il y a ${Math.floor(secondes / 3600)} h`
  return JOUR.format(new Date(iso))
}

const HEURE_COURTE = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' })
const JOUR_COURT = new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit' })

/** « 14:09 » pour aujourd'hui, « 15/11 14:09 » pour un autre jour : sans le jour, 14:09 puis 01:00 semble à l'envers. */
export function heureCourte(iso: string, maintenant = new Date()) {
  const quand = new Date(iso)
  const heure = HEURE_COURTE.format(quand)
  return quand.toDateString() === maintenant.toDateString() ? heure : `${JOUR_COURT.format(quand)} ${heure}`
}

/** Durée lisible : 1,3 s au-dessus d'une seconde, 20 ms en dessous. */
export function duree(secondes: number) {
  if (secondes >= 3600) return `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(secondes / 3600)} h`
  if (secondes >= 60) return `${Math.round(secondes / 60)} min`
  if (secondes >= 1) return `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(secondes)} s`
  return secondes < 0.01 ? 'moins de 10 ms' : `${Math.round(secondes * 1000)} ms`
}

// Le même vocabulaire que l'éditeur de circuit : Réception, Lecture IA, Contrôles, Approbation.
export const ETAPES = ['Réception', 'Lecture IA', 'Contrôles', 'Approbation', 'Terminé'] as const

/** Où en est une facture dans le parcours : nombre d'étapes finies, et si l'étape en cours pose problème. */
export function avancement(etat: Etat): { faites: number; alerte: boolean } {
  switch (etat) {
    case 'recue':
      return { faites: 1, alerte: false }
    case 'echec':
      return { faites: 1, alerte: true }
    case 'extraite':
      return { faites: 2, alerte: false }
    case 'a_valider':
    case 'en_approbation':
      return { faites: 3, alerte: false }
    case 'en_anomalie':
      return { faites: 3, alerte: true }
    case 'validee':
      return { faites: 4, alerte: false }
    default:
      return { faites: 5, alerte: etat === 'rejetee' }
  }
}

/** Initiales d'un fournisseur pour sa pastille : « Garage Central Bertin » donne « GC ». */
export function initiales(nom: string | null) {
  const mots = (nom ?? '?').replace(/[^\p{L}\p{N} ]/gu, ' ').split(/\s+/).filter(Boolean)
  return (mots.length > 1 ? mots[0][0] + mots[1][0] : (mots[0] ?? '?').slice(0, 2)).toUpperCase()
}

/** Une teinte stable par fournisseur (8 teintes), pour reconnaître une ligne d'un coup d'œil. */
export function teinte(nom: string | null) {
  let somme = 0
  for (const lettre of nom ?? '') somme = (somme * 31 + lettre.charCodeAt(0)) >>> 0
  return somme % 8
}

/** L'ordre des groupes dans la liste : ce qui demande une action d'abord. */
export const ORDRE_ETATS: Etat[] = ['en_anomalie', 'echec', 'a_valider', 'en_approbation', 'recue', 'extraite', 'validee', 'exportee', 'rejetee']

/** Une échéance proche ou dépassée se signale. */
export function urgence(iso: string | null | undefined, maintenant = new Date()): 'depassee' | 'proche' | null {
  if (!iso) return null
  const jours = Math.floor((new Date(iso).getTime() - maintenant.getTime()) / 86400000)
  return jours < 0 ? 'depassee' : jours <= 3 ? 'proche' : null
}

// ───────── Ce qui demande une action (cartes de l'accueil, filtres des factures) ─────────

const HEURE_MS = 3600 * 1000

/** Les anomalies qui signalent un risque de fraude au changement d'IBAN (les mêmes codes que moteur/controles.py). */
export const CODES_RISQUE = ['IBAN_DIFFERENT', 'IBAN_NOUVEAU']

/** Un risque de fraude à l'IBAN sur une facture qui attend encore une décision. */
export const aRisque = (facture: FactureResume) => Boolean(facture.risque) && (facture.etat === 'a_valider' || facture.etat === 'en_approbation')

/** À régler : la facture est arrêtée aux contrôles, n'a pas pu être lue, ou porte un risque de fraude à l'IBAN. */
export const aRegler = (facture: FactureResume) => facture.etat === 'en_anomalie' || facture.etat === 'echec' || aRisque(facture)

/** Pour trier une liste : les factures à risque d'abord, l'ordre des autres inchangé (le tri est stable). */
export const risqueDabord = (a: FactureResume, b: FactureResume) => Number(aRisque(b)) - Number(aRisque(a))

/** L'échéance tombe dans 7 jours ou moins (ou est passée), et la facture n'est ni envoyée en comptabilité ni rejetée. */
export function echeanceProche(facture: FactureResume, maintenant = new Date()) {
  if (!facture.date_echeance || facture.etat === 'exportee' || facture.etat === 'rejetee') return false
  return new Date(facture.date_echeance).getTime() - maintenant.getTime() <= 7 * 24 * HEURE_MS
}

/** Une approbation attendue depuis plus de 48 heures. */
export function attenteLongue(facture: FactureResume, maintenant = new Date()) {
  if (facture.etat !== 'a_valider' && facture.etat !== 'en_approbation') return false
  return maintenant.getTime() - new Date(facture.cree_le).getTime() > 48 * HEURE_MS
}
