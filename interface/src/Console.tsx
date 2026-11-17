import { useCallback, useEffect, useState } from 'react'
import * as api from './api'
import type { Etat, EtatConsole } from './api'
import { LIBELLE_ETAT, ORDRE_ETATS, duree, ilYA, jourEtHeure } from './format'
import { Icone } from './Icones'

/** « il y a 3 min », « à l’instant », ou « le 12 nov. » au-delà d'un jour. */
const quand = (iso: string) => {
  const texte = ilYA(iso)
  return texte.startsWith('il y a') || texte.startsWith('à l’') ? texte : `le ${texte}`
}

const ENTIER = new Intl.NumberFormat('fr-FR')
const EUROS = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' })

/** La Console de l'opérateur Verifac : l'état technique de cette installation, mesuré en base. */
export function Console({ surFacture }: { surFacture: (id: string) => void }) {
  const [etat, setEtat] = useState<EtatConsole | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [nom, setNom] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState<{ texte: string; erreur?: boolean } | null>(null)
  const [occupe, setOccupe] = useState(false)

  const recharger = useCallback(async () => {
    try {
      setEtat(await api.etatConsole())
      setErreur(null)
    } catch (probleme) {
      setErreur((probleme as Error).message)
    }
  }, [])

  useEffect(() => {
    recharger()
    const minuterie = window.setInterval(recharger, 30_000)
    return () => window.clearInterval(minuterie)
  }, [recharger])

  if (!etat) return <div className="page"><p className="note">{erreur ?? 'Chargement de la console…'}</p></div>

  const { sante, version, usage, ia, incidents } = etat
  const attenteLongue = (sante.plus_ancienne_attente_s ?? 0) > 600
  const semaine = usage.jours.slice(-7)

  return (
    <div className="page console">
      <header className="page__titre">
        <div>
          <h1>Console</h1>
          <p>L’état technique de cette installation, mesuré en base. Actualisé toutes les 30 secondes.</p>
        </div>
        <button className="bouton bouton--fantome" onClick={recharger}>
          Actualiser
        </button>
      </header>

      {message && (
        <p className={`connecteurs__message${message.erreur ? ' connecteurs__message--erreur' : ''}`} role={message.erreur ? 'alert' : 'status'}>
          {message.texte}
        </p>
      )}
      {erreur && (
        <p className="connecteurs__message connecteurs__message--erreur" role="alert">
          {erreur}
        </p>
      )}

      <div className="console__grille">
        <section className="bloc console__carte">
          <h2>
            <span className={`console__voyant console__voyant--${attenteLongue || sante.lectures_abandonnees > 0 ? 'alerte' : 'ok'}`} aria-hidden="true" /> Santé
          </h2>
          <dl>
            <dt>Base de données</dt>
            <dd>Répond</dd>
            <dt>File de lecture</dt>
            <dd>
              {sante.file_en_attente === 0 ? 'Vide' : `${sante.file_en_attente} en attente`}
              {sante.plus_ancienne_attente_s !== null && `, la plus ancienne depuis ${duree(sante.plus_ancienne_attente_s)}`}
            </dd>
            <dt>Travailleur</dt>
            <dd>{sante.derniere_tache_traitee ? `Dernière lecture ${quand(sante.derniere_tache_traitee)}` : 'Aucune lecture traitée'}</dd>
            <dt>Lectures abandonnées</dt>
            <dd>{sante.lectures_abandonnees}</dd>
          </dl>
        </section>

        <section className="bloc console__carte">
          <h2>Version</h2>
          <dl>
            <dt>Code en service</dt>
            <dd>{version.code ? <code>{version.code}</code> : 'Non renseignée (VERIFAC_VERSION)'}</dd>
            <dt>Migration de la base</dt>
            <dd>{version.migration ? <code>{version.migration}</code> : 'Inconnue'}</dd>
          </dl>
        </section>

        <section className="bloc console__carte">
          <h2>Usage</h2>
          <dl>
            <dt>Factures sur 30 jours</dt>
            <dd>{ENTIER.format(usage.factures_30_jours)}</dd>
            <dt>Factures en tout</dt>
            <dd>{ENTIER.format(usage.factures_total)}</dd>
            <dt>Comptes actifs</dt>
            <dd>
              {usage.comptes_actifs}, dont {usage.administrateurs} administrateur{usage.administrateurs > 1 ? 's' : ''}
            </dd>
            <dt>Dernière connexion</dt>
            <dd>{usage.derniere_connexion ? jourEtHeure(usage.derniere_connexion) : 'Aucune'}</dd>
          </dl>
          <table className="console__semaine">
            <caption>Factures reçues ces 7 derniers jours</caption>
            <thead>
              <tr>
                {semaine.map((jour) => (
                  <th key={jour.jour} scope="col">
                    {new Intl.DateTimeFormat('fr-FR', { weekday: 'short', day: 'numeric' }).format(new Date(jour.jour))}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                {semaine.map((jour) => (
                  <td key={jour.jour}>{jour.factures}</td>
                ))}
              </tr>
            </tbody>
          </table>
        </section>

        <section className="bloc console__carte">
          <h2>Lecture par l’IA, 30 jours</h2>
          <dl>
            <dt>Lectures</dt>
            <dd>{ENTIER.format(ia.lectures_30_jours)}</dd>
            <dt>Modèle</dt>
            <dd>
              {Object.keys(ia.modeles).length === 0
                ? 'Aucune lecture'
                : Object.entries(ia.modeles)
                    .map(([modele, nombre]) => `${modele} (${nombre})`)
                    .join(', ')}
            </dd>
            <dt>Jetons comptés</dt>
            <dd>
              {ENTIER.format(ia.jetons_entree)} en entrée, {ENTIER.format(ia.jetons_sortie)} en sortie
            </dd>
            <dt>Coût</dt>
            <dd>{ia.cout_30_jours_eur !== null ? EUROS.format(ia.cout_30_jours_eur) : 'Prix non renseigné (VERIFAC_PRIX_ENTREE et VERIFAC_PRIX_SORTIE, en € par million de jetons)'}</dd>
          </dl>
        </section>
      </div>

      <section className="bloc console__bloc">
        <h2>Factures par état</h2>
        <ul className="console__etats">
          {ORDRE_ETATS.filter((cle) => (usage.par_etat[cle] ?? 0) > 0).map((cle: Etat) => (
            <li key={cle}>
              <span className={`puce puce--${cle}`} aria-hidden="true" />
              {LIBELLE_ETAT[cle]} <strong>{usage.par_etat[cle]}</strong>
            </li>
          ))}
        </ul>
      </section>

      <section className="bloc console__bloc">
        <h2>Incidents récents</h2>
        {incidents.length === 0 ? (
          <p className="reglages__vide">Aucune lecture abandonnée, aucun mail en échec.</p>
        ) : (
          <ul className="console__incidents">
            {incidents.map((incident, rang) => (
              <li key={`${incident.facture_id}-${rang}`}>
                <Icone nom={incident.type === 'mail' ? 'mail' : 'anomalie'} taille={14} />
                <span>
                  <strong>{incident.type === 'mail' ? 'Mail non parti' : 'Lecture abandonnée'}</strong>
                  <small>{incident.message}</small>
                </span>
                <span className="console__quand">{incident.le ? jourEtHeure(incident.le) : ''}</span>
                <button className="bouton bouton--fantome bouton--petit" onClick={() => surFacture(incident.facture_id)}>
                  Voir la facture
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {usage.administrateurs === 0 && (
        <form
          className="bloc reglages__ajout"
          onSubmit={async (evenement) => {
            evenement.preventDefault()
            setOccupe(true)
            setMessage(null)
            try {
              const cree = await api.premierAdministrateur(nom.trim(), email.trim())
              setNom('')
              setEmail('')
              setMessage({ texte: `${cree.nom} est administrateur : il peut se connecter avec ${cree.email} et gérer son équipe.` })
              await recharger()
            } catch (probleme) {
              setMessage({ texte: (probleme as Error).message, erreur: true })
            } finally {
              setOccupe(false)
            }
          }}
        >
          <h2>Aucun administrateur actif</h2>
          <p className="comptes__aide">Créez l’administrateur du client. C’est ensuite lui qui gère l’équipe : la console ne le peut plus dès qu’il existe.</p>
          <div className="reglages__champs console__champs">
            <label>
              Nom
              <input className="champ" value={nom} onChange={(e) => setNom(e.target.value)} required maxLength={100} />
            </label>
            <label>
              Adresse mail
              <input className="champ" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <button className="bouton bouton--plein" disabled={occupe || !nom.trim() || !email.trim()}>
              Créer l’administrateur
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
