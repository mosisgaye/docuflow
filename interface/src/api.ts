// Appels à l'API du moteur. Toutes les routes passent par /api.

export type Etat = 'recue' | 'extraite' | 'a_valider' | 'en_anomalie' | 'validee' | 'rejetee' | 'exportee' | 'echec'

export interface Ligne {
  designation: string
  quantite: string
  prix_unitaire_ht: string
  montant_ht: string
}

export interface Donnees {
  numero_facture: string | null
  date_facture: string | null
  date_echeance: string | null
  fournisseur_nom: string | null
  fournisseur_siret: string | null
  fournisseur_tva: string | null
  client_nom: string | null
  lignes: Ligne[]
  total_ht: string | null
  taux_tva: string | null
  total_tva: string | null
  total_ttc: string | null
}

export interface Anomalie {
  code: string
  gravite: 'bloquante' | 'avertissement'
  message: string
  champ: string | null
}

export interface Evenement {
  rang: number
  type: string
  etat: Etat
  auteur: string
  detail: Record<string, unknown>
  cree_le: string
}

export interface FactureResume {
  id: string
  nom_fichier: string
  etat: Etat
  numero_facture: string | null
  fournisseur_siret: string | null
  fournisseur_nom: string | null
  total_ttc: string | null
  nb_anomalies: number
  cree_le: string
}

export interface FactureDetail extends FactureResume {
  donnees: Donnees | null
  anomalies: Anomalie[]
  evenements: Evenement[]
}

export interface FactureDeposee extends FactureDetail {
  deja_vue: boolean
}

export interface Activite extends Evenement {
  facture_id: string
  numero_facture: string | null
  nom_fichier: string
}

export interface Statistiques {
  total: number
  par_etat: Record<Etat, number>
  conformes: number
  anomalies_detectees: number
  duree_moyenne_s: number | null
  lues_sans_ia: number
  durees_recentes_s: number[]
  recentes: FactureResume[]
  activite: Activite[]
}

async function appeler<T>(chemin: string, options?: RequestInit): Promise<T> {
  let reponse: Response
  try {
    reponse = await fetch(`/api${chemin}`, options)
  } catch {
    throw new Error('Le moteur ne répond pas. Vérifiez qu’il est démarré.')
  }
  if (!reponse.ok) {
    let message = `Le moteur a répondu ${reponse.status}.`
    try {
      const corps = await reponse.json()
      if (typeof corps.detail === 'string') message = corps.detail
    } catch {
      // Réponse sans JSON : on garde le message par défaut.
    }
    throw new Error(message)
  }
  return reponse.json() as Promise<T>
}

const enJson = (corps: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(corps),
})

export const statistiques = () => appeler<Statistiques>('/statistiques')
export const lister = () => appeler<FactureResume[]>('/factures')
export const detailler = (id: string) => appeler<FactureDetail>(`/factures/${id}`)
export const valider = (id: string, auteur: string) => appeler<FactureDetail>(`/factures/${id}/validation`, enJson({ auteur }))
export const rejeter = (id: string, auteur: string, motif: string) =>
  appeler<FactureDetail>(`/factures/${id}/rejet`, enJson({ auteur, motif }))
export const exporter = (id: string, auteur: string) => appeler<FactureDetail>(`/factures/${id}/export`, enJson({ auteur }))
export const adresseExport = (id: string) => `/api/factures/${id}/export`
export const adresseFichier = (id: string) => `/api/factures/${id}/fichier#toolbar=0&navpanes=0&view=FitH`

export function deposer(fichier: File) {
  const formulaire = new FormData()
  formulaire.append('fichier', fichier)
  return appeler<FactureDeposee>('/factures', { method: 'POST', body: formulaire })
}
