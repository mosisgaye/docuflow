// Appels à l'API du moteur. Toutes les routes passent par /api.

export type Etat = 'recue' | 'extraite' | 'a_valider' | 'en_approbation' | 'en_anomalie' | 'validee' | 'rejetee' | 'exportee' | 'echec'

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
  fournisseur_iban?: string | null
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
  date_echeance?: string | null
  nb_anomalies: number
  risque?: boolean // risque de fraude à l'IBAN : en tête des listes, approbation avec confirmation
  cree_le: string
  niveau_attendu?: Niveau | null // à qui c'est le tour d'approuver
  approuve_par?: string[] // qui a déjà approuvé (personne n'approuve deux niveaux)
}

export type Niveau = 'comptable' | 'directeur_financier' | 'gerant'

/** Qui doit approuver une facture, et pourquoi : calculé par les règles d'approbation. */
export interface Circuit {
  version: number | null
  niveaux: { niveau: Niveau; raisons: string[] }[]
  bloque: string | null
  /** Le chemin suivi dans le circuit dessiné, en clair (absent pour les versions d'avant l'éditeur). */
  etapes?: {
    id: string
    type: 'debut' | 'condition' | 'approbation' | 'blocage' | 'fin'
    nom: string
    sortie: 'oui' | 'non' | null
    condition: string | null
    niveau: Niveau | null
    message: string | null
  }[]
}

export interface FactureDetail extends FactureResume {
  donnees: Donnees | null
  anomalies: Anomalie[]
  evenements: Evenement[]
  circuit: Circuit | null
  approbations: { niveau: Niveau; personne: string; cree_le: string }[]
  niveau_attendu: Niveau | null
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
  lues_par_ia: number
  durees_recentes_s: number[]
  recentes: FactureResume[]
  activite: Activite[]
}

export const EVENEMENT_ACCES = 'docuflow:acces-requis'
export const EVENEMENT_CONNEXION = 'verifac:connexion-requise'

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
      // Code d'accès de la démonstration absent ou périmé : l'application affiche l'écran d'entrée.
      if (reponse.status === 401 && corps.acces) window.dispatchEvent(new Event(EVENEMENT_ACCES))
      // Session de compte absente ou expirée : l'application affiche l'écran de connexion.
      if (reponse.status === 401 && reponse.headers.get('X-Verifac-Connexion') === 'requise') window.dispatchEvent(new Event(EVENEMENT_CONNEXION))
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
export const valider = (id: string, auteur: string, fournisseurAppele = false) =>
  appeler<FactureDetail>(`/factures/${id}/validation`, enJson({ auteur, fournisseur_appele: fournisseurAppele }))
export const rejeter = (id: string, auteur: string, motif: string) =>
  appeler<FactureDetail>(`/factures/${id}/rejet`, enJson({ auteur, motif }))
export const exporter = (id: string, auteur: string) => appeler<FactureDetail>(`/factures/${id}/export`, enJson({ auteur }))
export const adresseExport = (id: string) => `/api/factures/${id}/export`
export const adresseFichier = (id: string) => `/api/factures/${id}/fichier#toolbar=0&navpanes=0&view=FitH`

export class LectureTropLongue extends Error {}

/**
 * Attend que le travailleur ait lu la facture (elle quitte l'état « reçue »).
 * Le dépôt répond tout de suite ; la lecture se fait à part, en une ou deux secondes en général.
 */
export async function attendreLecture(id: string, delaiMaxS = 60): Promise<FactureDetail> {
  const limite = Date.now() + delaiMaxS * 1000
  for (;;) {
    const facture = await detailler(id)
    if (facture.etat !== 'recue') return facture
    if (Date.now() > limite) {
      throw new LectureTropLongue('La lecture est toujours en attente. Le travailleur est-il démarré ? (uv run python -m moteur.travailleur)')
    }
    await new Promise((resoudre) => setTimeout(resoudre, 1000))
  }
}

export function deposer(fichier: File) {
  const formulaire = new FormData()
  formulaire.append('fichier', fichier)
  return appeler<FactureDeposee>('/factures', { method: 'POST', body: formulaire })
}

// ───────── Connecteurs ─────────

export type StatutConnecteur = 'disponible' | 'preversion' | 'a_confirmer' | 'bientot'

