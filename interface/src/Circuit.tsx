// La page Circuit : le schéma, le panneau de réglage, et l'en-tête (différences, annuler, tester, publier).
// Chaque modification est enregistrée dans le brouillon, qu'aucune facture ne voit avant la publication.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import * as api from './api'
import type { BrouillonCircuit, Catalogue, Changement, FactureResume, Niveau, Regle, Relances, ResultatTest } from './api'
import { euros } from './format'
import { Icone } from './Icones'
import { PanneauEtape, type Statut, nouvelleRegle } from './PanneauEtape'
import { SchemaCircuit, type Selection } from './SchemaCircuit'

const DELAI_ENREGISTREMENT_MS = 600
const LUES = new Set(['a_valider', 'en_approbation', 'en_anomalie', 'validee', 'rejetee', 'exportee'])

function Fenetre({ titre, children, actions, surFermer }: { titre: string; children: ReactNode; actions: ReactNode; surFermer: () => void }) {
  return (
    <div className="voile" onClick={surFermer} onKeyDown={(evenement) => evenement.key === 'Escape' && surFermer()}>
      <div className="fenetre" role="dialog" aria-modal="true" aria-labelledby="fenetre-titre" onClick={(evenement) => evenement.stopPropagation()}>
        <h2 id="fenetre-titre">{titre}</h2>
        <div className="fenetre__corps">{children}</div>
        <div className="fenetre__actions">{actions}</div>
      </div>
    </div>
  )
}

const pluriel = (n: number, mot: string) => `${n} ${mot}${n > 1 ? 's' : ''}`

