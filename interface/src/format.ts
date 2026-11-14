import type { Etat, Evenement } from './api'

const EUROS = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' })
const NOMBRE = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 4 })
const JOUR = new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
const HEURE = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export const euros = (montant: string | null) => (montant === null ? 'Non lu' : EUROS.format(Number(montant)))
export const nombre = (valeur: string | null) => (valeur === null ? 'Non lu' : NOMBRE.format(Number(valeur)))
export const jour = (iso: string | null) => (iso === null ? 'Non lue' : JOUR.format(new Date(iso)))
export const heure = (iso: string) => HEURE.format(new Date(iso))
export const jourEtHeure = (iso: string) => `${JOUR.format(new Date(iso))} à ${HEURE.format(new Date(iso))}`

export function siret(valeur: string | null) {
  if (valeur === null) return 'Non lu'
  return valeur.length === 14 ? `${valeur.slice(0, 3)} ${valeur.slice(3, 6)} ${valeur.slice(6, 9)} ${valeur.slice(9)}` : valeur
}

export const LIBELLE_ETAT: Record<Etat, string> = {
  recue: 'Reçue',
  extraite: 'Extraite',
  a_valider: 'À valider',
  en_anomalie: 'En anomalie',
  validee: 'Validée',
  rejetee: 'Rejetée',
  exportee: 'Exportée',
  echec: 'Lecture impossible',
}

export const A_TRAITER: Etat[] = ['en_anomalie', 'echec', 'a_valider', 'recue', 'extraite']

/** Phrase lisible pour une ligne du journal. */
export function raconter(evenement: Evenement): string {
  const detail = evenement.detail
  switch (evenement.type) {
    case 'RECEPTION':
      return 'Fichier reçu'
    case 'EXTRACTION':
      if (detail.source === 'factur-x') return 'Facture électronique Factur-X : données lues directement, sans IA'
      return `Données lues par l’IA en ${NOMBRE.format(Number(detail.duree_s))} s (${String(detail.modele)})`
    case 'FACTURX_ILLISIBLE':
      return `Factur-X illisible, lecture confiée à l’IA : ${String(detail.raison)}`
    case 'CONTROLE': {
      const anomalies = (detail.anomalies as string[] | undefined) ?? []
      if (anomalies.length === 0) return 'Contrôles passés sans anomalie'
      return anomalies.length === 1 ? 'Contrôles : 1 anomalie trouvée' : `Contrôles : ${anomalies.length} anomalies trouvées`
    }
    case 'DOUBLON_FICHIER':
      return 'Même fichier renvoyé : reconnu, rien n’a été refait'
    case 'NOUVEL_ESSAI':
      return 'Nouvel essai de lecture'
    case 'EXTRACTION_ECHOUEE':
    case 'LECTURE_IMPOSSIBLE':
      return String(detail.raison ?? 'Lecture impossible')
    case 'VALIDATION':
      return `Validée par ${evenement.auteur}`
    case 'REJET':
      return `Rejetée par ${evenement.auteur} : ${String(detail.motif)}`
    case 'EXPORT':
      return `Envoyée à la comptabilité par ${evenement.auteur}`
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

export const heureCourte = (iso: string) => new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' }).format(new Date(iso))

/** Durée lisible : 1,3 s au-dessus d'une seconde, 20 ms en dessous. */
export function duree(secondes: number) {
  if (secondes >= 1) return `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(secondes)} s`
  return secondes < 0.01 ? 'moins de 10 ms' : `${Math.round(secondes * 1000)} ms`
}

export const ETAPES = ['Réception', 'Analyse IA', 'Contrôle', 'Validation', 'Terminé'] as const

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
      return { faites: 3, alerte: false }
    case 'en_anomalie':
      return { faites: 3, alerte: true }
    case 'validee':
      return { faites: 4, alerte: false }
    default:
      return { faites: 5, alerte: etat === 'rejetee' }
  }
}
