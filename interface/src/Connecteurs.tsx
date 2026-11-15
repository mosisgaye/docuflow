import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api'
import type { Connecteur, FicheConnecteur, Statistiques, StatutConnecteur } from './api'
import { heure, jourEtHeure } from './format'
import { INITIALES, LOGOS } from './logos'
import { ServicesIntegres } from './Pages'
import { AccesDeveloppeurs } from './AccesDeveloppeurs'

type Onglet = 'mes' | 'decouvrir' | 'integres' | 'developpeurs'

const LIBELLE_STATUT: Record<StatutConnecteur, string> = {
  disponible: 'Disponible',
  preversion: 'Préversion',
  a_confirmer: 'À confirmer',
  bientot: 'Bientôt',
}

/** Logo officiel quand il est libre de droits, sinon une pastille neutre à l'initiale. */
function Logo({ connecteur, taille = 44 }: { connecteur: Pick<Connecteur, 'id' | 'nom'>; taille?: number }) {
  const logo = LOGOS[connecteur.id]
  return (
    <span className="logo-connecteur" style={{ width: taille, height: taille }} aria-hidden="true">
      {logo ? (
        // Le logo d'Odoo est un mot : il lui faut plus de largeur qu'un symbole pour rester lisible.
        <svg viewBox="0 0 24 24" width={taille * (connecteur.id === 'odoo' ? 0.85 : 0.55)} height={taille * (connecteur.id === 'odoo' ? 0.85 : 0.55)} fill={logo.couleur}>
          <path d={logo.chemin} />
        </svg>
      ) : (
        <span className="logo-connecteur__initiale">{INITIALES[connecteur.id] ?? connecteur.nom[0]}</span>
      )}
    </span>
  )
}

/** Où en est le connecteur, quand on ne peut pas encore le brancher. None : on peut agir. */
function etat(connecteur: Connecteur): string | null {
  if (connecteur.branche) return null
  if (connecteur.statut === 'bientot' || connecteur.statut === 'a_confirmer') return LIBELLE_STATUT[connecteur.statut]
  // Connexion par compte : il faut d'abord les identifiants fournis par l'éditeur.
  if (connecteur.connexion === 'oauth' && !connecteur.connexion_prete) return 'Identifiants à configurer'
  return null
}

/** Ce qu'on peut faire d'un connecteur depuis sa carte. */
function Action({ connecteur, occupe, surBrancher, surOuvrir }: { connecteur: Connecteur; occupe: boolean; surBrancher: () => void; surOuvrir: () => void }) {
  if (connecteur.branche)
    return (
      <button className="carte-connecteur__etat carte-connecteur__etat--branche" onClick={surOuvrir} aria-label={`${connecteur.nom} est branché : voir le détail`}>
        Branché
      </button>
    )
  if (etat(connecteur)) return null
  return (
    <button className="bouton bouton--plein carte-connecteur__brancher" onClick={surBrancher} disabled={occupe}>
      {occupe ? 'Connexion…' : connecteur.connexion === 'oauth' ? 'Connecter mon compte' : 'Brancher'}
    </button>
  )
}

function Carte({ connecteur, occupe, surBrancher, surOuvrir }: { connecteur: Connecteur; occupe: boolean; surBrancher: () => void; surOuvrir: () => void }) {
  return (
    <li className="carte carte-connecteur">
      <button className="carte-connecteur__ouvrir" onClick={surOuvrir} aria-label={`Détail de ${connecteur.nom}`}>
        <Logo connecteur={connecteur} />
        <span className="carte-connecteur__texte">
          <span className="carte-connecteur__nom">
            {connecteur.nom}
            {connecteur.statut === 'preversion' && <span className="carte-connecteur__marque">Préversion</span>}
          </span>
          <span className="carte-connecteur__description">{connecteur.description}</span>
          <span className="carte-connecteur__editeur">
            par {connecteur.editeur}
            {etat(connecteur) && <span className="carte-connecteur__etat">{etat(connecteur)}</span>}
          </span>
        </span>
      </button>
      <Action connecteur={connecteur} occupe={occupe} surBrancher={surBrancher} surOuvrir={surOuvrir} />
    </li>
  )
}

