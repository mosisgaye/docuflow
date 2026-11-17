import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type EvenementAgent, type MessageAgent, parler } from './agent'
import * as api from './api'
import type { Etat, FactureDetail, FactureResume, Statistiques } from './api'
import { Conversation, type Tour } from './Conversation'
import { Fiche, Journal, Tampon } from './Fiche'
import { A_TRAITER, LIBELLE_ETAT, ORDRE_ETATS, aRegler, attenteLongue, echeanceProche, euros, initiales, raconter, teinte } from './format'
import { Icone, type NomIcone } from './Icones'
import { IconeAgent } from './IconeAgent'
import { Connecteurs, type OngletConnecteurs } from './Connecteurs'
import { Documents } from './Pages'
import { EcranAcces } from './EcranAcces'
import { type OngletReglages, Reglages } from './Reglages'
import { TableauDeBord } from './TableauDeBord'
import { type OngletWorkflow, Workflow } from './Workflow'
import { type Theme, retenirTheme } from './theme'

type Page = 'tableau' | 'documents' | 'workflow' | 'connecteurs' | 'reglages'
// « À traiter » est un filtre des factures (comme « Non lus » dans une boîte mail), pas une page à part.
type Vue = Etat | 'toutes' | 'a_traiter' | 'mon_tour' | 'a_regler' | 'echeances' | 'attente'

const CLE_AUTEUR = 'factures.auteur'
const MENU: { page: Page; nom: string; icone: NomIcone }[] = [
  { page: 'tableau', nom: 'Accueil', icone: 'accueil' },
  { page: 'documents', nom: 'Factures', icone: 'document' },
  { page: 'workflow', nom: 'Workflow', icone: 'workflow' },
  { page: 'connecteurs', nom: 'Connecteurs', icone: 'integration' },
  { page: 'reglages', nom: 'Réglages', icone: 'reglages' },
]
const ONGLETS_CONNECTEURS: { onglet: OngletConnecteurs; nom: string; icone: NomIcone }[] = [
  { onglet: 'mes', nom: 'Mes connecteurs', icone: 'integration' },
  { onglet: 'decouvrir', nom: 'Découvrir', icone: 'grille' },
  { onglet: 'integres', nom: 'Intégrés à Verifac', icone: 'bouclier' },
  { onglet: 'developpeurs', nom: 'Accès développeurs', icone: 'code' },
]
// Les filtres qui viennent des cartes de l'accueil : affichés seulement s'ils ont des factures.
const AUTRES_FILTRES: { vue: 'a_regler' | 'echeances' | 'attente'; nom: string; icone: NomIcone; garder: (facture: FactureResume) => boolean }[] = [
  { vue: 'a_regler', nom: 'Anomalies à régler', icone: 'anomalie', garder: (facture) => aRegler(facture) },
  { vue: 'echeances', nom: 'Échéance sous 7 jours', icone: 'horloge', garder: (facture) => echeanceProche(facture) },
  { vue: 'attente', nom: 'En attente depuis 48 h', icone: 'utilisateur', garder: (facture) => attenteLongue(facture) },
]
const TITRES_VUES = {
  mon_tour: ['Mon tour', 'Les factures où c’est à vous d’approuver maintenant. A approuve, R rejette, les flèches passent à la suivante.'],
  a_traiter: ['À traiter', 'Les factures qui attendent une décision, les anomalies en premier.'],
  toutes: ['Toutes les factures', 'Cliquez sur une facture pour l’ouvrir à côté de la liste.'],
  a_regler: ['Anomalies à régler', 'Arrêtées aux contrôles ou illisibles : à corriger, ou à rejeter avec un motif.'],
  echeances: ['Échéance sous 7 jours', 'À traiter en priorité : une facture payée en retard coûte des pénalités.'],
  attente: ['En attente depuis plus de 48 h', 'Une approbation tarde. Une relance part toute seule ; un appel va parfois plus vite.'],
} as const
const FORMATS_ACCEPTES = /\.(pdf|jpe?g|png|webp)$/i
const lire = (cle: string) => {
  try {
    return localStorage.getItem(cle)
  } catch {
    return null
  }
}
const ecrire = (cle: string, valeur: string) => {
  try {
    localStorage.setItem(cle, valeur)
  } catch {
    // Sans stockage, le réglage vaut pour cette visite.
  }
}
let prochainId = 1
// Un nom comparable : sans majuscules ni espaces en trop (« claire  FABRE » = « Claire Fabre »).
const normaliser = (nom: string) => nom.trim().replace(/\s+/g, ' ').toLowerCase()

const tourVide = (role: Tour['role'], champs: Partial<Tour> = {}): Tour => ({
  id: prochainId++,
  role,
  texte: '',
  etapes: [],
  propositions: [],
  enCours: role === 'assistant',
  ...champs,
})

/** Au retour d'une connexion par compte (OAuth), l'éditeur renvoie ici avec le résultat dans l'adresse. */
function retourConnexion(): string | null {
  const parametres = new URLSearchParams(window.location.search)
  const resultat = parametres.get('oauth')
  if (!resultat) return null
  window.history.replaceState(null, '', window.location.pathname)
  if (resultat === 'ok') return `Compte connecté : ${parametres.get('connecteur') ?? 'le connecteur'} est branché, l’assistant peut y chercher.`
  if (resultat === 'refuse') return 'Connexion annulée : rien n’a été branché.'
  return 'La connexion du compte a échoué. Réessayez ; le détail est dans le journal du serveur.'
}

