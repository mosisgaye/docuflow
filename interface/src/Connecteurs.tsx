import { useCallback, useEffect, useState } from 'react'
import * as api from './api'
import type { Connecteur, FicheConnecteur, Statistiques, StatutConnecteur } from './api'
import { heure, jourEtHeure } from './format'
import { Icone } from './Icones'
import { INITIALES, LOGOS } from './logos'
import { ServicesIntegres } from './Pages'
import { AccesDeveloppeurs } from './AccesDeveloppeurs'

export type OngletConnecteurs = 'mes' | 'decouvrir' | 'integres' | 'developpeurs'

const LIBELLE_STATUT: Record<StatutConnecteur, string> = {
  disponible: 'Disponible',
  preversion: 'Préversion',
  a_confirmer: 'À confirmer',
  bientot: 'Bientôt',
}

/** Logo officiel quand il est libre de droits, sinon une pastille neutre à l'initiale. */
function Logo({ connecteur, taille = 32 }: { connecteur: Pick<Connecteur, 'id' | 'nom'>; taille?: number }) {
  const logo = LOGOS[connecteur.id]
  return (
    <span className="logo-connecteur" style={{ width: `${taille / 16}rem`, height: `${taille / 16}rem` }} aria-hidden="true">
      {logo ? (
        // Le logo d'Odoo est un mot : il lui faut plus de largeur qu'un symbole pour rester lisible.
        <svg viewBox="0 0 24 24" style={{ width: `${(taille * (connecteur.id === 'odoo' ? 0.85 : 0.55)) / 16}rem`, height: `${(taille * (connecteur.id === 'odoo' ? 0.85 : 0.55)) / 16}rem` }} fill={logo.couleur}>
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
      <>
        <span className="carte-connecteur__etat carte-connecteur__etat--branche">
          <Icone nom="coche" taille={14} /> Branché
        </span>
        <button className="bouton bouton--petit" onClick={surOuvrir}>
          Gérer
        </button>
      </>
    )
  const attente = etat(connecteur)
  if (attente) return <span className="carte-connecteur__etat">{attente}</span>
  return (
    <>
      <span className="carte-connecteur__etat" />
      <button className="bouton bouton--plein bouton--petit" onClick={surBrancher} disabled={occupe}>
        {occupe ? 'Connexion…' : connecteur.connexion === 'oauth' ? 'Connecter mon compte' : 'Brancher'}
      </button>
    </>
  )
}

function Carte({ connecteur, occupe, ouverte, surBrancher, surOuvrir }: { connecteur: Connecteur; occupe: boolean; ouverte: boolean; surBrancher: () => void; surOuvrir: () => void }) {
  return (
    <li className="carte-connecteur" aria-current={ouverte || undefined}>
      <button className="carte-connecteur__ouvrir" onClick={surOuvrir} aria-label={`Détail de ${connecteur.nom}`}>
        <Logo connecteur={connecteur} />
        <span className="carte-connecteur__texte">
          <span className="carte-connecteur__nom">
            {connecteur.nom}
            {connecteur.statut === 'preversion' && <span className="carte-connecteur__marque">Préversion</span>}
          </span>
          <span className="carte-connecteur__description">{connecteur.description}</span>
          <span className="carte-connecteur__editeur">par {connecteur.editeur}</span>
        </span>
      </button>
      <div className="carte-connecteur__pied">
        <Action connecteur={connecteur} occupe={occupe} surBrancher={surBrancher} surOuvrir={surOuvrir} />
      </div>
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
  const basculer = (nom: string) => {
    const actuels = new Set(lecture.filter((outil) => outil.autorise).map((outil) => outil.nom))
    if (actuels.has(nom)) actuels.delete(nom)
    else actuels.add(nom)
    // Tous cochés : on revient à « tous les outils de lecture », y compris ceux qu'un serveur ajoutera.
    surOutils(actuels.size === lecture.length ? null : [...actuels])
  }
  return (
    <aside className="panneau" aria-label={`Connecteur ${fiche.nom}`}>
      <header className="panneau__tete">
        <Logo connecteur={fiche} taille={36} />
        <div className="panneau__titre">
          <h2>{fiche.nom}</h2>
          <p>
            par {fiche.editeur}, {LIBELLE_STATUT[fiche.statut].toLowerCase()}
          </p>
        </div>
        <div className="panneau__boutons">
          <button className="bouton bouton--fantome bouton--icone" onClick={surFermer} aria-label="Fermer" title="Fermer (Échap)">
            <Icone nom="fermer" />
          </button>
        </div>
      </header>
      <div className="panneau__corps fiche-connecteur">
      {fiche.branche && fiche.branche_par && fiche.branche_le && (
        <p className="signal signal--vert" style={{ marginTop: '0.875rem' }}>
          <Icone nom="coche" />
          <span>
            Branché par {fiche.branche_par} le {jourEtHeure(fiche.branche_le)}
          </span>
        </p>
      )}

      <p className="fiche-connecteur__note">{fiche.note}</p>

      <h3>Ce que l’assistant peut en faire</h3>
      <ul className="fiche-connecteur__usages">
        {fiche.usages.map((usage) => (
          <li key={usage}>
            <Icone nom="coche" taille={14} />
            {usage}
          </li>
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
              Documentation <Icone nom="externe" taille={14} />
            </a>
            <button className="bouton bouton--danger" onClick={surDebrancher} disabled={occupe}>
              Débrancher
            </button>
          </div>
        </>
      ) : (
        <div className="fiche-connecteur__actions">
          <a className="bouton" href={fiche.documentation} target="_blank" rel="noreferrer">
            Documentation <Icone nom="externe" taille={14} />
          </a>
          {(fiche.statut === 'disponible' || fiche.statut === 'preversion') && fiche.connexion_prete && (
            <button className="bouton bouton--plein" onClick={surBrancher} disabled={occupe}>
              {fiche.connexion === 'oauth' ? `Connecter mon compte ${fiche.nom}` : 'Brancher'}
            </button>
          )}
        </div>
      )}
      </div>
    </aside>
  )
}

interface Props {
  auteur: string
  onglet: OngletConnecteurs
  messageInitial: string | null  // au retour d'une connexion par compte
  statistiques: Statistiques | null
  surOnglet: (onglet: OngletConnecteurs) => void
  surChangement: () => void
  surSansAuteur: () => void
}

export function Connecteurs({ auteur, onglet, messageInitial, statistiques, surOnglet, surChangement, surSansAuteur }: Props) {
  const [liste, setListe] = useState<Connecteur[] | null>(null)
  const [recherche, setRecherche] = useState('')
  const [ouvert, setOuvert] = useState<string | null>(null)
  const [fiche, setFiche] = useState<FicheConnecteur | null>(null)
  const [occupe, setOccupe] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(messageInitial)

  const recharger = useCallback(async () => {
    const nouvelle = await api.connecteurs()
    setListe(nouvelle)
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

  // Échap ferme la fiche ouverte.
  useEffect(() => {
    if (!ouvert) return
    const fermer = (evenement: KeyboardEvent) => {
      if (evenement.key === 'Escape') setOuvert(null)
    }
    window.addEventListener('keydown', fermer)
    return () => window.removeEventListener('keydown', fermer)
  }, [ouvert])

  return (
    <>
      <div className="page">
        <header className="page__titre">
          <div>
            <h1>{TITRES[onglet].titre}</h1>
            <p>{TITRES[onglet].texte}</p>
          </div>
        </header>

        {(onglet === 'mes' || onglet === 'decouvrir') && (
          <div className="connecteurs__barre">
            <label className="recherche">
              <Icone nom="recherche" />
              <input type="search" value={recherche} onChange={(evenement) => setRecherche(evenement.target.value)} placeholder="Rechercher un outil" aria-label="Rechercher un connecteur" />
            </label>
          </div>
        )}

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
          <p className="note">Chargement des connecteurs…</p>
        ) : visibles.length === 0 ? (
          <div className="vide">
            <Icone nom="integration" taille={28} />
            {onglet === 'mes' && !mots ? (
              <>
                <strong>Aucun connecteur branché</strong>
                <p>Branchez un logiciel de l’entreprise : l’assistant pourra y chercher, en lecture seule.</p>
                <button className="bouton bouton--plein" onClick={() => surOnglet('decouvrir')}>
                  Découvrir les connecteurs
                </button>
              </>
            ) : (
              <strong>Aucun connecteur ne correspond à cette recherche</strong>
            )}
          </div>
        ) : (
          <ul className="connecteurs__grille">
            {visibles.map((connecteur) => (
              <Carte
                key={connecteur.id}
                connecteur={connecteur}
                occupe={occupe === connecteur.id}
                ouverte={ouvert === connecteur.id}
                surBrancher={() => brancher(connecteur)}
                surOuvrir={() => setOuvert(connecteur.id)}
              />
            ))}
          </ul>
        )}
      </div>

      {fiche && (onglet === 'mes' || onglet === 'decouvrir') && (
        <Fiche
          key={fiche.id}
          fiche={fiche}
          occupe={occupe === fiche.id}
          surFermer={() => setOuvert(null)}
          surBrancher={() => brancher(fiche)}
          surDebrancher={() => agir(fiche.id, () => api.debrancher(fiche.id), `${fiche.nom} est débranché : l’assistant n’y a plus accès.`)}
          surOutils={(autorises) => agir(fiche.id, () => api.autoriserOutils(fiche.id, autorises), 'Outils autorisés mis à jour.')}
        />
      )}
    </>
  )
}

const TITRES: Record<OngletConnecteurs, { titre: string; texte: string }> = {
  mes: { titre: 'Mes connecteurs', texte: 'Les logiciels branchés, où l’assistant peut chercher : en lecture seule, chaque appel inscrit au journal.' },
  decouvrir: { titre: 'Découvrir', texte: 'Les logiciels qu’on peut brancher à Verifac.' },
  integres: { titre: 'Intégrés à Verifac', texte: 'Ce qui fonctionne sans rien brancher.' },
  developpeurs: { titre: 'Accès développeurs', texte: 'Pour qu’un autre logiciel dépose et lise les factures, ou soit prévenu de leurs changements.' },
}
