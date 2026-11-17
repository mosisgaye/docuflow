import { type ReactNode, useState } from 'react'
import * as api from './api'
import type { Evenement, FactureDetail } from './api'
import { LIBELLE_ETAT, LIBELLE_NIVEAU, euros, heure, jour, jourEtHeure, nombre, raconter, siret } from './format'
import { Icone } from './Icones'
import { ICONE_ETAPE } from './SchemaCircuit'

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

const dernier = (facture: FactureDetail, ...types: string[]): Evenement | undefined =>
  [...facture.evenements].reverse().find((evenement) => types.includes(evenement.type))

/** L'écriture comptable envoyée, telle qu'enregistrée au journal. */
function Ecriture({ facture }: { facture: FactureDetail }) {
  const envoi = dernier(facture, 'EXPORT')
  const lignes = envoi?.detail.ecriture as LigneEcriture[] | undefined
  if (!lignes) return null
  return (
    <section className="fiche__section ecriture">
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
        <Icone nom="deposer" /> Fichier comptable (CSV)
      </a>
    </section>
  )
}

const VERDICTS_IBAN: Record<string, { texte: string; ton: 'vert' | 'rouge' | 'ambre' }> = {
  conforme: { texte: 'IBAN conforme à celui connu dans Odoo.', ton: 'vert' },
  different: { texte: 'IBAN différent de celui connu dans Odoo : appelez le fournisseur au numéro habituel avant de payer.', ton: 'rouge' },
  inconnu: { texte: 'Aucun IBAN connu dans Odoo pour ce fournisseur : à vérifier avant de payer.', ton: 'ambre' },
}

/** Ce que disent les sources : Factur-X, scan, mail, Odoo. Une ligne par signal. */
function Signaux({ facture }: { facture: FactureDetail }) {
  const extraction = dernier(facture, 'EXTRACTION')
  const reception = facture.evenements[0]
  const fournisseur = dernier(facture, 'FOURNISSEUR_ODOO')
  const commande = dernier(facture, 'COMMANDE_ODOO')
  const envoi = dernier(facture, 'EXPORT')?.detail.logiciel as { logiciel?: string; adresse?: string; total_odoo?: string; ecart_total?: string | null } | undefined
  const iban = fournisseur?.detail.trouve ? VERDICTS_IBAN[String(fournisseur.detail.iban)] : undefined
  const signaux: { cle: string; ton: string; icone: Parameters<typeof Icone>[0]['nom']; contenu: ReactNode }[] = []

  if (extraction?.detail.source === 'factur-x')
    signaux.push({ cle: 'fx', ton: 'vert', icone: 'facture', contenu: 'Facture électronique Factur-X : données lues directement dans le fichier, sans IA.' })
  if (extraction?.detail.source === 'ia-image')
    signaux.push({ cle: 'scan', ton: 'ia', icone: 'assistant', contenu: 'Facture scannée ou photographiée, lue sur l’image par l’IA. Comparez les montants et l’IBAN avec le document.' })
  if (reception?.detail.source === 'mail')
    signaux.push({
      cle: 'mail',
      ton: 'gris',
      icone: 'mail',
      contenu: (
        <>
          Reçue par mail de <strong>{String(reception.detail.expediteur)}</strong>
          {reception.detail.objet ? <>, objet « {String(reception.detail.objet)} »</> : null}
        </>
      ),
    })
  if (reception?.detail.source === 'api')
    signaux.push({ cle: 'api', ton: 'gris', icone: 'cle', contenu: <>Déposée par l’API, clé « {String(reception.detail.cle_nom)} »</> })
  if (fournisseur)
    signaux.push(
      fournisseur.detail.trouve
        ? {
            cle: 'odoo',
            ton: 'vert',
            icone: 'entreprise',
            contenu: (
              <>
                Fournisseur reconnu dans Odoo :{' '}
                <a href={String(fournisseur.detail.adresse)} target="_blank" rel="noreferrer">
                  {String(fournisseur.detail.nom)}
                </a>
              </>
            ),
          }
        : { cle: 'odoo', ton: 'ambre', icone: 'entreprise', contenu: 'Fournisseur absent d’Odoo.' },
    )
  if (iban) signaux.push({ cle: 'iban', ton: iban.ton, icone: iban.ton === 'vert' ? 'bouclier' : 'alerte', contenu: iban.texte })
  if (commande)
    signaux.push(
      commande.detail.statut === 'sans_commande'
        ? { cle: 'po', ton: 'gris', icone: 'document', contenu: 'Aucun bon de commande correspondant dans Odoo.' }
        : {
            cle: 'po',
            ton: commande.detail.statut === 'conforme' ? 'vert' : 'ambre',
            icone: 'document',
            contenu: (
              <>
                {commande.detail.statut === 'conforme' ? 'Conforme au bon de commande ' : 'Écart avec le bon de commande '}
                <a href={String(commande.detail.adresse)} target="_blank" rel="noreferrer">
                  {String(commande.detail.commande)}
                </a>
              </>
            ),
          },
    )
  if (envoi?.logiciel === 'odoo' && envoi.adresse)
    signaux.push({
      cle: 'envoi',
      ton: 'vert',
      icone: 'externe',
      contenu: (
        <>
          <a href={envoi.adresse} target="_blank" rel="noreferrer">
            Facture créée dans Odoo
          </a>{' '}
          ({euros(envoi.total_odoo ?? null)}
          {envoi.ecart_total ? `, écart de ${euros(envoi.ecart_total)} avec la facture` : ', même total que la facture'})
        </>
      ),
    })

  if (signaux.length === 0) return null
  return (
    <section className="fiche__section">
      <h3>Provenance et vérifications</h3>
      {signaux.map((signal) => (
        <p key={signal.cle} className={`signal signal--${signal.ton}`}>
          <Icone nom={signal.icone} />
          <span>{signal.contenu}</span>
        </p>
      ))}
    </section>
  )
}