export interface Connecteur {
  id: string
  nom: string
  editeur: string
  description: string
  usages: string[]
  statut: StatutConnecteur
  connexion: 'oauth' | 'cle_api'
  note: string
  documentation: string
  branche: boolean
  outils_autorises: string[] | null
  branche_par: string | null
  branche_le: string | null
  connexion_prete: boolean
}

export interface OutilConnecteur {
  nom: string
  description: string
  lecture: boolean
  autorise: boolean
}

export interface AppelConnecteur {
  outil: string
  arguments: Record<string, unknown>
  statut: 'ok' | 'erreur' | 'refuse'
  detail: string | null
  duree_ms: number | null
  cree_le: string
}

export interface FicheConnecteur extends Connecteur {
  outils: OutilConnecteur[]
  erreur: string | null
  appels: AppelConnecteur[]
}

export const connecteurs = () => appeler<Connecteur[]>('/connecteurs')
export const ficheConnecteur = (id: string) => appeler<FicheConnecteur>(`/connecteurs/${id}`)
export const brancher = (id: string, auteur: string) => appeler<Connecteur>(`/connecteurs/${id}/branchement`, enJson({ auteur }))
export const debrancher = (id: string) => appeler<Connecteur>(`/connecteurs/${id}/branchement`, { method: 'DELETE' })
export const commencerConnexion = (id: string, auteur: string) => appeler<{ adresse: string }>(`/connecteurs/${id}/oauth`, enJson({ auteur }))
export const autoriserOutils = (id: string, autorises: string[] | null) =>
  appeler<Connecteur>(`/connecteurs/${id}/outils`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ autorises }) })

// ───────── Accès développeurs : clés de l'API publique et événements sortants ─────────

export interface CleApi {
  id: string
  nom: string
  debut: string
  droits: string[]
  creee_par: string
  creee_le: string
  utilisee_le: string | null
  revoquee_le: string | null
}

export interface LivraisonSortante {
  id: string
  evenement: string
  etat: 'en_attente' | 'livree' | 'abandonnee'
  tentatives: number
  reponse: string | null
  cree_le: string
  prochain_essai_le: string | null
}

export interface AbonnementSortant {
  id: string
  url: string
  evenements: string[]
  actif: boolean
  cree_par: string
  cree_le: string
  livraisons: LivraisonSortante[]
}

const supprimer: RequestInit = { method: 'DELETE' }

export const clesApi = () => appeler<{ droits: Record<string, string>; cles: CleApi[] }>('/cles-api')
export const creerCle = (nom: string, droits: string[], auteur: string) => appeler<CleApi & { cle: string }>('/cles-api', enJson({ nom, droits, auteur }))
export const revoquerCle = (id: string) => appeler<CleApi>(`/cles-api/${id}`, supprimer)
export const abonnements = () => appeler<{ evenements: Record<string, string>; abonnements: AbonnementSortant[] }>('/abonnements')
export const creerAbonnement = (url: string, evenements: string[], auteur: string) =>
  appeler<AbonnementSortant & { secret: string }>('/abonnements', enJson({ url, evenements, auteur }))
export const essayerAbonnement = (id: string) => appeler<AbonnementSortant>(`/abonnements/${id}/essai`, { method: 'POST' })
export const arreterAbonnement = (id: string) => appeler<{ id: string }>(`/abonnements/${id}`, supprimer)

// ───────── Code d'accès de la démonstration ─────────

export interface EtatAcces {
  requis: boolean
  ouvert: boolean
}

export const etatAcces = () => appeler<EtatAcces>('/acces')
export const entrer = (code: string) => appeler<EtatAcces>('/acces', enJson({ code }))
export const sortir = () => appeler<EtatAcces>('/acces', { method: 'DELETE' })

// ───────── Les comptes : connexion par lien ou par code ─────────

export type Role = 'administrateur' | 'membre' | 'approbateur' | 'lecture' | 'operateur'
export type Droit = 'voir' | 'approuver' | 'traiter' | 'circuit' | 'agent' | 'administrer' | 'operer'

export interface Compte {
  id: string
  nom: string
  email: string
  role: Role
  libelle_role: string
  niveaux: Niveau[]
  actif: boolean
  derniere_connexion: string | null
  droits: Droit[]
}

