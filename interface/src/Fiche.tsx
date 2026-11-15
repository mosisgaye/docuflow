import { useState } from 'react'
import * as api from './api'
import type { FactureDetail } from './api'
import { LIBELLE_ETAT, euros, heure, jour, jourEtHeure, nombre, raconter, siret } from './format'

interface Props {
  facture: FactureDetail
  occupe: boolean
  surValidation: () => void
  surRejet: (motif: string) => void
  surExport: () => void
}

interface LigneEcriture {
  compte: string
  compte_auxiliaire: string
  libelle: string
  debit: string
  credit: string
}

const NOMS_COMPTES: Record<string, string> = { '445660': 'TVA déductible', '401000': 'Fournisseur' }

/** L'écriture comptable envoyée, telle qu'enregistrée au journal. */
function Ecriture({ facture }: { facture: FactureDetail }) {
  const envoi = [...facture.evenements].reverse().find((evenement) => evenement.type === 'EXPORT')
  if (!envoi) return null
  const lignes = envoi.detail.ecriture as LigneEcriture[]
  return (
    <section className="ecriture">
      <h3>Écriture envoyée à la comptabilité</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Compte</th>
            <th scope="col">Débit</th>
            <th scope="col">Crédit</th>
          </tr>
        </thead>
        <tbody>
          {lignes.map((ligne) => (
            <tr key={ligne.compte}>
              <td>
                <strong>{ligne.compte}</strong> {NOMS_COMPTES[ligne.compte] ?? 'Charge'}
                {ligne.compte_auxiliaire && <small> ({ligne.compte_auxiliaire})</small>}
              </td>
              <td>{Number(ligne.debit) ? euros(ligne.debit) : ''}</td>
              <td>{Number(ligne.credit) ? euros(ligne.credit) : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <a className="bouton" href={api.adresseExport(facture.id)} download>
        Télécharger le fichier comptable (CSV)
      </a>
    </section>
  )
}

/** Ce qu'Odoo, le logiciel du client, sait de cette facture : le fournisseur, puis la facture créée. */
function Odoo({ facture }: { facture: FactureDetail }) {
  const fournisseur = [...facture.evenements].reverse().find((evenement) => evenement.type === 'FOURNISSEUR_ODOO')
  const envoi = [...facture.evenements].reverse().find((evenement) => evenement.type === 'EXPORT')?.detail.logiciel as
    | { logiciel?: string; adresse?: string; total_odoo?: string; ecart_total?: string | null }
    | undefined
  if (!fournisseur && envoi?.logiciel !== 'odoo') return null
  return (
    <p className="odoo">
      {fournisseur?.detail.trouve ? (
        <>
          Fournisseur reconnu dans Odoo :{' '}
          <a href={String(fournisseur.detail.adresse)} target="_blank" rel="noreferrer">
            {String(fournisseur.detail.nom)}
          </a>
        </>
      ) : fournisseur ? (
        'Fournisseur absent d’Odoo'
      ) : null}
      {envoi?.logiciel === 'odoo' && envoi.adresse && (
        <>
          {' · '}
          <a href={envoi.adresse} target="_blank" rel="noreferrer">
            Voir la facture dans Odoo
          </a>{' '}
          ({euros(envoi.total_odoo ?? null)}
          {envoi.ecart_total ? `, écart de ${euros(envoi.ecart_total)} avec la facture` : ', même total que la facture'})
        </>
      )}
    </p>
  )
}

function Tampon({ facture }: { facture: FactureDetail }) {
  const decision = [...facture.evenements].reverse().find((evenement) => evenement.type === 'VALIDATION' || evenement.type === 'REJET')
  if (!decision) return null
  // Le tampon montre la décision de la personne et son heure, pas l'état actuel :
  // une facture validée puis exportée garde « Validée » avec l'heure de la validation.
  const etat = decision.type === 'VALIDATION' ? 'validee' : 'rejetee'
  return (
    <p className={`tampon tampon--${etat}`}>
      <strong>{LIBELLE_ETAT[etat]}</strong>
      <span>
        par {decision.auteur}, le {jourEtHeure(decision.cree_le)}
      </span>
    </p>
  )
}

export function Fiche({ facture, occupe, surValidation, surRejet, surExport }: Props) {
  const [rejetOuvert, setRejetOuvert] = useState(false)
  const [motif, setMotif] = useState('')
  const donnees = facture.donnees
  const fautifs = new Set(facture.anomalies.map((anomalie) => anomalie.champ))
  const marque = (champ: string) => (fautifs.has(champ) ? 'fautif' : undefined)
  const bloquantes = facture.anomalies.filter((anomalie) => anomalie.gravite === 'bloquante')
  const decidable = facture.etat === 'a_valider' || facture.etat === 'en_anomalie'

  return (
    <article className="fiche" aria-label="Données de la facture">
      <header className="fiche__entete">
        <p className={`etat etat--${facture.etat}`}>{LIBELLE_ETAT[facture.etat]}</p>
        <h2>{donnees?.fournisseur_nom ?? facture.nom_fichier}</h2>
        {facture.evenements.some((evenement) => evenement.type === 'EXTRACTION' && evenement.detail.source === 'factur-x') && (
          <p className="facturx">Facture électronique Factur-X : données lues directement dans le fichier, sans IA</p>
        )}
        {facture.evenements[0]?.detail.source === 'mail' && (
          <p className="origine">
            Reçue par mail de <strong>{String(facture.evenements[0].detail.expediteur)}</strong>
            {facture.evenements[0].detail.objet ? <>, objet « {String(facture.evenements[0].detail.objet)} »</> : null}
          </p>
        )}
        <Odoo facture={facture} />
        <Tampon facture={facture} />
      </header>

      {facture.anomalies.length > 0 && (
        <ul className="anomalies">
          {facture.anomalies.map((anomalie) => (
            <li key={anomalie.code + anomalie.message} className={`anomalies__${anomalie.gravite}`}>
              {anomalie.message}
            </li>
          ))}
        </ul>
      )}

      {facture.etat === 'echec' && (
        <p className="anomalies anomalies__bloquante anomalies--seule">
          {String(facture.evenements.at(-1)?.detail.raison ?? 'La facture n’a pas pu être lue.')} Déposez de nouveau le fichier pour réessayer.
        </p>
      )}

      {donnees && (
        <>
          <dl className="champs">
            <div className={marque('numero_facture')}>
              <dt>Numéro</dt>
              <dd>{donnees.numero_facture ?? 'Absent'}</dd>
            </div>
            <div className={marque('date_facture')}>
              <dt>Date de facture</dt>
              <dd>{jour(donnees.date_facture)}</dd>
            </div>
            <div className={marque('date_echeance')}>
              <dt>Échéance</dt>
              <dd>{jour(donnees.date_echeance)}</dd>
            </div>
            <div className={marque('fournisseur_siret')}>
              <dt>SIRET</dt>
              <dd>{siret(donnees.fournisseur_siret)}</dd>
            </div>
            <div className={marque('fournisseur_tva')}>
              <dt>N° de TVA</dt>
              <dd>{donnees.fournisseur_tva ?? 'Absent'}</dd>
            </div>
            <div>
              <dt>Client</dt>
              <dd>{donnees.client_nom ?? 'Absent'}</dd>
            </div>
          </dl>

          <table className={`lignes ${marque('lignes') ?? ''}`}>
            <thead>
              <tr>
                <th scope="col">Désignation</th>
                <th scope="col">Qté</th>
                <th scope="col">Prix HT</th>
                <th scope="col">Montant HT</th>
              </tr>
            </thead>
            <tbody>
              {donnees.lignes.map((ligne, rang) => (
                <tr key={rang}>
                  <td>{ligne.designation}</td>
                  <td>{nombre(ligne.quantite)}</td>
                  <td>{euros(ligne.prix_unitaire_ht)}</td>
                  <td>{euros(ligne.montant_ht)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className={marque('total_ht')}>
                <th scope="row" colSpan={3}>
                  Total HT
                </th>
                <td>{euros(donnees.total_ht)}</td>
              </tr>
              <tr className={marque('total_tva')}>
                <th scope="row" colSpan={3}>
                  TVA {donnees.taux_tva === null ? '' : `${nombre(donnees.taux_tva)} %`}
                </th>
                <td>{euros(donnees.total_tva)}</td>
              </tr>
              <tr className={`lignes__ttc ${marque('total_ttc') ?? ''}`}>
                <th scope="row" colSpan={3}>
                  Total TTC
                </th>
                <td>{euros(donnees.total_ttc)}</td>
              </tr>
            </tfoot>
          </table>
        </>
      )}

      {decidable && (
        <div className="decision">
          {rejetOuvert ? (
            <form
              onSubmit={(evenement) => {
                evenement.preventDefault()
                if (motif.trim()) surRejet(motif.trim())
              }}
            >
              <label htmlFor="motif">Motif du rejet</label>
              <textarea id="motif" value={motif} onChange={(evenement) => setMotif(evenement.target.value)} rows={2} maxLength={500} autoFocus required />
              <div className="decision__boutons">
                <button type="button" className="bouton" onClick={() => setRejetOuvert(false)}>
                  Annuler
                </button>
                <button type="submit" className="bouton bouton--rejet" disabled={occupe || !motif.trim()}>
                  Rejeter la facture
                </button>
              </div>
            </form>
          ) : (
            <>
              {bloquantes.length > 0 && (
                <p className="decision__note">
                  {bloquantes.length > 1 ? 'Des anomalies bloquantes empêchent' : 'Une anomalie bloquante empêche'} la validation.
                </p>
              )}
              <div className="decision__boutons">
                <button className="bouton" onClick={() => setRejetOuvert(true)} disabled={occupe}>
                  Rejeter
                </button>
                <button className="bouton bouton--plein" onClick={surValidation} disabled={occupe || facture.etat !== 'a_valider'}>
                  Valider la facture
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {facture.etat === 'validee' && (
        <div className="decision">
          <p className="decision__note">Facture validée. Il reste à l’envoyer au logiciel de comptabilité.</p>
          <div className="decision__boutons">
            <button className="bouton bouton--plein" onClick={surExport} disabled={occupe}>
              Envoyer à la comptabilité
            </button>
          </div>
        </div>
      )}

      <Ecriture facture={facture} />

      <section className="journal">
        <h3>Journal</h3>
        <ol>
          {facture.evenements.map((evenement) => (
            <li key={evenement.rang}>
              <time dateTime={evenement.cree_le}>{heure(evenement.cree_le)}</time>
              <span>{raconter(evenement)}</span>
            </li>
          ))}
        </ol>
      </section>
    </article>
  )
}
