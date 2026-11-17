// Le panneau de réglage d'une étape : construit à partir du catalogue du moteur (champs, comparaisons,
// anomalies, bornes des relances). Aucun champ n'est écrit en dur ici.
import type { Catalogue, ChampCondition, Condition, LigneCondition, Niveau, NoeudGraphe, Relance, Relances, ResultatTest, TypeEtape } from './api'
import { Icone } from './Icones'
import { ICONE_ETAPE, nomEtape } from './SchemaCircuit'

export type Statut = { etat: 'repos' } | { etat: 'enregistrement' } | { etat: 'enregistre' } | { etat: 'erreur'; message: string }

type Champ = Catalogue['champs'][number]

function valeurParDefaut(champ: Champ, catalogue: Catalogue): string | string[] {
  if (champ.genre === 'anomalies') return [catalogue.anomalies.find((anomalie) => anomalie.utilisable)!.code]
  return champ.genre === 'montant' ? '1000' : ''
}

function LigneEditee({
  ligne,
  catalogue,
  rang,
  verdict,
  surChangement,
  surRetrait,
}: {
  ligne: LigneCondition
  catalogue: Catalogue
  rang: number
  verdict?: boolean
  surChangement: (ligne: LigneCondition) => void
  surRetrait: () => void
}) {
  const champ = catalogue.champs.find((c) => c.champ === ligne.champ)!
  const utilisables = catalogue.anomalies.filter((anomalie) => anomalie.utilisable)
  const cochees = Array.isArray(ligne.valeur) ? ligne.valeur : []
  return (
    <div className={`condition${verdict === true ? ' condition--vraie' : ''}`}>
      <div className="condition__champs">
        <select
          className="champ"
          aria-label={`Condition ${rang} : champ`}
          value={ligne.champ}
          onChange={(evenement) => {
            const nouveau = catalogue.champs.find((c) => c.champ === (evenement.target.value as ChampCondition))!
            surChangement({ champ: nouveau.champ, comparaison: nouveau.comparaisons[0].code, valeur: valeurParDefaut(nouveau, catalogue) })
          }}
        >
          {catalogue.champs.map((c) => (
            <option key={c.champ} value={c.champ}>
              {c.libelle}
            </option>
          ))}
        </select>
        <select
          className="champ"
          aria-label={`Condition ${rang} : comparaison`}
          value={ligne.comparaison}
          onChange={(evenement) => surChangement({ ...ligne, comparaison: evenement.target.value as LigneCondition['comparaison'] })}
        >
          {champ.comparaisons.map((comparaison) => (
            <option key={comparaison.code} value={comparaison.code}>
              {comparaison.libelle}
            </option>
          ))}
        </select>
        {champ.genre !== 'anomalies' && (
          <label className="condition__valeur">
            <input
              className="champ"
              aria-label={`Condition ${rang} : valeur`}
              inputMode={champ.genre === 'montant' ? 'decimal' : 'text'}
              value={typeof ligne.valeur === 'string' ? ligne.valeur : ''}
              placeholder={champ.genre === 'montant' ? '1 000' : 'Texte'}
              onChange={(evenement) => surChangement({ ...ligne, valeur: evenement.target.value })}
            />
            {champ.genre === 'montant' && <span aria-hidden="true">€</span>}
          </label>
        )}
      </div>
      {champ.genre === 'anomalies' && (
        <fieldset className="condition__anomalies">
          <legend className="visuellement-cache">Anomalies de la condition {rang}</legend>
          {utilisables.map((anomalie) => (
            <label key={anomalie.code}>
              <input
                type="checkbox"
                checked={cochees.includes(anomalie.code)}
                onChange={(evenement) => {
                  const suite = evenement.target.checked ? [...cochees, anomalie.code] : cochees.filter((code) => code !== anomalie.code)
                  surChangement({ ...ligne, valeur: suite })
                }}
              />
              {anomalie.libelle}
            </label>
          ))}
        </fieldset>
      )}
      <div className="condition__pied">
        <button className="lien-bouton" onClick={surRetrait}>
          Retirer
        </button>
        {verdict !== undefined && <span className={verdict ? 'condition__verdict condition__verdict--vraie' : 'condition__verdict'}>{verdict ? 'vraie pour le test' : 'fausse pour le test'}</span>}
      </div>
    </div>
  )
}