function Fiche({
  fiche,
  occupe,
  surFermer,
  surBrancher,
  surDebrancher,
  surOutils,
}: {
  fiche: FicheConnecteur
  occupe: boolean
  surFermer: () => void
  surBrancher: () => void
  surDebrancher: () => void
  surOutils: (autorises: string[] | null) => void
}) {
  const lecture = fiche.outils.filter((outil) => outil.lecture)
  const cadre = useRef<HTMLElement>(null)
  // La fiche s'ouvre sous la grille : on l'amène à l'écran, sinon le clic semble sans effet.
  useEffect(() => {
    // Accolades obligatoires : scrollIntoView peut renvoyer une promesse, que React prendrait pour un nettoyage.
    cadre.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [fiche.id])
  const basculer = (nom: string) => {
    const actuels = new Set(lecture.filter((outil) => outil.autorise).map((outil) => outil.nom))
    if (actuels.has(nom)) actuels.delete(nom)
    else actuels.add(nom)
    // Tous cochés : on revient à « tous les outils de lecture », y compris ceux qu'un serveur ajoutera.
    surOutils(actuels.size === lecture.length ? null : [...actuels])
  }
  return (
    <section ref={cadre} className="carte fiche-connecteur" aria-label={`Connecteur ${fiche.nom}`}>
      <header className="fiche-connecteur__entete">
        <Logo connecteur={fiche} taille={52} />
        <div>
          <h2>{fiche.nom}</h2>
          <p>
            par {fiche.editeur} · {LIBELLE_STATUT[fiche.statut]}
            {fiche.branche && fiche.branche_par && fiche.branche_le && ` · branché par ${fiche.branche_par} le ${jourEtHeure(fiche.branche_le)}`}
          </p>
        </div>
        <button className="bouton" onClick={surFermer}>
          Fermer
        </button>
      </header>

      <p className="fiche-connecteur__note">{fiche.note}</p>

      <h3>Ce que l’assistant peut en faire</h3>
      <ul className="fiche-connecteur__usages">
        {fiche.usages.map((usage) => (
          <li key={usage}>{usage}</li>
        ))}
      </ul>

      {fiche.branche ? (
        <>
          <h3>Outils autorisés</h3>
          {fiche.erreur ? (
            <p className="fiche-connecteur__erreur">{fiche.erreur}</p>
          ) : (
            <ul className="fiche-connecteur__outils">
              {fiche.outils.map((outil) => (
                <li key={outil.nom}>
                  <label>
                    <input type="checkbox" checked={outil.autorise} disabled={!outil.lecture || occupe} onChange={() => basculer(outil.nom)} />
                    <span>
                      <strong>{outil.nom.replace(/_/g, ' ')}</strong>
                      <small>{outil.lecture ? outil.description.split('\n')[0] : 'Modifie des données : jamais confié à l’assistant.'}</small>
                    </span>
                  </label>
                  <span className={`fiche-connecteur__nature fiche-connecteur__nature--${outil.lecture ? 'lecture' : 'ecriture'}`}>{outil.lecture ? 'Lecture' : 'Écriture'}</span>
                </li>
              ))}
            </ul>
          )}

          <h3>Derniers appels de l’assistant</h3>
          {fiche.appels.length === 0 ? (
            <p className="fiche-connecteur__vide">Aucun appel pour l’instant. Posez une question à l’assistant.</p>
          ) : (
            <ol className="fiche-connecteur__appels">
              {fiche.appels.map((appel) => (
                <li key={appel.cree_le + appel.outil}>
                  <time dateTime={appel.cree_le}>{heure(appel.cree_le)}</time>
                  <span>
                    {appel.outil.replace(/_/g, ' ')}
                    <small>{Object.values(appel.arguments).map(String).join(', ')}</small>
                  </span>
                  <span className={`fiche-connecteur__statut fiche-connecteur__statut--${appel.statut}`}>
                    {appel.statut === 'ok' ? `${appel.duree_ms} ms` : appel.statut === 'refuse' ? 'Refusé' : 'Erreur'}
                  </span>
                </li>
              ))}
            </ol>
          )}

          <div className="fiche-connecteur__actions">
            <a className="bouton" href={fiche.documentation} target="_blank" rel="noreferrer">
              Documentation
            </a>
            <button className="bouton bouton--rejet" onClick={surDebrancher} disabled={occupe}>
              Débrancher
            </button>
          </div>
        </>
      ) : (
        <div className="fiche-connecteur__actions">
          <a className="bouton" href={fiche.documentation} target="_blank" rel="noreferrer">
            Documentation
          </a>
          {(fiche.statut === 'disponible' || fiche.statut === 'preversion') && fiche.connexion_prete && (
            <button className="bouton bouton--plein" onClick={surBrancher} disabled={occupe}>
              {fiche.connexion === 'oauth' ? `Connecter mon compte ${fiche.nom}` : 'Brancher'}
            </button>
          )}
        </div>
      )}
    </section>
  )
}

interface Props {
  auteur: string
  messageInitial: string | null  // au retour d'une connexion par compte
  statistiques: Statistiques | null
  surChangement: () => void
  surSansAuteur: () => void
}

export function Connecteurs({ auteur, messageInitial, statistiques, surChangement, surSansAuteur }: Props) {
  const [liste, setListe] = useState<Connecteur[] | null>(null)
  const [onglet, setOnglet] = useState<Onglet | null>(null)
  const [recherche, setRecherche] = useState('')
  const [ouvert, setOuvert] = useState<string | null>(null)
  const [fiche, setFiche] = useState<FicheConnecteur | null>(null)
  const [occupe, setOccupe] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(messageInitial)

  const recharger = useCallback(async () => {
    const nouvelle = await api.connecteurs()
    setListe(nouvelle)
    setOnglet((actuel) => actuel ?? (nouvelle.some((connecteur) => connecteur.branche) ? 'mes' : 'decouvrir'))
    return nouvelle
  }, [])

  useEffect(() => {
    recharger().catch((erreur: Error) => setMessage(erreur.message))
  }, [recharger])

  useEffect(() => {
    if (!ouvert) {
      setFiche(null)
      return
    }
    api.ficheConnecteur(ouvert).then(setFiche, (erreur: Error) => setMessage(erreur.message))
  }, [ouvert])

  const agir = async (id: string, action: () => Promise<unknown>, succes: string) => {
    setOccupe(id)
    setMessage(null)
    try {
      await action()
      await recharger()
      if (ouvert === id) setFiche(await api.ficheConnecteur(id))
      surChangement()
      setMessage(succes)
    } catch (erreur) {
      setMessage((erreur as Error).message)
    } finally {
      setOccupe(null)
    }
  }

  const brancher = (connecteur: Connecteur) => {
    if (!auteur.trim()) {
      setMessage('Indiquez votre nom en haut à droite : le branchement est inscrit à votre nom.')
      return surSansAuteur()
    }
    if (connecteur.connexion === 'oauth') {
      // Connexion par compte : le navigateur part chez l'éditeur, puis revient ici.
      setOccupe(connecteur.id)
      api.commencerConnexion(connecteur.id, auteur.trim()).then(
        ({ adresse }) => window.location.assign(adresse),
        (erreur: Error) => {
          setOccupe(null)
          setMessage(erreur.message)
        },
      )
      return
    }
    agir(connecteur.id, () => api.brancher(connecteur.id, auteur.trim()), `${connecteur.nom} est branché : l’assistant peut maintenant y chercher.`)
  }

  const mots = recherche.trim().toLowerCase()
  const branches = (liste ?? []).filter((connecteur) => connecteur.branche)
  const visibles = (onglet === 'mes' ? branches : (liste ?? [])).filter((connecteur) =>
    [connecteur.nom, connecteur.editeur, connecteur.description].some((texte) => texte.toLowerCase().includes(mots)),
  )

  return (
    <div className="page connecteurs">
      <header className="tableau__titre">
        <h1>Connecteurs</h1>
        <p>Les logiciels de l’entreprise où l’assistant peut chercher : en lecture seule, chaque appel inscrit au journal.</p>
      </header>

      <div className="connecteurs__barre">
        <div className="connecteurs__onglets" role="tablist">
          <button role="tab" aria-selected={onglet === 'mes'} onClick={() => setOnglet('mes')}>
            Mes connecteurs <span className="connecteurs__compte">{branches.length}</span>
          </button>
          <button role="tab" aria-selected={onglet === 'decouvrir'} onClick={() => setOnglet('decouvrir')}>
            Découvrir
          </button>
          <button role="tab" aria-selected={onglet === 'integres'} onClick={() => setOnglet('integres')}>
            Intégrés à DocuFlow
          </button>
          <button role="tab" aria-selected={onglet === 'developpeurs'} onClick={() => setOnglet('developpeurs')}>
            Accès développeurs
          </button>
        </div>
        {(onglet === 'mes' || onglet === 'decouvrir') && (
          <input className="connecteurs__recherche" type="search" value={recherche} onChange={(evenement) => setRecherche(evenement.target.value)} placeholder="Rechercher un outil" aria-label="Rechercher un connecteur" />
        )}
      </div>

      {message && (
        <p className="connecteurs__message" role="status">
          {message}
        </p>
      )}

      {onglet === 'developpeurs' ? (
        <AccesDeveloppeurs auteur={auteur} surSansAuteur={surSansAuteur} />
      ) : onglet === 'integres' ? (
        <ServicesIntegres statistiques={statistiques} />
      ) : liste === null ? (
        <p className="page__note">Chargement des connecteurs…</p>
      ) : visibles.length === 0 ? (
        <div className="carte carte__vide">
          {onglet === 'mes' && !mots ? (
            <>
              Aucun connecteur branché.{' '}
              <button className="lien" onClick={() => setOnglet('decouvrir')}>
                Découvrir les connecteurs
              </button>
            </>
          ) : (
            'Aucun connecteur ne correspond à cette recherche.'
          )}
        </div>
      ) : (
        <ul className="connecteurs__grille">
          {visibles.map((connecteur) => (
            <Carte key={connecteur.id} connecteur={connecteur} occupe={occupe === connecteur.id} surBrancher={() => brancher(connecteur)} surOuvrir={() => setOuvert(connecteur.id)} />
          ))}
        </ul>
      )}

      {fiche && (
        <Fiche
          fiche={fiche}
          occupe={occupe === fiche.id}
          surFermer={() => setOuvert(null)}
          surBrancher={() => brancher(fiche)}
          surDebrancher={() => agir(fiche.id, () => api.debrancher(fiche.id), `${fiche.nom} est débranché : l’assistant n’y a plus accès.`)}
          surOutils={(autorises) => agir(fiche.id, () => api.autoriserOutils(fiche.id, autorises), 'Outils autorisés mis à jour.')}
        />
      )}
    </div>
  )
}
