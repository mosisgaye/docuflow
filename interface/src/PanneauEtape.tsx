// Le panneau de réglage d'une étape : construit à partir du catalogue du moteur (champs, comparaisons,
// anomalies, bornes des relances). Aucun champ n'est écrit en dur ici.
import { useState } from 'react'
import type { Catalogue, ChampCondition, Condition, LigneCondition, Niveau, Regle, Relance, Relances, ResultatTest } from './api'
import { Icone } from './Icones'
import type { Selection } from './SchemaCircuit'

export type Statut = { etat: 'repos' } | { etat: 'enregistrement' } | { etat: 'enregistre' } | { etat: 'erreur'; message: string }

type Champ = Catalogue['champs'][number]

function valeurParDefaut(champ: Champ, catalogue: Catalogue): string | string[] {
  if (champ.genre === 'anomalies') return [catalogue.anomalies.find((anomalie) => anomalie.utilisable)!.code]
  return champ.genre === 'montant' ? '1000' : ''
}

function nomLibre(regles: Regle[], base: string) {
  const pris = new Set(regles.map((regle) => regle.nom.trim().toLowerCase()))
  if (!pris.has(base.toLowerCase())) return base
  let rang = 2
  while (pris.has(`${base} ${rang}`.toLowerCase())) rang++
  return `${base} ${rang}`
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

function ConditionEditee({
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

export function PanneauEtape({
  selection,
  regles,
  relances,
  catalogue,
  test,
  statut,
  surRegles,
  surRelances,
  surFermer,
}: {
  selection: Exclude<Selection, null>
  regles: Regle[]
  relances: Relances | null
  catalogue: Catalogue
  test: ResultatTest | null
  statut: Statut
  surRegles: (regles: Regle[]) => void
  surRelances: (relances: Relances) => void
  surFermer: () => void
}) {
  const [onglet, setOnglet] = useState<'reglages' | 'test'>('reglages')
  const niveau = selection.genre === 'niveau' ? selection.niveau : null
  const libelle = (code: Niveau) => catalogue.niveaux.find((n) => n.code === code)!.libelle
  const rangNiveau = niveau ? catalogue.niveaux.findIndex((n) => n.code === niveau) + 1 : 0
  const siennes = regles.map((regle, rang) => ({ regle, rang })).filter(({ regle }) => (niveau ? regle.exige?.includes(niveau) : regle.bloque))
  const ongletEffectif = test ? onglet : 'reglages'

  const changer = (rang: number, regle: Regle) => surRegles(regles.map((r, i) => (i === rang ? regle : r)))
  const retirer = (rang: number) => {
    const regle = regles[rang]
    if (niveau && regle.exige && regle.exige.length > 1) return changer(rang, { ...regle, exige: regle.exige.filter((n) => n !== niveau) })
    surRegles(regles.filter((_, i) => i !== rang))
  }
  const ajouter = () => {
    const anomalie = catalogue.anomalies.find((a) => a.code === 'FOURNISSEUR_INCONNU' && a.utilisable) ?? catalogue.anomalies.find((a) => a.utilisable)!
    const nouvelle: Regle = niveau
      ? { nom: nomLibre(regles, `${libelle(niveau)} : nouvelle règle`), si: { lignes: [{ champ: 'total_ttc', comparaison: 'superieur_a', valeur: '1000' }], combinaison: 'une' }, exige: [niveau] }
      : { nom: nomLibre(regles, 'Nouveau blocage'), si: { lignes: [{ champ: 'anomalie', comparaison: 'une_de', valeur: [anomalie.code] }], combinaison: 'une' }, bloque: 'À régler avant toute approbation.' }
    surRegles([...regles, nouvelle])
  }
  const reglage: Relance | null = niveau ? { ...Object.fromEntries(catalogue.relances.map((r) => [r.nom, r.defaut])), ...relances?.[niveau] } as Relance : null

  const resultatsTest = test?.regles ?? []
  const verdictsDe = (nom: string) => resultatsTest.find((r) => r.nom === nom)

  return (
    <aside className="panneau panneau--etape" aria-label="Réglage de l’étape">
      <header className="panneau__tete">
        <div className="panneau__titre">
          <p className="panneau__surtitre">{niveau ? `Niveau ${rangNiveau}` : 'Réglable'}</p>
          <h2>{niveau ? libelle(niveau) : 'Bloquée par règle'}</h2>
        </div>
        <div className="panneau__boutons">
          <button className="bouton bouton--fantome bouton--icone" onClick={surFermer} aria-label="Fermer le réglage" title="Fermer (Échap)">
            <Icone nom="fermer" />
          </button>
        </div>
      </header>
      <div className="onglets" role="tablist">
        <button role="tab" aria-selected={ongletEffectif === 'reglages'} onClick={() => setOnglet('reglages')}>
          <Icone nom="reglages" taille={14} /> Réglages
        </button>
        <button role="tab" aria-selected={ongletEffectif === 'test'} onClick={() => setOnglet('test')} disabled={!test} title={test ? undefined : 'Testez une facture pour voir le résultat'}>
          <Icone nom="test" taille={14} /> Résultat du test
        </button>
      </div>

      <div className="panneau__corps reglage">
        {ongletEffectif === 'reglages' ? (
          <>
            <p className="reglage__aide">
              {niveau
                ? `${libelle(niveau)} approuve la facture quand une de ces règles s’applique.`
                : 'Une facture qui remplit une de ces règles ne peut pas être approuvée : elle attend qu’on règle le problème.'}
            </p>
            {siennes.length === 0 && <p className="reglage__vide">{niveau ? 'Aucune règle : ce niveau n’intervient jamais.' : 'Aucune règle de blocage.'}</p>}
            {siennes.map(({ regle, rang }) => {
              const verdicts = verdictsDe(regle.nom)
              const autres = niveau ? (regle.exige ?? []).filter((n) => n !== niveau) : []
              return (
                <section key={rang} className={`regle${verdicts?.vraie ? ' regle--vraie' : ''}`}>
                  <label className="regle__nom">
                    <span className="visuellement-cache">Nom de la règle</span>
                    <input className="champ" value={regle.nom} maxLength={200} onChange={(evenement) => changer(rang, { ...regle, nom: evenement.target.value })} />
                  </label>
                  {autres.length > 0 && <p className="regle__note">Exige aussi : {autres.map((n) => libelle(n).toLowerCase()).join(', ')}.</p>}
                  <ConditionEditee
                    condition={regle.si}
                    catalogue={catalogue}
                    verdicts={verdicts?.lignes.map((ligne) => ligne.vraie)}
                    surChangement={(si) => changer(rang, { ...regle, si })}
                  />
                  {regle.bloque !== undefined && (
                    <label className="regle__message">
                      Message affiché
                      <input className="champ" value={regle.bloque} maxLength={300} onChange={(evenement) => changer(rang, { ...regle, bloque: evenement.target.value })} />
                    </label>
                  )}
                  <button className="lien-bouton lien-bouton--danger" onClick={() => retirer(rang)}>
                    {autres.length > 0 ? `Retirer ce niveau de la règle` : 'Retirer la règle'}
                  </button>
                </section>
              )
            })}
            <button className="bouton" onClick={ajouter}>
              <Icone nom="plus" /> {niveau ? 'Ajouter une règle' : 'Ajouter un blocage'}
            </button>

            {niveau && reglage && (
              <section className="reglage__relances">
                <h3>Sans réponse</h3>
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
                            if (Number.isNaN(nombre)) return
                            surRelances({ ...(relances ?? {}), [niveau]: { ...reglage, [champ.nom]: nombre } })
                          }}
                        />
                        <small>{champ.unite}</small>
                      </span>
                    </label>
                  ))}
                </div>
              </section>
            )}

            {niveau && (
              <p className="reglage__garde">
                <Icone nom="cadenas" />
                <span>
                  <strong>Toujours une autre personne que le niveau précédent.</strong> Ce réglage protège contre la fraude : il ne se désactive pas.
                </span>
              </p>
            )}
          </>
        ) : (
          test && (
            <div className="reglage__test">
              <p>
                Facture <strong>{test.facture.numero ?? test.facture.id.slice(0, 8)}</strong>
                {test.facture.fournisseur && <> · {test.facture.fournisseur}</>}
              </p>
              {siennes.length === 0 && <p className="reglage__vide">Aucune règle à évaluer ici.</p>}
              {siennes.map(({ regle }) => {
                const verdicts = verdictsDe(regle.nom)
                if (!verdicts) return null
                return (
                  <section key={regle.nom} className={`regle${verdicts.vraie ? ' regle--vraie' : ''}`}>
                    <h3>
                      {regle.nom} <span className={`etat ${verdicts.vraie ? 'etat--validee' : 'etat--recue'}`}>{verdicts.vraie ? 'S’applique' : 'Ne s’applique pas'}</span>
                    </h3>
                    {verdicts.lignes.length === 0 ? (
                      <p>Toujours</p>
                    ) : (
                      <ul className="reglage__lignes">
                        {verdicts.lignes.map((ligne) => (
                          <li key={ligne.texte} className={ligne.vraie ? 'vraie' : ''}>
                            <Icone nom={ligne.vraie ? 'coche' : 'fermer'} taille={14} /> {ligne.texte}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                )
              })}
            </div>
          )
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
            <Icone nom="anomalie" taille={14} /> {statut.message}
          </>
        )}
        {statut.etat === 'repos' && 'Chaque modification est enregistrée dans le brouillon.'}
      </footer>
    </aside>
  )
}
