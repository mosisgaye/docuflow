import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type EvenementAgent, type MessageAgent, parler } from './agent'
import * as api from './api'
import type { FactureDetail, FactureResume, Statistiques } from './api'
import { Conversation, type Tour } from './Conversation'
import { Fiche } from './Fiche'
import { A_TRAITER, raconter } from './format'
import { Icone } from './Icones'
import { Documents, Integrations } from './Pages'
import { TableauDeBord } from './TableauDeBord'

type Page = 'tableau' | 'documents' | 'validations' | 'assistant' | 'integrations'

const CLE_AUTEUR = 'factures.auteur'
const MENU: { page: Page; nom: string; icone: 'accueil' | 'document' | 'validation' | 'assistant' | 'integration' }[] = [
  { page: 'tableau', nom: 'Tableau de bord', icone: 'accueil' },
  { page: 'documents', nom: 'Documents', icone: 'document' },
  { page: 'validations', nom: 'Validations', icone: 'validation' },
  { page: 'assistant', nom: 'Assistant', icone: 'assistant' },
  { page: 'integrations', nom: 'Intégrations', icone: 'integration' },
]
let prochainId = 1

const tourVide = (role: Tour['role'], champs: Partial<Tour> = {}): Tour => ({
  id: prochainId++,
  role,
  texte: '',
  etapes: [],
  propositions: [],
  enCours: role === 'assistant',
  ...champs,
})