export const moi = () => appeler<{ compte: Compte | null; comptes: boolean; demo?: boolean }>('/moi')
export type DemandePilote = {
  id: string
  nom: string
  entreprise: string
  email: string
  volume: string
  logiciel: string
  message: string | null
  cree_le: string
}
export const demandesPilote = () => appeler<{ demandes: DemandePilote[] }>('/pilote/demandes')
export const entrerDansLaDemo = () => appeler<{ compte: Compte }>('/connexion/demo', { method: 'POST' })
export const demanderConnexion = (email: string) => appeler<{ message: string }>('/connexion/demande', enJson({ email }))
export const connexionParLien = (jeton: string) => appeler<{ compte: Compte }>('/connexion/lien', enJson({ jeton }))
export const connexionParCode = (email: string, code: string) => appeler<{ compte: Compte }>('/connexion/code', enJson({ email, code }))
export const deconnexion = () => appeler<{ compte: null }>('/deconnexion', { method: 'POST' })

export interface ListeComptes {
  roles: Record<Exclude<Role, 'operateur'>, string>
  niveaux: Record<Niveau, string>
  comptes: Compte[]
}

export const comptes = () => appeler<ListeComptes>('/comptes')
export const creerCompte = (nom: string, email: string, role: Role, niveaux: Niveau[]) => appeler<Compte>('/comptes', enJson({ nom, email, role, niveaux }))
export const modifierCompte = (id: string, changement: { role?: Role; niveaux?: Niveau[]; actif?: boolean }) =>
  appeler<Compte>(`/comptes/${id}`, { ...enJson(changement), method: 'PUT' })
export const deconnecterCompte = (id: string) => appeler<Compte>(`/comptes/${id}/deconnexion`, { method: 'POST' })

// ───────── La Console de l'opérateur Verifac ─────────

export interface EtatConsole {
  sante: { base: string; file_en_attente: number; plus_ancienne_attente_s: number | null; derniere_tache_traitee: string | null; lectures_abandonnees: number }
  version: { code: string | null; migration: string | null }
  usage: {
    jours: { jour: string; factures: number }[]
    factures_30_jours: number
    factures_total: number
    par_etat: Partial<Record<Etat, number>>
    comptes_actifs: number
    administrateurs: number
    derniere_connexion: string | null
  }
  ia: { lectures_30_jours: number; modeles: Record<string, number>; jetons_entree: number; jetons_sortie: number; cout_30_jours_eur: number | null; prix_renseigne: boolean }
  incidents: { type: 'lecture' | 'mail'; facture_id: string; message: string; le: string | null }[]
}

export const etatConsole = () => appeler<EtatConsole>('/console')
export const premierAdministrateur = (nom: string, email: string) => appeler<Compte>('/console/premier-administrateur', enJson({ nom, email }))

// ───────── Réglages : l'équipe qui approuve, et la réception des factures ─────────

export interface MembreEquipe {
  id: string
  nom: string
  email: string
  niveau: Niveau
  cree_par: string
  cree_le: string
}

export interface MailRecu {
  id: string
  expediteur: string
  objet: string
  statut: 'traite' | 'sans_facture'
  recu_le: string
  factures: number
  texte: string | null
}

export const equipe = () => appeler<{ niveaux: Record<Niveau, string>; membres: MembreEquipe[] }>('/reglages/equipe')
export const ajouterMembre = (nom: string, email: string, niveau: Niveau, auteur: string) =>
  appeler<MembreEquipe>('/reglages/equipe', enJson({ nom, email, niveau, auteur }))
export const retirerMembre = (id: string) => appeler<{ id: string }>(`/reglages/equipe/${id}`, { method: 'DELETE' })
export const reception = () => appeler<{ adresse: string; active: boolean; mails: MailRecu[] }>('/reglages/reception')

// ───────── Éditeur de circuit : brouillon, test, publication, versions, exécutions ─────────

export type Comparaison = 'superieur_a' | 'superieur_ou_egal_a' | 'inferieur_a' | 'inferieur_ou_egal_a' | 'egal_a' | 'different_de' | 'contient' | 'une_de' | 'aucune_de'
export type ChampCondition = 'total_ttc' | 'total_ht' | 'fournisseur_nom' | 'fournisseur_siret' | 'anomalie'

export interface LigneCondition {
  champ: ChampCondition
  comparaison: Comparaison
  valeur: string | string[]
}

/** Une condition : « toujours », ou des lignes reliées par « une suffit » ou « toutes ». */
export interface Condition {
  toujours?: boolean
  lignes?: LigneCondition[]
  combinaison?: 'une' | 'toutes'
}