export function ConditionEditee({
  condition,
  catalogue,
  verdicts,
  surChangement,
}: {
  condition: Condition
  catalogue: Catalogue
  verdicts?: boolean[]
  surChangement: (condition: Condition) => void
}) {
  const lignes = condition.lignes ?? []
  const ajouter = () => {
    const champ = catalogue.champs[0]
    const nouvelle: LigneCondition = { champ: champ.champ, comparaison: champ.comparaisons[0].code, valeur: valeurParDefaut(champ, catalogue) }
    surChangement({ lignes: [...lignes, nouvelle], combinaison: condition.combinaison ?? 'une' })
  }
  if (condition.toujours) {
    return (
      <div className="condition condition--toujours">
        <p>
          <strong>Toujours</strong> : toutes les factures.
        </p>
        <button className="lien-bouton" onClick={ajouter}>
          + Mettre une condition
        </button>
      </div>
    )
  }
  return (
    <>
      {lignes.length > 1 && (
        <div className="segment" role="radiogroup" aria-label="Combinaison des conditions">
          {(['une', 'toutes'] as const).map((combinaison) => (
            <button
              key={combinaison}
              role="radio"
              aria-checked={(condition.combinaison ?? 'une') === combinaison}
              onClick={() => surChangement({ ...condition, combinaison })}
            >
              {combinaison === 'une' ? 'Une condition suffit' : 'Toutes les conditions'}
            </button>
          ))}
        </div>
      )}
      {lignes.map((ligne, rang) => (
        <LigneEditee
          key={rang}
          ligne={ligne}
          rang={rang + 1}
          catalogue={catalogue}
          verdict={verdicts?.[rang]}
          surChangement={(modifiee) => surChangement({ ...condition, lignes: lignes.map((l, r) => (r === rang ? modifiee : l)) })}
          surRetrait={() => (lignes.length === 1 ? surChangement({ toujours: true }) : surChangement({ ...condition, lignes: lignes.filter((_, r) => r !== rang) }))}
        />
      ))}
      <button className="lien-bouton lien-bouton--vert" onClick={ajouter}>
        + Ajouter une condition
      </button>
    </>
  )
}

/** Une étape neuve du type demandé, placée à l'endroit donné. */
export function nouvelleEtape(type: TypeEtape, catalogue: Catalogue, x: number, y: number): NoeudGraphe {
  const id = `${type}-${Math.random().toString(36).slice(2, 8)}`
  if (type === 'condition') return { id, type, x, y, nom: 'Montant élevé ?', si: { lignes: [{ champ: 'total_ttc', comparaison: 'superieur_a', valeur: '1000' }], combinaison: 'une' } }
  if (type === 'approbation') return { id, type, x, y, nom: '', niveau: catalogue.niveaux[0].code }
  return { id, type, x, y, nom: 'Blocage', message: 'À régler avant toute approbation.' }
}

function Palette({ catalogue, surAjout }: { catalogue: Catalogue; surAjout: (type: TypeEtape) => void }) {
  return (
    <div className="palette">
      <p className="reglage__aide">Cliquez sur une étape pour l’ajouter au canevas, puis reliez-la en tirant depuis ses points.</p>
      {catalogue.etapes
        .filter((etape) => !etape.fixe)
        .map((etape) => {
          const disponible = etape.disponible !== false
          return (
            <button key={etape.type} className={`palette__etape palette__etape--${etape.type}`} disabled={!disponible} onClick={() => surAjout(etape.type as TypeEtape)}>
              <span className="palette__tuile">
                <Icone nom={disponible ? ICONE_ETAPE[etape.type as TypeEtape] : 'horloge'} taille={18} />
              </span>
              <span>
                <strong>
                  {etape.libelle}
                  {!disponible && <span className="pastille-bientot">Bientôt</span>}
                </strong>
                <small>{etape.description}</small>
              </span>
            </button>
          )
        })}
      <p className="palette__astuce">
        <Icone nom="cadenas" taille={14} /> Début et Odoo sont fixes : ils protègent le paiement.
        <br />
        Supprimer : choisir une étape ou un lien, puis la touche Suppr.
      </p>
    </div>
  )
}