export function Circuit({
  auteur,
  factures,
  surSansAuteur,
  surInformation,
}: {
  auteur: string
  factures: FactureResume[]
  surSansAuteur: () => void
  surInformation: (message: string) => void
}) {
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null)
  const [regles, setRegles] = useState<Regle[]>([])
  const [relances, setRelances] = useState<Relances | null>(null)
  const [brouillon, setBrouillon] = useState<BrouillonCircuit | null>(null)
  const [changements, setChangements] = useState<Changement[]>([])
  const [selection, setSelection] = useState<Selection>(null)
  const [statut, setStatut] = useState<Statut>({ etat: 'repos' })
  const [test, setTest] = useState<ResultatTest | null>(null)
  const [factureTest, setFactureTest] = useState<string | null>(null)
  const [fenetre, setFenetre] = useState<'differences' | 'annuler' | 'publier' | null>(null)
  const [menu, setMenu] = useState<'ajout' | 'test' | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [occupe, setOccupe] = useState(false)
  const minuterie = useRef<number | undefined>(undefined)
  const compteur = useRef(0)
  const enAttenteDeNom = useRef<{ regles: Regle[]; relances: Relances | null } | null>(null)

  const tester = useCallback(async (id: string | null) => {
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
      setRegles(actuel.regles)
      setRelances(actuel.relances)
      setChangements(ecarts.changements)
      setStatut({ etat: 'repos' })
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
    async (suiteRegles: Regle[], suiteRelances: Relances | null, numero: number) => {
      if (!auteur.trim()) {
        enAttenteDeNom.current = { regles: suiteRegles, relances: suiteRelances }
        setStatut({ etat: 'erreur', message: 'Indiquez votre nom en haut à droite : chaque modification est inscrite à un nom.' })
        surSansAuteur()
        return
      }
      try {
        const enregistre = await api.enregistrerBrouillon(suiteRegles, suiteRelances, auteur.trim())
        if (numero !== compteur.current) return // une modification plus récente est partie après celle-ci
        setBrouillon(enregistre)
        setStatut({ etat: 'enregistre' })
        setChangements((await api.differences()).changements)
        if (factureTest) await tester(factureTest)
      } catch (probleme) {
        if (numero === compteur.current) setStatut({ etat: 'erreur', message: (probleme as Error).message })
      }
    },
    [auteur, factureTest, surSansAuteur, tester],
  )

  /** Chaque modification part au brouillon 600 ms après la dernière frappe. */
  const modifier = useCallback(
    (suiteRegles: Regle[], suiteRelances: Relances | null) => {
      setRegles(suiteRegles)
      setRelances(suiteRelances)
      setStatut({ etat: 'enregistrement' })
      const numero = ++compteur.current
      window.clearTimeout(minuterie.current)
      minuterie.current = window.setTimeout(() => enregistrer(suiteRegles, suiteRelances, numero), DELAI_ENREGISTREMENT_MS)
    },
    [enregistrer],
  )

  // Le nom saisi après coup : la modification en attente part.
  useEffect(() => {
    if (auteur.trim() && enAttenteDeNom.current) {
      const { regles: r, relances: rel } = enAttenteDeNom.current
      enAttenteDeNom.current = null
      modifier(r, rel)
    }
  }, [auteur, modifier])

  // Échap ferme le panneau de réglage (hors saisie).
  useEffect(() => {
    const touche = (evenement: KeyboardEvent) => {
      if (evenement.key !== 'Escape' || (evenement.target as HTMLElement).matches('input, textarea, select')) return
      if (fenetre) setFenetre(null)
      else if (menu) setMenu(null)
      else setSelection(null)
    }
    window.addEventListener('keydown', touche)
    return () => window.removeEventListener('keydown', touche)
  }, [fenetre, menu])

  const modifiees = useMemo(() => new Set(changements.filter((c) => c.regle).map((c) => c.regle!)), [changements])
  const relancesModifiees = useMemo(() => new Set(changements.filter((c) => c.niveau).map((c) => c.niveau!)), [changements])
  const lues = useMemo(() => factures.filter((facture) => LUES.has(facture.etat)).slice(0, 12), [factures])

  if (!catalogue || !brouillon) {
    return <div className="page">{erreur ? <p className="connecteurs__message">{erreur}</p> : <p className="note">Chargement du circuit…</p>}</div>
  }

  const enService = brouillon.version_en_service
  const prochaine = (enService ?? 0) + 1
  const peutPublier = brouillon.modifie && changements.length > 0 && statut.etat !== 'enregistrement' && statut.etat !== 'erreur'
  const libelle = (code: Niveau) => catalogue.niveaux.find((n) => n.code === code)!.libelle
  const factureTestee = test ? factures.find((facture) => facture.id === test.facture.id) : null

  const ajouterRegle = (niveau: Niveau | null) => {
    modifier([...regles, nouvelleRegle(regles, catalogue, niveau)], relances)
    setSelection(niveau ? { genre: 'niveau', niveau } : { genre: 'blocage' })
    setMenu(null)
  }

  const annuler = async () => {
    setOccupe(true)
    window.clearTimeout(minuterie.current)
    compteur.current++
    try {
      await api.annulerBrouillon()
      await charger()
      if (factureTest) await tester(factureTest)
      setFenetre(null)
      surInformation('Modifications annulées : le circuit est revenu à la version en service.')
    } catch (probleme) {
      setErreur((probleme as Error).message)
    } finally {
      setOccupe(false)
    }
  }

  const publier = async () => {
    if (!auteur.trim()) {
      setFenetre(null)
      setErreur('Indiquez votre nom en haut à droite : chaque publication est inscrite à un nom.')
      return surSansAuteur()
    }
    setOccupe(true)
    try {
      const publiee = await api.publierCircuit(auteur.trim())
      setFenetre(null)
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
    <div className={`editeur${selection ? ' editeur--panneau' : ''}`}>
      <div className="editeur__principal">
        <header className="editeur__tete">
          <div className="editeur__titre">
            <h1>Circuit de validation des factures</h1>
            <p className="editeur__pastilles">
              <span className="etat etat--validee">{enService ? `Version ${enService} en service` : 'Aucune version publiée'}</span>
              {brouillon.modifie && (
                <span className="etat etat--en_anomalie">
                  Brouillon : {pluriel(changements.length, 'modification')}, pas encore publiée{changements.length > 1 ? 's' : ''}
                </span>
              )}
              {brouillon.modifie && changements.length > 0 && (
                <button className="lien-bouton lien-bouton--vert" onClick={() => setFenetre('differences')}>
                  Voir les différences
                </button>
              )}
            </p>
            <p className="editeur__aide">Qui approuve, quand, et ce qui bloque une facture avant le paiement.</p>
          </div>
          <div className="editeur__actions">
            {brouillon.modifie && (
              <button className="bouton bouton--fantome" onClick={() => setFenetre('annuler')} disabled={occupe}>
                Annuler les modifications
              </button>
            )}
            <div className="menu-deroulant">
              <button className="bouton" aria-expanded={menu === 'test'} aria-haspopup="menu" onClick={() => setMenu(menu === 'test' ? null : 'test')}>
                <Icone nom="test" /> Tester une facture
              </button>
              {menu === 'test' && (
                <div className="menu-deroulant__liste" role="menu" aria-label="Choisir une facture à tester">
                  {lues.length === 0 && <p className="menu-deroulant__vide">Aucune facture lue pour l’instant.</p>}
                  {lues.map((facture) => (
                    <button
                      key={facture.id}
                      role="menuitem"
                      onClick={() => {
                        setFactureTest(facture.id)
                        tester(facture.id)
                        setMenu(null)
                      }}
                    >
                      <strong>{facture.fournisseur_nom ?? facture.nom_fichier}</strong>
                      <small>
                        {facture.numero_facture ?? 'sans numéro'}
                        {facture.total_ttc && ` · ${euros(facture.total_ttc)}`}
                      </small>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button className="bouton bouton--plein" onClick={() => setFenetre('publier')} disabled={!peutPublier || occupe} title={peutPublier ? undefined : 'Modifiez le circuit pour pouvoir publier'}>
              Publier la version {prochaine}
            </button>
          </div>
        </header>

        {erreur && (
          <p className="connecteurs__message" role="alert">
            {erreur}
          </p>
        )}

        {test && (
          <div className={`editeur__test${test.change ? ' editeur__test--change' : ''}`} role="status">
            <Icone nom="test" />
            <p>
              <strong>Test : </strong>
              {test.facture.fournisseur ?? 'Facture'} {test.facture.numero && `n° ${test.facture.numero}`}
              {test.facture.total_ttc && `, ${euros(test.facture.total_ttc)}`}. Le chemin en vert est celui qu’elle prendrait avec{' '}
              {test.circuit_teste === 'brouillon' ? 'le brouillon' : 'la version en service'}.
              {test.change && (
                <>
                  {' '}
                  <strong>Différent de la version en service</strong>, qui demandait :{' '}
                  {test.en_service.bloque ? 'un blocage' : test.en_service.niveaux.map((n) => libelle(n).toLowerCase()).join(', ') || 'aucune approbation'}.
                </>
              )}
              {factureTestee && factureTestee.etat === 'en_anomalie' && ' Cette facture est en anomalie.'}
            </p>
            <button
              className="bouton bouton--fantome bouton--petit"
              onClick={() => {
                setFactureTest(null)
                setTest(null)
              }}
            >
              Arrêter le test
            </button>
          </div>
        )}

        <div className="editeur__outils">
          <div className="menu-deroulant">
            <button className="bouton bouton--vert-pale" aria-expanded={menu === 'ajout'} aria-haspopup="menu" onClick={() => setMenu(menu === 'ajout' ? null : 'ajout')}>
              <Icone nom="plus" /> Ajouter une étape
            </button>
            {menu === 'ajout' && (
              <div className="menu-deroulant__liste menu-deroulant__liste--gauche" role="menu" aria-label="Types d’étapes">
                <p className="menu-deroulant__section">Approbation : qui approuve</p>
                {catalogue.niveaux.map((niveau) => (
                  <button key={niveau.code} role="menuitem" onClick={() => ajouterRegle(niveau.code)}>
                    <strong>{niveau.libelle}</strong>
                    <small>Ajouter une règle qui exige son approbation</small>
                  </button>
                ))}
                <p className="menu-deroulant__section">Autres étapes</p>
                <button role="menuitem" onClick={() => ajouterRegle(null)}>
                  <strong>Blocage par règle</strong>
                  <small>Empêcher l’approbation tant qu’un problème n’est pas réglé</small>
                </button>
                {catalogue.etapes
                  .filter((etape) => !etape.fixe && etape.disponible === false)
                  .map((etape) => (
                    <button key={etape.type} role="menuitem" disabled>
                      <strong>
                        {etape.libelle} <span className="pastille-bientot">Bientôt</span>
                      </strong>
                    </button>
                  ))}
              </div>
            )}
          </div>
        </div>

        <SchemaCircuit
          regles={regles}
          catalogue={catalogue}
          test={test}
          selection={selection}
          modifiees={modifiees}
          relancesModifiees={relancesModifiees}
          surSelection={(choix) => {
            setSelection(choix)
            setMenu(null)
          }}
        />
      </div>

      {selection && (
        <PanneauEtape
          key={selection.genre === 'niveau' ? selection.niveau : 'blocage'}
          selection={selection}
          regles={regles}
          relances={relances}
          catalogue={catalogue}
          test={test}
          statut={statut}
          surRegles={(suite) => modifier(suite, relances)}
          surRelances={(suite) => modifier(regles, suite)}
          surFermer={() => setSelection(null)}
        />
      )}

      {fenetre === 'differences' && (
        <Fenetre titre="Ce que le brouillon change" surFermer={() => setFenetre(null)} actions={<button className="bouton" onClick={() => setFenetre(null)}>Fermer</button>}>
          <ul className="differences">
            {changements.map((changement) => (
              <li key={changement.texte} className={`differences__${changement.genre}`}>
                {changement.texte}
              </li>
            ))}
          </ul>
        </Fenetre>
      )}

      {fenetre === 'annuler' && (
        <Fenetre
          titre="Annuler les modifications ?"
          surFermer={() => setFenetre(null)}
          actions={
            <>
              <button className="bouton bouton--fantome" onClick={() => setFenetre(null)}>
                Garder le brouillon
              </button>
              <button className="bouton bouton--danger" onClick={annuler} disabled={occupe}>
                Annuler les modifications
              </button>
            </>
          }
        >
          <p>Le brouillon est jeté : le circuit revient à la version {enService ?? 'de départ'}. Aucune facture n’est touchée.</p>
        </Fenetre>
      )}

      {fenetre === 'publier' && (
        <Fenetre
          titre={`Publier la version ${prochaine} ?`}
          surFermer={() => setFenetre(null)}
          actions={
            <>
              <button className="bouton bouton--fantome" onClick={() => setFenetre(null)}>
                Pas maintenant
              </button>
              <button className="bouton bouton--plein" onClick={publier} disabled={occupe}>
                Publier la version {prochaine}
              </button>
            </>
          }
        >
          <p>Les nouvelles factures suivront ce circuit. Celles déjà en cours gardent le leur. Ce qui change :</p>
          <ul className="differences">
            {changements.map((changement) => (
              <li key={changement.texte} className={`differences__${changement.genre}`}>
                {changement.texte}
              </li>
            ))}
          </ul>
        </Fenetre>
      )}
    </div>
  )
}