export interface Regle {
  nom: string
  si: Condition
  exige?: Niveau[]
  bloque?: string
}

export interface Relance {
  delai_h: number
  delai_urgent_h: number
  maximum: number
}

export type Relances = Partial<Record<Niveau, Relance>>

export interface Catalogue {
  champs: { champ: ChampCondition; libelle: string; genre: 'montant' | 'texte' | 'anomalies'; comparaisons: { code: Comparaison; libelle: string }[] }[]
  anomalies: { code: string; libelle: string; gravite: 'bloquante' | 'avertissement'; utilisable: boolean }[]
  niveaux: { code: Niveau; libelle: string }[]
  relances: { nom: keyof Relance; libelle: string; unite: string; min: number; max: number; defaut: number }[]
  etapes: { type: string; libelle: string; description: string; fixe: boolean; disponible?: boolean }[]
}

export type TypeEtape = 'debut' | 'condition' | 'approbation' | 'blocage' | 'fin'

/** Une étape du circuit dessiné, comme un nœud de n8n. */
export interface NoeudGraphe {
  id: string
  type: TypeEtape
  x: number
  y: number
  nom?: string
  si?: Condition
  niveau?: Niveau
  message?: string
}

export interface LienGraphe {
  de: string
  vers: string
  sortie: 'oui' | 'non' | null
}

export interface Graphe {
  noeuds: NoeudGraphe[]
  liens: LienGraphe[]
}

export interface BrouillonCircuit {
  version_en_service: number | null
  graphe: Graphe
  a_completer: string | null // ce qui manque pour publier ; null : le circuit est complet
  relances: Relances | null
  modifie: boolean
  modifie_par: string | null
  modifie_le: string | null
}

export interface Changement {
  genre: 'ajout' | 'retrait' | 'modification' | 'lien' | 'relances'
  etape: string | null
  niveau?: Niveau
  avant: string | null
  apres: string | null
  texte: string
}

export interface ResultatTest {
  facture: { id: string; fournisseur: string | null; numero: string | null; total_ttc: string | null }
  circuit_teste: 'brouillon' | 'en_service'
  controles: { arretee: boolean; anomalies: { code: string; libelle: string; gravite: string | null }[] }
  chemin: { id: string; sortie: 'oui' | 'non' | null }[]
  conditions: { id: string; nom: string; vraie: boolean; lignes: { texte: string; vraie: boolean }[] }[]
  niveaux: { niveau: Niveau; raisons: string[] }[]
  bloque: string | null
  relances: Relances
  en_service: { version: number | null; niveaux: Niveau[]; bloque: string | null }
  change: boolean
}

export interface VersionCircuit {
  version: number
  en_service: boolean
  publie_par: string
  publie_le: string
  nombre_etapes: number | null
  nombre_regles: number
  changements: string[] | null
  relances_reglees: boolean
}

export interface Execution {
  facture_id: string
  fournisseur: string | null
  numero: string | null
  total_ttc: string | null
  etat: Etat
  version_circuit: number | null
  chemin: string[]
  resultat: string
  en_cours: boolean
  duree_s: number
  recue_le: string
}

export const catalogueCircuit = () => appeler<Catalogue>('/circuit/catalogue')
export const brouillon = () => appeler<BrouillonCircuit>('/circuit/brouillon')
export const enregistrerBrouillon = (graphe: Graphe, relances: Relances | null, auteur: string) =>
  appeler<BrouillonCircuit>('/circuit/brouillon', { ...enJson({ auteur, graphe, relances }), method: 'PUT' })
export const annulerBrouillon = () => appeler<BrouillonCircuit>('/circuit/brouillon', supprimer)
export const differences = () => appeler<{ version_en_service: number | null; modifie: boolean; changements: Changement[] }>('/circuit/differences')
export const publierCircuit = (auteur: string) => appeler<{ version: number; publie_par: string; changements: string[] }>('/circuit/publier', enJson({ auteur }))
export const testerCircuit = (factureId: string) => appeler<ResultatTest>('/circuit/tester', enJson({ facture_id: factureId }))
export const versionsCircuit = () => appeler<{ versions: VersionCircuit[] }>('/circuit/versions')
export const executions = (limite = 30) => appeler<{ executions: Execution[] }>(`/circuit/executions?limite=${limite}`)