export function PanneauEtape({
  etape,
  catalogue,
  relances,
  test,
  statut,
  surEtape,
  surRelances,
  surRetrait,
  surAjout,
  surFermer,
}: {
  etape: NoeudGraphe | null
  catalogue: Catalogue
  relances: Relances | null
  test: ResultatTest | null
  statut: Statut
  surEtape: (etape: NoeudGraphe) => void
  surRelances: (relances: Relances) => void
  surRetrait: () => void
  surAjout: (type: TypeEtape) => void
  surFermer: () => void
}) {
  const libelle = (code: Niveau) => catalogue.niveaux.find((n) => n.code === code)!.libelle
  const verdict = etape && test?.conditions.find((condition) => condition.id === etape.id)
  const surLeChemin = etape && test ? test.chemin.some((pas) => pas.id === etape.id) : null
  const niveau = etape?.type === 'approbation' ? etape.niveau! : null
  const reglage: Relance | null = niveau ? ({ ...Object.fromEntries(catalogue.relances.map((r) => [r.nom, r.defaut])), ...relances?.[niveau] } as Relance) : null
  const fixe = etape?.type === 'debut' || etape?.type === 'fin'

  return (
    <aside className="panneau panneau--etape" aria-label={etape ? 'Réglage de l’étape' : 'Ajouter une étape'}>
      <header className="panneau__tete">
        {etape ? (
          <>
            <span className={`palette__tuile palette__tuile--${etape.type}`} aria-hidden="true">
              <Icone nom={ICONE_ETAPE[etape.type]} taille={18} />
            </span>
            <div className="panneau__titre">
              <p className="panneau__surtitre">{catalogue.etapes.find((e) => e.type === etape.type)?.libelle}</p>
              <h2>{nomEtape(etape, catalogue)}</h2>
            </div>
            <div className="panneau__boutons">
              {!fixe && (
                <button className="bouton bouton--fantome bouton--icone bouton--danger" onClick={surRetrait} aria-label="Supprimer l’étape" title="Supprimer l’étape (Suppr)">
                  <Icone nom="corbeille" />
                </button>
              )}
              <button className="bouton bouton--fantome bouton--icone" onClick={surFermer} aria-label="Fermer le réglage" title="Fermer (Échap)">
                <Icone nom="fermer" />
              </button>
            </div>
          </>
        ) : (
          <div className="panneau__titre">
            <h2>Ajouter une étape</h2>
          </div>
        )}
      </header>

      <div className="panneau__corps reglage">
        {!etape && <Palette catalogue={catalogue} surAjout={surAjout} />}

        {etape && test && (
          <p className={`reglage__test-ligne${surLeChemin ? ' reglage__test-ligne--oui' : ''}`}>
            <Icone nom="test" taille={14} />
            {surLeChemin ? 'La facture testée passe par cette étape.' : 'La facture testée ne passe pas par ici.'}
            {verdict && <strong>{verdict.vraie ? ' Réponse : Oui.' : ' Réponse : Non.'}</strong>}
          </p>
        )}

        {etape && fixe && (
          <p className="reglage__aide">
            {etape.type === 'debut'
              ? 'Chaque facture est reçue (mail, dépôt ou API), lue par l’IA et contrôlée (calculs, doublon, SIRET, IBAN, commande). Une anomalie bloquante l’arrête avant le circuit.'
              : 'Une fois approuvée, la facture est enregistrée dans Odoo avec son PDF.'}
          </p>
        )}

        {etape && !fixe && (
          <label className="reglage__champ">
            Nom affiché
            <input
              className="champ"
              value={etape.nom ?? ''}
              maxLength={200}
              placeholder={nomEtape({ ...etape, nom: '' }, catalogue)}
              onChange={(evenement) => surEtape({ ...etape, nom: evenement.target.value })}
            />
          </label>
        )}

        {etape?.type === 'condition' && etape.si && (
          <section className="reglage__bloc">
            <h3>Si</h3>
            <ConditionEditee condition={etape.si} catalogue={catalogue} verdicts={verdict?.lignes.map((l) => l.vraie)} surChangement={(si) => surEtape({ ...etape, si })} />
            <p className="reglage__note">Oui : la facture suit la sortie du haut. Non : celle du bas.</p>
          </section>
        )}

        {etape?.type === 'approbation' && niveau && reglage && (
          <>
            <label className="reglage__champ">
              Qui approuve
              <select className="champ" value={niveau} onChange={(evenement) => surEtape({ ...etape, niveau: evenement.target.value as Niveau })}>
                {catalogue.niveaux.map((n) => (
                  <option key={n.code} value={n.code}>
                    {n.libelle}
                  </option>
                ))}
              </select>
            </label>
            <section className="reglage__relances">
              <h3>Sans réponse ({libelle(niveau).toLowerCase()})</h3>
              <div className="reglage__grille">
                {catalogue.relances.map((champ) => (
                  <label key={champ.nom}>
                    {champ.libelle}
                    <span className="reglage__nombre">
                      <input
                        className="champ"
                        type="number"
                        min={champ.min}
                        max={champ.max}
                        value={reglage[champ.nom]}
                        onChange={(evenement) => {
                          const nombre = Number.parseInt(evenement.target.value, 10)
                          if (!Number.isNaN(nombre)) surRelances({ ...(relances ?? {}), [niveau]: { ...reglage, [champ.nom]: nombre } })
                        }}
                      />
                      <small>{champ.unite}</small>
                    </span>
                  </label>
                ))}
              </div>
            </section>
            <p className="reglage__garde">
              <Icone nom="cadenas" />
              <span>
                <strong>Toujours une autre personne que le niveau précédent</strong>, et les niveaux s’approuvent dans l’ordre : comptable, directeur financier, gérant.
              </span>
            </p>
          </>
        )}

        {etape?.type === 'blocage' && (
          <label className="reglage__champ">
            Message affiché sur la facture
            <input className="champ" value={etape.message ?? ''} maxLength={300} onChange={(evenement) => surEtape({ ...etape, message: evenement.target.value })} />
          </label>
        )}
      </div>

      <footer className={`reglage__statut reglage__statut--${statut.etat}`} role="status" aria-live="polite">
        {statut.etat === 'enregistrement' && 'Enregistrement…'}
        {statut.etat === 'enregistre' && (
          <>
            <Icone nom="coche" taille={14} /> Brouillon enregistré : aucune facture n’est touchée avant la publication.
          </>
        )}
        {statut.etat === 'erreur' && (
          <>
            <Icone nom="alerte" taille={14} /> À compléter : {statut.message}
          </>
        )}
        {statut.etat === 'repos' && 'Chaque modification est enregistrée dans le brouillon.'}
      </footer>
    </aside>
  )
}
