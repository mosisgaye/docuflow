// La page Circuit, comme n8n : le canevas où l'on crée et relie ses étapes, un seul panneau à droite
// (la palette, ou les réglages de l'étape choisie), et une barre en haut pour tester et publier.
// Chaque modification est enregistrée dans le brouillon, qu'aucune facture ne voit avant la publication.
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as api from './api'
import type { BrouillonCircuit, Catalogue, Changement, FactureResume, Graphe, NoeudGraphe, Relances, ResultatTest, TypeEtape } from './api'
import { euros } from './format'
import { Icone } from './Icones'
import { PanneauEtape, type Statut, nouvelleEtape } from './PanneauEtape'
import { SchemaCircuit } from './SchemaCircuit'

const DELAI_ENREGISTREMENT_MS = 600
const LUES = new Set(['a_valider', 'en_approbation', 'en_anomalie', 'validee', 'rejetee', 'exportee'])

const pluriel = (n: number, mot: string) => `${n} ${mot}${n > 1 ? 's' : ''}`

export function Circuit({
  onglets,
  auteur,
  factures,
  surSansAuteur,
  surInformation,
}: {
  onglets: ReactNode
  auteur: string
  factures: FactureResume[]
  surSansAuteur: () => void
  surInformation: (message: string) => void
}) {
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null)
  const [graphe, setGraphe] = useState<Graphe | null>(null)
  const [relances, setRelances] = useState<Relances | null>(null)
  const [brouillon, setBrouillon] = useState<BrouillonCircuit | null>(null)
  const [changements, setChangements] = useState<Changement[]>([])
  const [choisie, setChoisie] = useState<string | null>(null)
  const [statut, setStatut] = useState<Statut>({ etat: 'repos' })
  const [test, setTest] = useState<ResultatTest | null>(null)
  const [factureTest, setFactureTest] = useState('')
  const [voirChangements, setVoirChangements] = useState(false)
  const [confirmation, setConfirmation] = useState<'publier' | 'annuler' | null>(null)
  const [palette, setPalette] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [occupe, setOccupe] = useState(false)
  const minuterie = useRef<number | undefined>(undefined)
  const compteur = useRef(0)
  const enAttenteDeNom = useRef<{ graphe: Graphe; relances: Relances | null } | null>(null)

  const tester = useCallback(async (id: string) => {
    if (!id) return setTest(null)
    try {
      setTest(await api.testerCircuit(id))
    } catch (probleme) {
      setErreur((probleme as Error).message)
    }
  }, [])

  const charger = useCallback(async () => {
    try {
      const [cat, actuel, ecarts] = await Promise.all([api.catalogueCircuit(), api.brouillon(), api.differences()])
      setCatalogue(cat)
      setBrouillon(actuel)
      // Le moteur omet « sortie » quand elle est vide : on la remet à null, pour reconnaître chaque lien.
      setGraphe({ ...actuel.graphe, liens: actuel.graphe.liens.map((lien) => ({ ...lien, sortie: lien.sortie ?? null })) })
      setRelances(actuel.relances)
      setChangements(ecarts.changements)
      setStatut(actuel.a_completer ? { etat: 'incomplet', message: actuel.a_completer } : { etat: 'repos' })
      setErreur(null)
    } catch (probleme) {
      setErreur((probleme as Error).message)
    }
  }, [])

  useEffect(() => {
    charger()
    return () => window.clearTimeout(minuterie.current)
  }, [charger])

  const enregistrer = useCallback(
    async (suite: Graphe, suiteRelances: Relances | null, numero: number) => {
      if (!auteur.trim()) {
        enAttenteDeNom.current = { graphe: suite, relances: suiteRelances }
        setStatut({ etat: 'erreur', message: 'indiquez votre nom en haut à droite, chaque modification est inscrite à un nom.' })
        surSansAuteur()
        return
      }
      try {
        const enregistre = await api.enregistrerBrouillon(suite, suiteRelances, auteur.trim())
        if (numero !== compteur.current) return // une modification plus récente est partie après celle-ci
        setBrouillon(enregistre)
        setStatut(enregistre.a_completer ? { etat: 'incomplet', message: enregistre.a_completer } : { etat: 'enregistre' })
        setChangements((await api.differences()).changements)
        if (factureTest && !enregistre.a_completer) await tester(factureTest)
        else if (enregistre.a_completer) setTest(null) // un circuit incomplet ne se teste pas
      } catch (probleme) {
        if (numero === compteur.current) setStatut({ etat: 'erreur', message: (probleme as Error).message })
      }
    },
    [auteur, factureTest, surSansAuteur, tester],
  )

  /** Chaque modification part au brouillon 600 ms après la dernière action. */
  const modifier = useCallback(
    (suite: Graphe, suiteRelances: Relances | null) => {
      setGraphe(suite)
      setRelances(suiteRelances)
      setStatut({ etat: 'enregistrement' })
      setConfirmation(null)
      const numero = ++compteur.current
      window.clearTimeout(minuterie.current)
      minuterie.current = window.setTimeout(() => enregistrer(suite, suiteRelances, numero), DELAI_ENREGISTREMENT_MS)
    },
    [enregistrer],
  )

  // Le nom saisi après coup : la modification en attente part.
  useEffect(() => {
    if (auteur.trim() && enAttenteDeNom.current) {
      const { graphe: g, relances: r } = enAttenteDeNom.current
      enAttenteDeNom.current = null
      modifier(g, r)
    }
  }, [auteur, modifier])

  // Échap ferme le réglage de l'étape (hors saisie).
  useEffect(() => {
    const touche = (evenement: KeyboardEvent) => {
      const cible = evenement.target as HTMLElement | null
      if (evenement.key === 'Escape' && !cible?.matches?.('input, textarea, select')) {
        setChoisie(null)
        setPalette(false)
      }
    }
    window.addEventListener('keydown', touche)
    return () => window.removeEventListener('keydown', touche)
  }, [])

  const lues = useMemo(() => factures.filter((facture) => LUES.has(facture.etat)).slice(0, 20), [factures])

  if (!catalogue || !brouillon || !graphe) {
    return <div className="page">{erreur ? <p className="connecteurs__message">{erreur}</p> : <p className="note">Chargement du circuit…</p>}</div>
  }

  const etape = graphe.noeuds.find((noeud) => noeud.id === choisie) ?? null
  const enService = brouillon.version_en_service
  const prochaine = (enService ?? 0) + 1
  const peutPublier = brouillon.modifie && !brouillon.a_completer && changements.length > 0 && statut.etat !== 'enregistrement' && statut.etat !== 'erreur'

  const ajouter = (type: TypeEtape) => {
    // La nouvelle étape se pose sous le circuit, au milieu : on la déplace ensuite où l'on veut.
    const xs = graphe.noeuds.map((n) => n.x)
    const x = Math.round((Math.min(...xs) + Math.max(...xs)) / 2 / 20) * 20
    const y = Math.max(...graphe.noeuds.map((n) => n.y)) + 160
    const nouvelle = nouvelleEtape(type, catalogue, x, y)
    modifier({ ...graphe, noeuds: [...graphe.noeuds, nouvelle] }, relances)
    setPalette(false)
    setChoisie(nouvelle.id)
  }

  const changerEtape = (modifiee: NoeudGraphe) => modifier({ ...graphe, noeuds: graphe.noeuds.map((n) => (n.id === modifiee.id ? modifiee : n)) }, relances)

  const retirer = () => {
    if (!etape) return
    modifier({ noeuds: graphe.noeuds.filter((n) => n.id !== etape.id), liens: graphe.liens.filter((l) => l.de !== etape.id && l.vers !== etape.id) }, relances)
    setChoisie(null)
  }

  const annuler = async () => {
    setOccupe(true)
    window.clearTimeout(minuterie.current)
    compteur.current++
    try {
      await api.annulerBrouillon()
      await charger()
      if (factureTest) await tester(factureTest)
      setConfirmation(null)
      setChoisie(null)
      surInformation('Modifications annulées : le circuit est revenu à la version en service.')
    } catch (probleme) {
      setErreur((probleme as Error).message)
    } finally {
      setOccupe(false)
    }
  }

  const publier = async () => {
    if (!auteur.trim()) {
      setConfirmation(null)
      setErreur('Indiquez votre nom en haut à droite : chaque publication est inscrite à un nom.')
      return surSansAuteur()
    }
    setOccupe(true)
    try {
      const publiee = await api.publierCircuit(auteur.trim())
      setConfirmation(null)
      setVoirChangements(false)
      await charger()
      if (factureTest) await tester(factureTest)
      surInformation(`Version ${publiee.version} publiée : les nouvelles factures suivent ce circuit. Celles en cours gardent le leur.`)
    } catch (probleme) {
      setErreur((probleme as Error).message)
    } finally {
      setOccupe(false)
    }
  }

  return (
    <div className="editeur">
      <div className="editeur__principal">
        <header className="barre-circuit">
          <div className="barre-circuit__gauche">
          <h1>Circuit des factures</h1>
          <span className="etat etat--validee">{enService ? `Version ${enService} en service` : 'Aucune version publiée'}</span>
          {brouillon.modifie && changements.length > 0 && (
            <button className="etat etat--en_anomalie barre-circuit__brouillon" aria-expanded={voirChangements} onClick={() => setVoirChangements(!voirChangements)}>
              Brouillon : {pluriel(changements.length, 'modification')}
              <Icone nom="deplier" taille={12} />
            </button>
          )}

          </div>
          {onglets}
          <div className="barre-circuit__droite">
          <label className="barre-circuit__test">
            <Icone nom="test" />
            <span className="visuellement-cache">Tester sur une facture</span>
            <select
              className="champ"
              value={factureTest}
              onChange={(evenement) => {
                setFactureTest(evenement.target.value)
                tester(evenement.target.value)
              }}
            >
              <option value="">Tester sur une facture…</option>
              {lues.map((facture) => (
                <option key={facture.id} value={facture.id}>
                  {facture.fournisseur_nom ?? facture.nom_fichier} · {facture.numero_facture ?? 'sans numéro'}
                  {facture.total_ttc ? ` · ${euros(facture.total_ttc)}` : ''}
                </option>
              ))}
            </select>
          </label>

          <div className="barre-circuit__actions">
            {confirmation ? (
              <>
                <span className="barre-circuit__question">{confirmation === 'publier' ? `Publier la version ${prochaine} ?` : 'Jeter le brouillon ?'}</span>
                <button className="bouton bouton--fantome" onClick={() => setConfirmation(null)} disabled={occupe}>
                  Non
                </button>
                <button className={`bouton ${confirmation === 'publier' ? 'bouton--plein' : 'bouton--danger'}`} onClick={confirmation === 'publier' ? publier : annuler} disabled={occupe}>
                  {confirmation === 'publier' ? 'Oui, publier' : 'Oui, annuler'}
                </button>
              </>
            ) : (
              <>
                {brouillon.modifie && (
                  <button className="bouton bouton--fantome" onClick={() => setConfirmation('annuler')} disabled={occupe}>
                    Annuler
                  </button>
                )}
                <button className="bouton bouton--plein" onClick={() => setConfirmation('publier')} disabled={!peutPublier || occupe} title={peutPublier ? undefined : brouillon.a_completer ? `À compléter : ${brouillon.a_completer}` : 'Modifiez le circuit pour pouvoir publier'}>
                  Publier la version {prochaine}
                </button>
              </>
            )}
          </div>
          </div>
        </header>

        {(voirChangements || confirmation === 'publier') && changements.length > 0 && (
          <ul className="bande bande--changements">
            {changements.map((changement) => (
              <li key={changement.texte}>{changement.texte}</li>
            ))}
          </ul>
        )}

        {test && (
          <p className={`bande bande--test${test.change ? ' bande--change' : ''}`} role="status">
            <Icone nom="test" />
            <span>
              <strong>{test.facture.numero ?? 'Facture'}</strong>
              {test.facture.total_ttc && `, ${euros(test.facture.total_ttc)}`} : {test.bloque ? `bloquée (${test.bloque})` : `approuvée par ${test.niveaux.map((n) => catalogue.niveaux.find((c) => c.code === n.niveau)!.libelle.toLowerCase()).join(', ')}`}.
              {test.change && <strong> Différent de la version en service.</strong>}
            </span>
            <button
              className="bouton bouton--fantome bouton--petit bouton--icone"
              aria-label="Arrêter le test"
              onClick={() => {
                setFactureTest('')
                setTest(null)
              }}
            >
              <Icone nom="fermer" taille={14} />
            </button>
          </p>
        )}

        {erreur && (
          <p className="bande bande--erreur" role="alert">
            {erreur}
          </p>
        )}

        <div className="editeur__canevas">
          <SchemaCircuit
            graphe={graphe}
            catalogue={catalogue}
            test={test}
            choisie={choisie}
            surGraphe={(suite) => modifier(suite, relances)}
            surChoix={(id) => {
              setChoisie(id)
              if (id) setPalette(false)
            }}
          />
          {!etape && !palette && (
            <button className="editeur__ajouter" onClick={() => setPalette(true)} aria-label="Ajouter une étape" title="Ajouter une étape">
              <Icone nom="plus" taille={20} />
            </button>
          )}
          {statut.etat !== 'repos' && !etape && !palette && (
            <p className={`editeur__etat editeur__etat--${statut.etat}`} role="status">
              {statut.etat === 'enregistrement' && 'Enregistrement…'}
              {statut.etat === 'enregistre' && 'Brouillon enregistré'}
              {statut.etat === 'incomplet' && `À compléter : ${statut.message}`}
              {statut.etat === 'erreur' && `Non enregistré : ${statut.message}`}
            </p>
          )}
      {(etape || palette) && (
      <PanneauEtape
        key={etape?.id ?? 'palette'}
        etape={etape}
        catalogue={catalogue}
        relances={relances}
        test={test}
        statut={statut}
        surEtape={changerEtape}
        surRelances={(suite) => modifier(graphe, suite)}
        surRetrait={retirer}
        surAjout={ajouter}
        surFermer={() => {
          setChoisie(null)
          setPalette(false)
        }}
      />
      )}
        </div>
      </div>

    </div>
  )
}