/** Qui doit approuver, dans quel ordre et pourquoi ; qui l'a déjà fait. */
function CircuitApprobation({ facture }: { facture: FactureDetail }) {
  const circuit = facture.circuit
  // Un circuit d'un seul niveau sans règles publiées n'a rien à expliquer : c'est la validation simple.
  if (!circuit || circuit.version === null) return null
  return (
    <section className="fiche__section circuit" aria-label="Circuit d'approbation">
      <h3>Circuit d’approbation</h3>
      {circuit.bloque && (
        <p className="signal signal--rouge" style={{ marginBottom: '0.625rem' }}>
          <Icone nom="refus" />
          <span>{circuit.bloque}</span>
        </p>
      )}
      {circuit.etapes && circuit.etapes.length > 0 && (
        <details className="pourquoi" open>
          <summary>Pourquoi ce circuit ?</summary>
          <ol className="pourquoi__chemin">
            {circuit.etapes.map((etape) => (
              <li key={etape.id} className={`pourquoi__etape pourquoi__etape--${etape.type}`}>
                <span className="pourquoi__tuile" aria-hidden="true">
                  <Icone nom={ICONE_ETAPE[etape.type]} taille={13} />
                </span>
                <span className="pourquoi__texte">
                  <strong>{etape.nom}</strong>
                  {etape.type === 'condition' && (
                    <span>
                      {etape.condition} :{' '}
                      <span className={`pourquoi__reponse pourquoi__reponse--${etape.sortie}`}>{etape.sortie === 'oui' ? 'Oui' : 'Non'}</span>
                    </span>
                  )}
                  {etape.type === 'blocage' && etape.message && <span>{etape.message}</span>}
                  {etape.type === 'debut' && <span>Reçue, lue et contrôlée</span>}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}
      <ol>
        {circuit.niveaux.map(({ niveau, raisons }) => {
          const faite = facture.approbations.find((approbation) => approbation.niveau === niveau)
          const etat = faite ? 'faite' : niveau === facture.niveau_attendu ? 'attendue' : 'a-venir'
          return (
            <li key={niveau} className={`circuit__niveau circuit__niveau--${etat}`}>
              <span className="circuit__marque" aria-hidden="true">
                {faite && <Icone nom="coche" taille={13} />}
              </span>
              <span className="circuit__texte">
                <strong>{LIBELLE_NIVEAU[niveau]}</strong>
                <span>
                  {faite ? `Approuvé par ${faite.personne}, le ${jourEtHeure(faite.cree_le)}` : etat === 'attendue' ? 'En attente de sa décision' : 'Après le niveau précédent'}
                </span>
                {/* Avec un circuit dessiné, « Pourquoi ce circuit ? » l'explique déjà : on ne le répète pas ici. */}
                {!circuit.etapes && <small>Pourquoi : {raisons.join(' ; ')}</small>}
              </span>
            </li>
          )
        })}
      </ol>
      <p className="circuit__regle">Circuit des factures, version {circuit.version}. Une même personne n’approuve jamais deux niveaux.</p>
    </section>
  )
}

/** La décision prise sur la facture, avec son auteur et son heure. */
export function Tampon({ facture }: { facture: FactureDetail }) {
  const decision = dernier(facture, 'VALIDATION', 'REJET')
  if (!decision) return null
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

/** Le journal complet de la facture : chaque étape, son heure et son auteur. */
export function Journal({ facture }: { facture: FactureDetail }) {
  return (
    <ol className="journal">
      {facture.evenements.map((evenement) => (
        <li key={evenement.rang}>
          <time dateTime={evenement.cree_le}>{heure(evenement.cree_le)}</time>
          <span>
            {raconter(evenement)}
            {evenement.auteur !== 'moteur' && <span className="journal__auteur"> · {evenement.auteur}</span>}
          </span>
        </li>
      ))}
    </ol>
  )
}

export function Fiche({ facture, occupe, surValidation, surRejet, surExport }: Props) {
  const [rejetOuvert, setRejetOuvert] = useState(false)
  const [motif, setMotif] = useState('')
  const donnees = facture.donnees
  const fautifs = new Set(facture.anomalies.map((anomalie) => anomalie.champ))
  const marque = (champ: string) => (fautifs.has(champ) ? 'fautif' : undefined)
  const bloquantes = facture.anomalies.filter((anomalie) => anomalie.gravite === 'bloquante')
  const decidable = facture.etat === 'a_valider' || facture.etat === 'en_approbation' || facture.etat === 'en_anomalie'
  const approuvable = (facture.etat === 'a_valider' || facture.etat === 'en_approbation') && !facture.circuit?.bloque
  const avecRegles = facture.circuit?.version != null
  const libelleDecision = avecRegles && facture.niveau_attendu ? `Approuver (${LIBELLE_NIVEAU[facture.niveau_attendu].toLowerCase()})` : 'Valider'

  return (
    <article className="fiche" aria-label="Données de la facture">
      {(facture.anomalies.length > 0 || facture.etat === 'echec') && (
        <section className="fiche__section">
          <h3>
            {facture.etat === 'echec'
              ? 'Lecture impossible'
              : `${facture.anomalies.length} anomalie${facture.anomalies.length > 1 ? 's' : ''} trouvée${facture.anomalies.length > 1 ? 's' : ''} par les contrôles`}
          </h3>
          {facture.etat === 'echec' && (
            <p className="signal signal--rouge">
              <Icone nom="anomalie" />
              <span>{String(facture.evenements.at(-1)?.detail.raison ?? 'La facture n’a pas pu être lue.')} Déposez de nouveau le fichier pour réessayer.</span>
            </p>
          )}
          {facture.anomalies.map((anomalie) => (
            <p key={anomalie.code + anomalie.message} className={`signal signal--${anomalie.gravite}`}>
              <Icone nom={anomalie.gravite === 'bloquante' ? 'refus' : 'alerte'} />
              <span>{anomalie.message}</span>
            </p>
          ))}
        </section>
      )}

      <Signaux facture={facture} />

      {donnees && (
        <>
          <section className="fiche__section">
            <h3>Données lues</h3>
            <dl className="champs">
              <div className={marque('numero_facture')}>
                <dt>Numéro</dt>
                <dd>{donnees.numero_facture ?? 'Absent'}</dd>
              </div>
              <div className={marque('total_ttc')}>
                <dt>Montant TTC</dt>
                <dd>{euros(donnees.total_ttc)}</dd>
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
              <div className={`champs__large ${marque('fournisseur_iban') ?? ''}`}>
                <dt>IBAN</dt>
                <dd>{donnees.fournisseur_iban ? donnees.fournisseur_iban.replace(/(.{4})/g, '$1 ').trim() : 'Absent'}</dd>
              </div>
              <div className="champs__large">
                <dt>Client</dt>
                <dd>{donnees.client_nom ?? 'Absent'}</dd>
              </div>
            </dl>
          </section>

          <section className="fiche__section">
            <h3>Lignes</h3>
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
          </section>
        </>
      )}

      <CircuitApprobation facture={facture} />
      <Ecriture facture={facture} />

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
              <textarea id="motif" className="champ" value={motif} onChange={(evenement) => setMotif(evenement.target.value)} rows={2} maxLength={500} autoFocus required />
              <div className="decision__boutons">
                <button type="button" className="bouton bouton--fantome" onClick={() => setRejetOuvert(false)}>
                  Annuler
                </button>
                <button type="submit" className="bouton bouton--danger" disabled={occupe || !motif.trim()}>
                  Rejeter la facture
                </button>
              </div>
            </form>
          ) : (
            <>
              {bloquantes.length > 0 && (
                <p className="decision__note">{bloquantes.length > 1 ? 'Des anomalies bloquantes empêchent' : 'Une anomalie bloquante empêche'} la validation.</p>
              )}
              <div className="decision__boutons">
                <button className="bouton bouton--danger" onClick={() => setRejetOuvert(true)} disabled={occupe}>
                  <Icone nom="refus" /> Rejeter
                </button>
                <button className="bouton bouton--plein" onClick={surValidation} disabled={occupe || !approuvable}>
                  <Icone nom="coche" /> {libelleDecision}
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
              <Icone nom="sortie" /> Envoyer à la comptabilité
            </button>
          </div>
        </div>
      )}
    </article>
  )
}