export function Application() {
  const [page, setPage] = useState<Page>('tableau')
  const [factures, setFactures] = useState<FactureResume[]>([])
  const [statistiques, setStatistiques] = useState<Statistiques | null>(null)
  const [vedette, setVedette] = useState<FactureDetail | null>(null)
  const [detail, setDetail] = useState<FactureDetail | null>(null)
  const [onglet, setOnglet] = useState<'donnees' | 'document'>('donnees')
  const [tours, setTours] = useState<Tour[]>([])
  const [recherche, setRecherche] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [enService, setEnService] = useState<boolean | null>(null)
  const [occupe, setOccupe] = useState(false)
  const [decision, setDecision] = useState(false)
  const [depotEnCours, setDepotEnCours] = useState<string | null>(null)
  const [survol, setSurvol] = useState(false)
  const [auteur, setAuteur] = useState(() => localStorage.getItem(CLE_AUTEUR) ?? '')
  const champAuteur = useRef<HTMLInputElement>(null)
  const champFichier = useRef<HTMLInputElement>(null)
  const toursActuels = useRef(tours)
  toursActuels.current = tours
  const derniereOuverture = useRef(0)

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
    recharger()
  }, [recharger])

  useEffect(() => localStorage.setItem(CLE_AUTEUR, auteur), [auteur])

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
          const facture = await api.deposer(fichier)
          const journal = facture.evenements
            .filter((evenement) => evenement.type !== 'RECEPTION')
            .map((evenement) => ({ id: `journal-${evenement.rang}`, libelle: raconter(evenement), fini: true, echec: evenement.etat === 'echec' }))
          modifierTour(reponse.id, (tour) => ({
            ...tour,
            etapes: [
              { id: 'depot', libelle: facture.deja_vue ? `${fichier.name} avait déjà été reçu : rien n’a été refait` : `${fichier.name} reçu et lu`, fini: true, duree: (performance.now() - debut) / 1000 },
              ...(facture.deja_vue ? [] : journal),
            ],
          }))
          await recharger()
          setDetail(facture)
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
      const pdfs = fichiers.filter((fichier) => fichier.name.toLowerCase().endsWith('.pdf'))
      if (pdfs.length < fichiers.length) setErreur('Seuls les fichiers PDF sont acceptés.')
      if (pdfs.length === 0) return
      if (page === 'assistant') return deposerAvecAssistant(pdfs)
      setOccupe(true)
      setPage('tableau')
      let derniere: FactureDetail | null = null
      for (const fichier of pdfs) {
        setDepotEnCours(fichier.name)
        try {
          derniere = await api.deposer(fichier)
        } catch (probleme) {
          setErreur(`« ${fichier.name} » : ${(probleme as Error).message}`)
        }
      }
      await recharger()
      setDepotEnCours(null)
      setOccupe(false)
      if (derniere) {
        setDerniereDeposee(derniere.id)
        setDetail(derniere)
      }
    },
    [page, deposerAvecAssistant, recharger],
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
    setPage('assistant')
    if (question && !occupe) envoyer(question)
  }

  return (
    <div
      className={`application${detail ? ' application--ouvert' : ''}`}
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
      <nav className="menu" aria-label="Navigation">
        <div className="menu__marque">
          <span className="menu__logo" aria-hidden="true" />
          <p>
            <strong>DocuFlow AI</strong>
            <small>Lire. Contrôler. Décider.</small>
          </p>
        </div>
        <ul>
          {MENU.map((entree) => (
            <li key={entree.page}>
              <button aria-current={page === entree.page ? 'page' : undefined} onClick={() => setPage(entree.page)}>
                <Icone nom={entree.icone} />
                <span>{entree.nom}</span>
                {entree.page === 'validations' && aTraiter.length > 0 && <span className="menu__compte">{aTraiter.length}</span>}
              </button>
            </li>
          ))}
        </ul>
        <p className={`menu__etat menu__etat--${enService === false ? 'arret' : 'marche'}`}>
          <span aria-hidden="true" />
          {enService === false ? 'Moteur injoignable' : enService ? 'Système opérationnel' : 'Connexion…'}
        </p>
      </nav>

      <div className="scene">
        <header className="barre">
          <label className="barre__recherche">
            <Icone nom="recherche" />
            <input
              type="search"
              value={recherche}
              placeholder="Rechercher un fournisseur, un numéro…"
              aria-label="Rechercher une facture"
              onChange={(evenement) => {
                setRecherche(evenement.target.value)
                if (page !== 'validations') setPage('documents')
              }}
            />
          </label>
          <button className="bouton bouton--plein" onClick={() => champFichier.current?.click()} disabled={occupe}>
            Déposer des factures
          </button>
          <label className="barre__auteur">
            Bonjour,
            <input ref={champAuteur} value={auteur} onChange={(evenement) => setAuteur(evenement.target.value)} placeholder="votre nom" maxLength={100} aria-label="Votre nom" />
          </label>
          <input
            ref={champFichier}
            type="file"
            accept="application/pdf"
            multiple
            hidden
            onChange={(evenement) => {
              deposer([...(evenement.target.files ?? [])])
              evenement.target.value = ''
            }}
          />
        </header>

        {erreur && (
          <p className="bandeau" role="alert">
            {erreur}
            <button onClick={() => setErreur(null)}>Fermer</button>
          </p>
        )}

        <div className="scene__page">
          {page === 'tableau' && statistiques && (
            <TableauDeBord
              statistiques={statistiques}
              vedette={vedette}
              depotEnCours={depotEnCours}
              surOuverture={ouvrir}
              surAssistant={versAssistant}
              surDocuments={() => setPage('documents')}
            />
          )}
          {page === 'documents' && (
            <Documents titre="Documents" sousTitre="Toutes les factures reçues." factures={factures} recherche={recherche} ouverte={detail?.id ?? null} surOuverture={ouvrir} />
          )}
          {page === 'validations' && (
            <Documents
              titre="Validations"
              sousTitre="Les factures qui attendent votre décision, les anomalies en premier."
              factures={aTraiter}
              recherche={recherche}
              ouverte={detail?.id ?? null}
              surOuverture={ouvrir}
            />
          )}
          {page === 'assistant' && (
            <Conversation tours={tours} occupe={occupe} surEnvoi={envoyer} surFichiers={deposerAvecAssistant} surProposition={repondreProposition} surOuverture={ouvrir} />
          )}
          {page === 'integrations' && <Integrations statistiques={statistiques} />}
        </div>
      </div>

      {detail && (
        <aside className="volet" aria-label="Facture ouverte">
          <div className="volet__onglets">
            <button aria-pressed={onglet === 'donnees'} onClick={() => setOnglet('donnees')}>
              Données lues par l’IA
            </button>
            <button aria-pressed={onglet === 'document'} onClick={() => setOnglet('document')}>
              Document reçu
            </button>
            <button className="volet__fermer" onClick={() => ouvrir(null)}>
              Fermer
            </button>
          </div>
          {onglet === 'document' ? (
            <iframe key={detail.id} className="volet__document" src={api.adresseFichier(detail.id)} title={`Facture ${detail.nom_fichier}`} />
          ) : (
            <Fiche
              key={detail.id + detail.etat}
              facture={detail}
              occupe={decision}
              surValidation={() => decider(detail.id, api.valider)}
              surRejet={(motif) => decider(detail.id, (id, nom) => api.rejeter(id, nom, motif))}
              surExport={() => decider(detail.id, api.exporter)}
            />
          )}
        </aside>
      )}

      {survol && <div className="depot">Relâchez pour déposer les factures</div>}
    </div>
  )
}