export function Application() {
  const [messageConnexion] = useState(retourConnexion)
  const [page, setPage] = useState<Page>(messageConnexion ? 'connecteurs' : 'tableau')
  const [factures, setFactures] = useState<FactureResume[]>([])
  const [statistiques, setStatistiques] = useState<Statistiques | null>(null)
  const [vedette, setVedette] = useState<FactureDetail | null>(null)
  const [detail, setDetail] = useState<FactureDetail | null>(null)
  const [onglet, setOnglet] = useState<'donnees' | 'document' | 'journal'>('donnees')
  const [vue, setVue] = useState<Vue>('a_traiter')
  const [ongletConnecteurs, setOngletConnecteurs] = useState<OngletConnecteurs | null>(null)
  const [ongletReglages, setOngletReglages] = useState<OngletReglages>('equipe')
  const [ongletWorkflow, setOngletWorkflow] = useState<OngletWorkflow>('circuit')
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'))
  const [laterale, setLaterale] = useState(() => lire('docuflow.laterale') !== 'repliee')
  // L'agent IA : un panneau à droite, ouvert depuis l'icône du haut, sur toutes les pages.
  const [agentOuvert, setAgentOuvert] = useState(false)
  // null : on ne sait pas encore ; vrai : le code d'accès de la démonstration est demandé.
  const [verrouille, setVerrouille] = useState<boolean | null>(null)
  const champRecherche = useRef<HTMLInputElement>(null)
  const [tours, setTours] = useState<Tour[]>([])
  const [recherche, setRecherche] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [information, setInformation] = useState<string | null>(null)
  const [enService, setEnService] = useState<boolean | null>(null)
  const [occupe, setOccupe] = useState(false)
  const [decision, setDecision] = useState(false)
  const [depotEnCours, setDepotEnCours] = useState<string | null>(null)
  const [survol, setSurvol] = useState(false)
  const [auteur, setAuteur] = useState(() => lire(CLE_AUTEUR) ?? '')
  const [branches, setBranches] = useState<string[]>([])
  const [equipe, setEquipe] = useState<api.MembreEquipe[]>([])
  const rechargerConnecteurs = useCallback(() => {
    api.connecteurs().then(
      (liste) => setBranches(liste.filter((connecteur) => connecteur.branche).map((connecteur) => connecteur.nom)),
      () => setBranches([]),
    )
  }, [])
  const champAuteur = useRef<HTMLInputElement>(null)
  const champFichier = useRef<HTMLInputElement>(null)
  const toursActuels = useRef(tours)
  toursActuels.current = tours
  const derniereOuverture = useRef(0)

  // Qui je suis : mon nom (en haut à droite) retrouvé dans « Mon équipe » donne mes rôles d'approbation.
  const mesNiveaux = useMemo(() => {
    const moi = normaliser(auteur)
    return moi ? equipe.filter((membre) => normaliser(membre.nom) === moi).map((membre) => membre.niveau) : []
  }, [equipe, auteur])
  const monTour = useCallback(
    (facture: FactureResume) =>
      Boolean(facture.niveau_attendu && mesNiveaux.includes(facture.niveau_attendu) && !(facture.approuve_par ?? []).some((nom) => normaliser(nom) === normaliser(auteur))),
    [mesNiveaux, auteur],
  )
  const aMonTour = useMemo(() => factures.filter(monTour), [factures, monTour])

  const aTraiter = useMemo(
    () => factures.filter((facture) => A_TRAITER.includes(facture.etat)).sort((a, b) => A_TRAITER.indexOf(a.etat) - A_TRAITER.indexOf(b.etat)),
    [factures],
  )

  const recharger = useCallback(async () => {
    try {
      const [liste, chiffres] = await Promise.all([api.lister(), api.statistiques()])
      setFactures(liste)
      setStatistiques(chiffres)
      setEnService(true)
      return liste
    } catch (probleme) {
      setEnService(false)
      setErreur((probleme as Error).message)
      return null
    }
  }, [])

  useEffect(() => {
    api.etatAcces().then(
      (etat) => setVerrouille(etat.requis && !etat.ouvert),
      () => setVerrouille(false), // moteur injoignable : l'écran normal le dira
    )
    const fermer = () => setVerrouille(true)
    window.addEventListener(api.EVENEMENT_ACCES, fermer)
    return () => window.removeEventListener(api.EVENEMENT_ACCES, fermer)
  }, [])

  useEffect(() => {
    if (verrouille === false) {
      setErreur(null)
      recharger()
      rechargerConnecteurs()
      api.equipe().then((reponse) => setEquipe(reponse.membres), () => setEquipe([]))
    }
  }, [verrouille, recharger, rechargerConnecteurs])

  useEffect(() => {
    ecrire(CLE_AUTEUR, auteur)
  }, [auteur])

  // La facture mise en avant sur le tableau de bord : celle qu'on vient de déposer,
  // sinon la première à traiter, sinon la plus récente.
  const [derniereDeposee, setDerniereDeposee] = useState<string | null>(null)
  const vedetteId = (derniereDeposee && factures.some((facture) => facture.id === derniereDeposee) ? derniereDeposee : null) ?? aTraiter[0]?.id ?? factures[0]?.id ?? null
  const etatVedette = factures.find((facture) => facture.id === vedetteId)?.etat
  useEffect(() => {
    if (!vedetteId) return setVedette(null)
    let annule = false
    api
      .detailler(vedetteId)
      .then((facture) => !annule && setVedette(facture))
      .catch(() => undefined)
    return () => {
      annule = true
    }
  }, [vedetteId, etatVedette])

  const ouvrir = useCallback(async (id: string | null) => {
    // Si plusieurs ouvertures se suivent, seule la dernière demandée s'affiche.
    const demande = ++derniereOuverture.current
    if (!id) return setDetail(null)
    try {
      const facture = await api.detailler(id)
      if (demande === derniereOuverture.current) setDetail(facture)
    } catch (probleme) {
      setErreur((probleme as Error).message)
    }
  }, [])

  const modifierTour = useCallback((id: number, modifier: (tour: Tour) => Tour) => {
    setTours((actuels) => actuels.map((tour) => (tour.id === id ? modifier(tour) : tour)))
  }, [])

  /** Envoie l'historique à l'assistant et remplit le tour `reponseId` au fil de l'eau. */
  const interroger = useCallback(
    async (historique: MessageAgent[], reponseId: number, factureId: string | null) => {
      const recevoir = (evenement: EvenementAgent) => {
        if (evenement.type === 'facture') return void ouvrir(evenement.id)
        modifierTour(reponseId, (tour) => {
          switch (evenement.type) {
            case 'texte':
              return { ...tour, texte: tour.texte + evenement.contenu }
            case 'outil':
              return evenement.etat === 'debut'
                ? { ...tour, etapes: [...tour.etapes, { id: evenement.id, libelle: evenement.libelle ?? '', fini: false }] }
                : { ...tour, etapes: tour.etapes.map((etape) => (etape.id === evenement.id ? { ...etape, fini: true, duree: evenement.duree_s, echec: evenement.echec } : etape)) }
            case 'proposition':
              return {
                ...tour,
                propositions: [...tour.propositions, { factureId: evenement.facture_id, numero: evenement.numero, decision: evenement.decision, motif: evenement.motif, statut: 'attente' }],
              }
            case 'erreur':
              return { ...tour, erreur: evenement.message }
            default:
              return { ...tour, enCours: false }
          }
        })
      }
      await parler(historique, factureId, auteur.trim() || null, recevoir)
      modifierTour(reponseId, (tour) => ({ ...tour, enCours: false }))
    },
    [modifierTour, ouvrir, auteur],
  )

  const historique = (supplement: MessageAgent): MessageAgent[] => [
    ...toursActuels.current.map((tour) => ({ role: tour.role, content: tour.envoye ?? tour.texte })).filter((message) => message.content.trim()),
    supplement,
  ]

  const envoyer = useCallback(
    async (texte: string) => {
      const reponse = tourVide('assistant')
      const messages = historique({ role: 'user', content: texte })
      setTours((actuels) => [...actuels, tourVide('user', { texte }), reponse])
      setOccupe(true)
      await interroger(messages, reponse.id, detail?.id ?? null)
      setOccupe(false)
    },
    [interroger, detail],
  )

  /** Dépôt depuis l'assistant : la facture est lue, puis l'assistant l'analyse et commente. */
  const deposerAvecAssistant = useCallback(
    async (fichiers: File[]) => {
      setOccupe(true)
      for (const fichier of fichiers) {
        const reponse = tourVide('assistant', { etapes: [{ id: 'depot', libelle: `Lecture de ${fichier.name} et extraction des données`, fini: false }] })
        const depot = tourVide('user', { fichiers: [fichier.name] })
        setTours((actuels) => [...actuels, depot, reponse])
        const debut = performance.now()
        try {
          const depose = await api.deposer(fichier)
          // Le dépôt répond tout de suite ; on attend que le travailleur ait lu la facture.
          const facture = depose.deja_vue ? depose : await api.attendreLecture(depose.id)
          const journal = facture.evenements
            .filter((evenement) => evenement.type !== 'RECEPTION')
            .map((evenement) => ({ id: `journal-${evenement.rang}`, libelle: raconter(evenement), fini: true, echec: evenement.etat === 'echec' }))
          modifierTour(reponse.id, (tour) => ({
            ...tour,
            etapes: [
              { id: 'depot', libelle: depose.deja_vue ? `${fichier.name} avait déjà été reçu : rien n’a été refait` : `${fichier.name} reçu et lu`, fini: true, duree: (performance.now() - debut) / 1000 },
              ...(depose.deja_vue ? [] : journal),
            ],
          }))
          await recharger()
          setDetail(facture)
          if (facture.etat === 'echec') {
            modifierTour(reponse.id, (tour) => ({ ...tour, enCours: false, erreur: 'La facture n’a pas pu être lue. Voir son journal.' }))
            continue
          }
          const consigne = `Je viens de déposer le fichier « ${fichier.name} ». Son identifiant est ${facture.id}. Résume cette facture en deux phrases, vérifie son fournisseur auprès de l’État, puis dis-moi ce que tu recommandes.`
          modifierTour(depot.id, (tour) => ({ ...tour, envoye: consigne }))
          await interroger(historique({ role: 'user', content: consigne }), reponse.id, facture.id)
        } catch (probleme) {
          modifierTour(reponse.id, (tour) => ({ ...tour, enCours: false, erreur: (probleme as Error).message, etapes: tour.etapes.map((etape) => ({ ...etape, fini: true, echec: true })) }))
        }
      }
      setOccupe(false)
    },
    [interroger, modifierTour, recharger],
  )

  /** Dépôt depuis le haut de l'écran : la facture est lue et son parcours s'affiche sur le tableau de bord. */
  const deposer = useCallback(
    async (fichiers: File[]) => {
      const pdfs = fichiers.filter((fichier) => FORMATS_ACCEPTES.test(fichier.name))
      if (pdfs.length < fichiers.length) setErreur('Seuls les PDF et les photos (JPEG, PNG, WebP) sont acceptés.')
      if (pdfs.length === 0) return
      if (agentOuvert) return deposerAvecAssistant(pdfs)
      setOccupe(true)
      setPage('tableau')
      let derniere: FactureDetail | null = null
      const dejaRecus: string[] = []
      setInformation(null)
      // Tous les fichiers sont déposés d'abord (chaque dépôt répond tout de suite),
      // puis on suit leur lecture par le travailleur, une à une.
      const deposes: { nom: string; id: string }[] = []
      for (const fichier of pdfs) {
        try {
          const facture = await api.deposer(fichier)
          if (facture.deja_vue) dejaRecus.push(fichier.name)
          else deposes.push({ nom: fichier.name, id: facture.id })
          derniere = facture
        } catch (probleme) {
          setErreur(`« ${fichier.name} » : ${(probleme as Error).message}`)
        }
      }
      await recharger()
      for (const { nom, id } of deposes) {
        setDepotEnCours(nom)
        try {
          derniere = await api.attendreLecture(id)
        } catch (probleme) {
          setErreur((probleme as Error).message)
          break
        }
        await recharger()
      }
      if (dejaRecus.length) setInformation(`${dejaRecus.map((nom) => `« ${nom} »`).join(', ')} : déjà reçu, rien n’a été refait.`)
      await recharger()
      setDepotEnCours(null)
      setOccupe(false)
      if (derniere) {
        setDerniereDeposee(derniere.id)
        setDetail(derniere)
      }
    },
    [agentOuvert, deposerAvecAssistant, recharger],
  )

  const decider = useCallback(
    async (id: string, action: (id: string, auteur: string) => Promise<FactureDetail>) => {
      if (!auteur.trim()) {
        setErreur('Indiquez votre nom en haut à droite avant de décider : il est inscrit au journal.')
        champAuteur.current?.focus()
        return false
      }
      setDecision(true)
      try {
        setDetail(await action(id, auteur.trim()))
        setErreur(null)
        await recharger()
        return true
      } catch (probleme) {
        setErreur((probleme as Error).message)
        return false
      } finally {
        setDecision(false)
      }
    },
    [auteur, recharger],
  )

  /** Décider, puis ouvrir la facture suivante de la liste : on vide « À traiter » sans revenir à la souris. */
  const deciderPuisSuivante = async (id: string, action: (id: string, auteur: string) => Promise<FactureDetail>) => {
    const prochaine = page === 'documents' ? suivante?.id : undefined
    const reussi = await decider(id, action)
    if (reussi && prochaine) ouvrir(prochaine)
    return reussi
  }

  const repondreProposition = useCallback(
    async (tourId: number, rang: number, accepter: boolean) => {
      const proposition = toursActuels.current.find((tour) => tour.id === tourId)?.propositions[rang]
      if (!proposition) return
      let statut: 'faite' | 'ignoree' = 'ignoree'
      if (accepter) {
        const reussi = await decider(proposition.factureId, (id, nom) => (proposition.decision === 'valider' ? api.valider(id, nom) : api.rejeter(id, nom, proposition.motif)))
        if (!reussi) return
        statut = 'faite'
      }
      modifierTour(tourId, (tour) => ({ ...tour, propositions: tour.propositions.map((p, r) => (r === rang ? { ...p, statut } : p)) }))
    },
    [decider, modifierTour],
  )

  const versAssistant = (question?: string) => {
    setAgentOuvert(true)
    if (question && !occupe) envoyer(question)
  }

  // ───────── Ce qui est affiché ─────────

  const ongletConnecteursEffectif: OngletConnecteurs = ongletConnecteurs ?? (branches.length > 0 ? 'mes' : 'decouvrir')
  const compte = useMemo(() => {
    const parEtat = new Map<Etat, number>()
    for (const facture of factures) parEtat.set(facture.etat, (parEtat.get(facture.etat) ?? 0) + 1)
    return parEtat
  }, [factures])

  const numeros = useMemo(() => new Map(factures.filter((facture) => facture.numero_facture).map((facture) => [facture.numero_facture!, facture.id])), [factures])

  const listeAffichee = useMemo(() => {
    const base =
      vue === 'mon_tour'
        ? aMonTour
        : vue === 'a_traiter'
        ? aTraiter
        : vue === 'toutes'
          ? factures
          : vue === 'a_regler'
            ? factures.filter((facture) => aRegler(facture))
            : vue === 'echeances'
              ? factures.filter((facture) => echeanceProche(facture))
              : vue === 'attente'
                ? factures.filter((facture) => attenteLongue(facture))
                : factures.filter((facture) => facture.etat === vue)
    const mots = recherche.trim().toLowerCase()
    const trouvees = mots
      ? base.filter((facture) =>
          [facture.fournisseur_nom, facture.numero_facture, facture.nom_fichier, facture.fournisseur_siret].some((valeur) => valeur?.toLowerCase().includes(mots)),
        )
      : base
    // Même ordre que les groupes affichés : « Suivante » descend la liste telle qu'on la voit.
    // Les échéances : la plus urgente d'abord. Sinon, même ordre que les groupes affichés.
    if (vue === 'echeances') return [...trouvees].sort((a, b) => (a.date_echeance ?? '').localeCompare(b.date_echeance ?? ''))
    return [...trouvees].sort((a, b) => ORDRE_ETATS.indexOf(a.etat) - ORDRE_ETATS.indexOf(b.etat))
  }, [page, vue, factures, aTraiter, aMonTour, recherche])

  // Précédente et suivante : dans la liste affichée si la facture y est, sinon dans toutes.
  const voisines = page === 'documents' ? listeAffichee : factures
  const rang = detail ? voisines.findIndex((facture) => facture.id === detail.id) : -1
  const precedente = rang > 0 ? voisines[rang - 1] : null
  const suivante = rang >= 0 && rang < voisines.length - 1 ? voisines[rang + 1] : null

  const changerTheme = () => {
    const nouveau = theme === 'dark' ? 'light' : 'dark'
    retenirTheme(nouveau)
    setTheme(nouveau)
  }

  const basculerLaterale = useCallback(() => {
    setLaterale((actuelle) => {
      ecrire('docuflow.laterale', actuelle ? 'repliee' : 'ouverte')
      return !actuelle
    })
  }, [])

  const allerVue = (nouvelle: Vue) => {
    setVue(nouvelle)
    setPage('documents')
  }

  // Raccourcis : Ctrl K pour chercher, Échap pour fermer, [ pour la barre latérale.
  useEffect(() => {
    const touche = (evenement: KeyboardEvent) => {
      const cible = evenement.target as HTMLElement
      const enSaisie = Boolean(cible?.matches?.('input, textarea, select, [contenteditable]'))
      if ((evenement.ctrlKey || evenement.metaKey) && evenement.key.toLowerCase() === 'k') {
        evenement.preventDefault()
        champRecherche.current?.focus()
        champRecherche.current?.select()
      } else if (evenement.key === 'Escape') {
        if (enSaisie) cible.blur()
        else if (detail && page !== 'connecteurs') ouvrir(null)
      } else if (evenement.key === '[' && !enSaisie) {
        basculerLaterale()
      } else if (!enSaisie && detail && (evenement.key === 'ArrowDown' || evenement.key === 'j') && suivante) {
        evenement.preventDefault()
        ouvrir(suivante.id)
      } else if (!enSaisie && detail && (evenement.key === 'ArrowUp' || evenement.key === 'k') && precedente) {
        evenement.preventDefault()
        ouvrir(precedente.id)
      }
    }
    window.addEventListener('keydown', touche)
    return () => window.removeEventListener('keydown', touche)
  }, [detail, page, ouvrir, basculerLaterale, suivante, precedente])

  // Une information se retire seule ; une erreur reste jusqu'à ce qu'on la ferme.
  useEffect(() => {
    if (!information) return
    const minuterie = window.setTimeout(() => setInformation(null), 6000)
    return () => window.clearTimeout(minuterie)
  }, [information])

  // La fiche s'ouvre à côté des listes et de l'assistant ; l'accueil et les connecteurs gardent toute la largeur.
  const panneauFacture = detail && page !== 'connecteurs' && page !== 'tableau' && page !== 'reglages' && page !== 'workflow'

  // L'accueil et le Workflow prennent toute la largeur : leur contenu suffit, une barre latérale le répéterait.
  const lateraleAffichee = laterale && page !== 'workflow' && page !== 'tableau'

  if (verrouille === null) return null
  if (verrouille) return <EcranAcces surOuverture={() => setVerrouille(false)} />
  const enSaisieNom = !auteur.trim()

  return (
    <div
      className={`app${lateraleAffichee ? '' : ' app--sans-laterale'}${agentOuvert ? ' app--agent' : ''}`}
      onDragOver={(evenement) => {
        evenement.preventDefault()
        setSurvol(true)
      }}
      onDragLeave={(evenement) => evenement.currentTarget === evenement.target && setSurvol(false)}
      onDrop={(evenement) => {
        evenement.preventDefault()
        setSurvol(false)
        if (!occupe) deposer([...evenement.dataTransfer.files])
      }}
    >
      <header className="haut">
        <div className="haut__marque">
          <span className="marque" aria-hidden="true">
            <Icone nom="facture" taille={14} />
          </span>
          <span className="haut__nom">Verifac</span> <small>Factures fournisseurs</small>
        </div>

        <label className="recherche">
          <Icone nom="recherche" />
          <input
            ref={champRecherche}
            type="search"
            value={recherche}
            placeholder="Rechercher un fournisseur, un numéro, un SIRET"
            aria-label="Rechercher une facture"
            onChange={(evenement) => {
              setRecherche(evenement.target.value)
              if (page !== 'documents') setPage('documents')
            }}
          />
          <kbd>Ctrl K</kbd>
        </label>

        <div className="haut__actions">
          <button
            className={`bouton-agent${agentOuvert ? ' bouton-agent--ouvert' : ''}`}
            onClick={() => setAgentOuvert(!agentOuvert)}
            aria-pressed={agentOuvert}
            aria-label={agentOuvert ? 'Fermer l’agent IA' : 'Ouvrir l’agent IA'}
            title="Agent IA"
          >
            <IconeAgent taille={18} />
            <span>Agent</span>
          </button>
          <label className="auteur" title="Votre nom, inscrit au journal à chaque décision">
            <span className={`avatar teinte-3`} aria-hidden="true">
              {enSaisieNom ? <Icone nom="utilisateur" taille={12} /> : initiales(auteur)}
            </span>
            <input ref={champAuteur} value={auteur} onChange={(evenement) => setAuteur(evenement.target.value)} placeholder="Votre nom" maxLength={100} aria-label="Votre nom" />
          </label>
          <button className="bouton bouton--fantome bouton--icone" onClick={changerTheme} aria-label={theme === 'dark' ? 'Passer en thème clair' : 'Passer en thème sombre'} title="Changer de thème">
            <Icone nom={theme === 'dark' ? 'soleil' : 'lune'} />
          </button>
          <input
            ref={champFichier}
            type="file"
            accept="application/pdf,image/jpeg,image/png,image/webp"
            multiple
            hidden
            onChange={(evenement) => {
              deposer([...(evenement.target.files ?? [])])
              evenement.target.value = ''
            }}
          />
        </div>
      </header>

      <nav className="rail" aria-label="Navigation">
        {MENU.map((entree) => (
          <button
            key={entree.page}
            className="rail__bouton"
            aria-current={page === entree.page ? 'page' : undefined}
            onClick={() => {
              // Recliquer sur la page ouverte replie ou déplie sa barre latérale (comme la touche « [ »).
              if (entree.page === page) return basculerLaterale()
              // Factures s'ouvre sur « Mon tour » s'il y a des factures à approuver soi-même, sinon sur « À traiter ».
              if (entree.page === 'documents') setVue(aMonTour.length > 0 ? 'mon_tour' : 'a_traiter')
              setPage(entree.page)
            }}
            title={entree.page === page ? 'Replier ou déplier la barre latérale ( [ )' : undefined}
          >
            <Icone nom={entree.icone} taille={18} />
            <span className="rail__libelle">{entree.nom}</span>
            {entree.page === 'documents' && aTraiter.length > 0 && <span className="rail__compte">{aTraiter.length}</span>}
          </button>
        ))}
        <div className="rail__bas">
          <span
            className={`rail__etat${enService === false ? ' rail__etat--arret' : ''}`}
            title={enService === false ? 'Moteur injoignable' : 'Système opérationnel'}
            role="status"
            aria-label={enService === false ? 'Moteur injoignable' : 'Système opérationnel'}
          />
        </div>
      </nav>

      <aside className="laterale" aria-label="Navigation de la section" aria-hidden={!lateraleAffichee || undefined}>
        {page === 'reglages' ? (
          <>
            <div className="laterale__tete">
              <h2>Réglages</h2>
            </div>
            <div className="laterale__corps">
              <button className="laterale__ligne" aria-current={ongletReglages === 'equipe' || undefined} onClick={() => setOngletReglages('equipe')} tabIndex={laterale ? 0 : -1}>
                <Icone nom="equipe" />
                <span>Mon équipe</span>
              </button>
              <button className="laterale__ligne" aria-current={ongletReglages === 'reception' || undefined} onClick={() => setOngletReglages('reception')} tabIndex={laterale ? 0 : -1}>
                <Icone nom="mail" />
                <span>Réception des factures</span>
              </button>
            </div>
            <p className="laterale__pied">Ce que vous réglez ici s’applique à toute l’entreprise.</p>
          </>
        ) : page === 'connecteurs' ? (
          <>
            <div className="laterale__tete">
              <h2>Connecteurs</h2>
            </div>
            <div className="laterale__corps">
              {ONGLETS_CONNECTEURS.map((entree) => (
                <button
                  key={entree.onglet}
                  className="laterale__ligne"
                  aria-current={ongletConnecteursEffectif === entree.onglet || undefined}
                  onClick={() => setOngletConnecteurs(entree.onglet)}
                  tabIndex={laterale ? 0 : -1}
                >
                  <Icone nom={entree.icone} />
                  <span>{entree.nom}</span>
                  {entree.onglet === 'mes' && <span className="laterale__compte">{branches.length}</span>}
                </button>
              ))}
            </div>
            <p className="laterale__pied">Lecture seule : l’assistant cherche, il ne modifie jamais rien dans vos logiciels.</p>
          </>
        ) : (
          <>
            <div className="laterale__tete">
              <h2>Filtres</h2>
            </div>
            <div className="laterale__corps">
              <button className="laterale__ligne" aria-current={(page === 'documents' && vue === 'a_traiter') || undefined} onClick={() => allerVue('a_traiter')} tabIndex={laterale ? 0 : -1}>
                <Icone nom="validation" />
                <span>À traiter</span>
                <span className="laterale__compte">{aTraiter.length}</span>
              </button>
              {mesNiveaux.length > 0 && (
                <button className="laterale__ligne" aria-current={(page === 'documents' && vue === 'mon_tour') || undefined} onClick={() => allerVue('mon_tour')} tabIndex={laterale ? 0 : -1}>
                  <Icone nom="utilisateur" />
                  <span>Mon tour</span>
                  <span className="laterale__compte">{aMonTour.length}</span>
                </button>
              )}
              {AUTRES_FILTRES.map(({ vue: filtre, nom, icone, garder }) => {
                const nombre = factures.filter(garder).length
                if (nombre === 0 && vue !== filtre) return null
                return (
                  <button key={filtre} className="laterale__ligne" aria-current={(page === 'documents' && vue === filtre) || undefined} onClick={() => allerVue(filtre)} tabIndex={laterale ? 0 : -1}>
                    <Icone nom={icone} />
                    <span>{nom}</span>
                    <span className="laterale__compte">{nombre}</span>
                  </button>
                )
              })}
              <button className="laterale__ligne" aria-current={(page === 'documents' && vue === 'toutes') || undefined} onClick={() => allerVue('toutes')} tabIndex={laterale ? 0 : -1}>
                <Icone nom="document" />
                <span>Toutes</span>
                <span className="laterale__compte">{factures.length}</span>
              </button>
              {/* Les états vides n'encombrent pas la liste, sauf celui qu'on regarde. */}
              {ORDRE_ETATS.filter((etat) => etat !== 'extraite' && ((compte.get(etat) ?? 0) > 0 || (page === 'documents' && vue === etat))).map((etat) => (
                <button key={etat} className="laterale__ligne" aria-current={(page === 'documents' && vue === etat) || undefined} onClick={() => allerVue(etat)} tabIndex={laterale ? 0 : -1}>
                  <span className={`puce puce--${etat}`} aria-hidden="true" />
                  <span>{LIBELLE_ETAT[etat]}</span>
                  <span className="laterale__compte">{compte.get(etat) ?? 0}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </aside>

      <main className="espace">
        {/* Cette ligne n'apparaît que pour la recherche en cours ; sinon elle ne contenait qu'un bouton et prenait une ligne. */}
        <div className="espace__tete" hidden={!(page === 'documents' && recherche.trim())}>
          <button className="bouton bouton--fantome bouton--icone" onClick={basculerLaterale} aria-label={laterale ? 'Replier la barre latérale' : 'Déplier la barre latérale'} title="Barre latérale ( [ )">
            <Icone nom="panneau" />
          </button>
          {/* Pas de fil d'Ariane : chaque page porte déjà son titre, il le répétait. */}
          {page === 'documents' && recherche.trim() && (
            <div className="espace__outils">
              <button className="pastille-filtre" aria-pressed="true" onClick={() => setRecherche('')}>
                « {recherche.trim()} » <Icone nom="fermer" taille={12} />
              </button>
            </div>
          )}
        </div>

        <div className="espace__corps">
          {page === 'workflow' ? (
            <Workflow
              onglet={ongletWorkflow}
              surOnglet={setOngletWorkflow}
              auteur={auteur}
              factures={factures}
              surSansAuteur={() => champAuteur.current?.focus()}
              surInformation={setInformation}
              surFacture={(id) => {
                allerVue('toutes')
                ouvrir(id)
              }}
            />
          ) : page === 'reglages' ? (
            <Reglages onglet={ongletReglages} auteur={auteur} surSansAuteur={() => champAuteur.current?.focus()} />
          ) : page === 'connecteurs' ? (
            <Connecteurs
              auteur={auteur}
              onglet={ongletConnecteursEffectif}
              messageInitial={messageConnexion}
              statistiques={statistiques}
              surOnglet={setOngletConnecteurs}
              surChangement={rechargerConnecteurs}
              surSansAuteur={() => champAuteur.current?.focus()}
            />
          ) : (
            <div className="page">
              {page === 'tableau' &&
                (statistiques ? (
                  <TableauDeBord
                    statistiques={statistiques}
                    vedette={vedette}
                    depotEnCours={depotEnCours}
                    auteur={auteur}
                    surOuverture={(id) => {
                      allerVue('toutes')
                      ouvrir(id)
                    }}
                    surAssistant={versAssistant}
                    surDocuments={() => allerVue('toutes')}
                    factures={factures}
                    monTour={mesNiveaux.length > 0 ? aMonTour.length : null}
                    surVue={(filtre) => allerVue(filtre)}
                  />
                ) : (
                  <p className="note">{enService === false ? 'Le moteur ne répond pas.' : 'Chargement…'}</p>
                ))}
              {page === 'documents' && (
                <>
                  <header className="page__titre">
                    <div>
                      <h1>{TITRES_VUES[vue as keyof typeof TITRES_VUES]?.[0] ?? LIBELLE_ETAT[vue as Etat]}</h1>
                      <p>{TITRES_VUES[vue as keyof typeof TITRES_VUES]?.[1] ?? 'Cliquez sur une facture pour l’ouvrir à côté de la liste.'}</p>
                    </div>
                    <button className="bouton bouton--plein" onClick={() => champFichier.current?.click()} disabled={occupe}>
                      <Icone nom="deposer" /> Déposer
                    </button>
                  </header>
                  <Documents factures={listeAffichee} recherche={recherche} ouverte={detail?.id ?? null} surOuverture={ouvrir} surDepot={() => champFichier.current?.click()} />
                </>
              )}
            </div>
          )}

          {panneauFacture && (
            <aside className="panneau" aria-label="Facture ouverte">
              <header className="panneau__tete">
                <span className={`avatar avatar--grand teinte-${teinte(detail.fournisseur_nom ?? detail.nom_fichier)}`} aria-hidden="true">
                  {initiales(detail.fournisseur_nom ?? detail.nom_fichier)}
                </span>
                <div className="panneau__titre">
                  <h2>{detail.fournisseur_nom ?? detail.nom_fichier}</h2>
                  <p>
                    <span className={`etat etat--${detail.etat}`}>{LIBELLE_ETAT[detail.etat]}</span>
                    {detail.numero_facture && <span>n° {detail.numero_facture}</span>}
                    {detail.total_ttc && <strong>{euros(detail.total_ttc)}</strong>}
                  </p>
                  <Tampon facture={detail} />
                </div>
                <div className="panneau__boutons">
                  <button className="bouton bouton--fantome bouton--icone" onClick={() => precedente && ouvrir(precedente.id)} disabled={!precedente} aria-label="Facture précédente" title="Précédente (↑)">
                    <Icone nom="precedent" />
                  </button>
                  <button className="bouton bouton--fantome bouton--icone" onClick={() => suivante && ouvrir(suivante.id)} disabled={!suivante} aria-label="Facture suivante" title="Suivante (↓)">
                    <Icone nom="suivant" />
                  </button>
                  <a className="bouton bouton--fantome bouton--icone" href={api.adresseFichier(detail.id)} target="_blank" rel="noreferrer" aria-label="Ouvrir le PDF dans un nouvel onglet" title="Ouvrir le PDF">
                    <Icone nom="externe" />
                  </a>
                  <button className="bouton bouton--fantome bouton--icone" onClick={() => ouvrir(null)} aria-label="Fermer" title="Fermer (Échap)">
                    <Icone nom="fermer" />
                  </button>
                </div>
              </header>
              <div className="onglets" role="tablist">
                <button role="tab" aria-selected={onglet === 'donnees'} onClick={() => setOnglet('donnees')}>
                  <Icone nom="assistant" taille={14} /> Données
                </button>
                <button role="tab" aria-selected={onglet === 'document'} onClick={() => setOnglet('document')}>
                  <Icone nom="document" taille={14} /> Document
                </button>
                <button role="tab" aria-selected={onglet === 'journal'} onClick={() => setOnglet('journal')}>
                  <Icone nom="journal" taille={14} /> Journal
                </button>
              </div>
              <div className="panneau__corps">
                {onglet === 'document' ? (
                  <iframe key={detail.id} className="panneau__document" src={api.adresseFichier(detail.id)} title={`Facture ${detail.nom_fichier}`} />
                ) : onglet === 'journal' ? (
                  <Journal facture={detail} />
                ) : (
                  <Fiche
                    key={detail.id + detail.etat}
                    facture={detail}
                    occupe={decision}
                    surValidation={() => deciderPuisSuivante(detail.id, api.valider)}
                    surRejet={(motif) => deciderPuisSuivante(detail.id, (id, nom) => api.rejeter(id, nom, motif))}
                    surExport={() => decider(detail.id, api.exporter)}
                  />
                )}
              </div>
            </aside>
          )}
        </div>
      </main>

      {agentOuvert && (
        <aside className="agent" aria-label="Agent IA">
          <header className="agent__tete">
            <button className="bouton bouton--fantome" onClick={() => setTours([])} disabled={occupe} title="Effacer et recommencer">
              <Icone nom="conversation" /> Nouvelle discussion
            </button>
            <button className="bouton bouton--fantome bouton--icone" onClick={() => setAgentOuvert(false)} aria-label="Fermer l’agent IA" title="Fermer">
              <Icone nom="fermer" />
            </button>
          </header>
          <Conversation
            panneau
            tours={tours}
            numeros={numeros}
            occupe={occupe}
            connecteurs={branches}
            surConnecteurs={() => setPage('connecteurs')}
            surEnvoi={envoyer}
            surFichiers={deposerAvecAssistant}
            surProposition={repondreProposition}
            surOuverture={(id) => {
              // La facture s'ouvre dans la liste, à côté de l'agent qui reste ouvert.
              if (page !== 'documents') allerVue('toutes')
              ouvrir(id)
            }}
          />
        </aside>
      )}

      <div className="notifications" aria-live="polite">
        {erreur && (
          <div className="notification notification--erreur" role="alert">
            <Icone nom="anomalie" />
            <p>{erreur}</p>
            <button className="bouton bouton--fantome bouton--petit bouton--icone" onClick={() => setErreur(null)} aria-label="Fermer">
              <Icone nom="fermer" taille={14} />
            </button>
          </div>
        )}
        {information && (
          <div className="notification" role="status">
            <Icone nom="coche" />
            <p>{information}</p>
            <button className="bouton bouton--fantome bouton--petit bouton--icone" onClick={() => setInformation(null)} aria-label="Fermer">
              <Icone nom="fermer" taille={14} />
            </button>
          </div>
        )}
      </div>

      {survol && <div className="depot">Relâchez pour déposer les factures</div>}
    </div>
  )
}
