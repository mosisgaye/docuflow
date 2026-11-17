import { useCallback, useContext, useEffect, useState } from 'react'
import * as api from './api'
import type { Compte, ListeComptes, Niveau, Role } from './api'
import { CompteConnecte, usePeut } from './droits'
import { initiales, jourEtHeure, teinte } from './format'
import { Icone } from './Icones'

const AIDE_ROLES: Record<Exclude<Role, 'operateur'>, string> = {
  administrateur: 'Tout, plus l’équipe, la réception, les connecteurs et la publication du circuit.',
  membre: 'Dépose et traite les factures, approuve à son niveau, prépare le circuit.',
  approbateur: 'Voit seulement les factures qu’il doit approuver, et les approuve.',
  lecture: 'Voit tout, ne change rien : expert-comptable, auditeur.',
}

const SANS_NIVEAU: Role[] = ['lecture', 'operateur']

/** Réglages › Équipe quand les comptes sont en service : qui a accès, avec quel rôle et quels niveaux d'approbation. */
export function Comptes() {
  const peut = usePeut()
  const moi = useContext(CompteConnecte)
  const administrateur = peut('administrer')
  const [liste, setListe] = useState<ListeComptes | null>(null)
  const [message, setMessage] = useState<{ texte: string; erreur?: boolean } | null>(null)
  const [enCours, setEnCours] = useState<string | null>(null)
  const [nom, setNom] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('membre')
  const [niveaux, setNiveaux] = useState<Niveau[]>([])

  const recharger = useCallback(async () => setListe(await api.comptes()), [])
  useEffect(() => {
    // La liste montre l'adresse de chacun : le moteur la réserve aux administrateurs.
    if (!administrateur) return
    recharger().catch((erreur: Error) => setMessage({ texte: erreur.message, erreur: true }))
  }, [recharger, administrateur])

  const agir = async (cle: string, action: () => Promise<string>) => {
    setEnCours(cle)
    setMessage(null)
    try {
      const texte = await action()
      await recharger()
      setMessage({ texte })
    } catch (erreur) {
      setMessage({ texte: (erreur as Error).message, erreur: true })
    } finally {
      setEnCours(null)
    }
  }

  const basculer = (liste: Niveau[], niveau: Niveau) => (liste.includes(niveau) ? liste.filter((n) => n !== niveau) : [...liste, niveau])

  if (!administrateur) {
    return (
      <p className="note">
        La liste de l’équipe est réservée aux administrateurs. Vous êtes connecté en tant que {moi?.libelle_role.toLowerCase() ?? 'membre'}
        {moi && moi.niveaux.length > 0 ? `, et vous approuvez en tant que ${moi.niveaux.map((niveau) => niveau.replace('_', ' ')).join(', ')}` : ''}.
      </p>
    )
  }

  if (!liste) return <p className="note">{message?.texte ?? 'Chargement de l’équipe…'}</p>

  const actifs = liste.comptes.filter((compte) => compte.actif)
  const inactifs = liste.comptes.filter((compte) => !compte.actif)

  const ligne = (compte: Compte) => {
    const modifiable = administrateur && compte.role !== 'operateur'
    const occupe = enCours === compte.id
    return (
      <li key={compte.id} className={`comptes__ligne${compte.actif ? '' : ' comptes__ligne--inactif'}`}>
        <span className={`avatar avatar--grand teinte-${teinte(compte.nom)}`} aria-hidden="true">
          {initiales(compte.nom)}
        </span>
        <span className="reglages__personne">
          <strong>
            {compte.nom}
            {moi?.id === compte.id && <span className="comptes__vous">vous</span>}
          </strong>
          <small>
            {compte.email} · {compte.derniere_connexion ? `connecté le ${jourEtHeure(compte.derniere_connexion)}` : 'jamais connecté'}
          </small>
        </span>

        {modifiable && compte.actif ? (
          <select
            className="champ comptes__role"
            value={compte.role}
            disabled={occupe}
            aria-label={`Rôle de ${compte.nom}`}
            onChange={(evenement) => {
              const nouveau = evenement.target.value as Role
              agir(compte.id, async () => {
                await api.modifierCompte(compte.id, { role: nouveau, ...(SANS_NIVEAU.includes(nouveau) ? { niveaux: [] } : {}) })
                return `${compte.nom} est maintenant ${liste.roles[nouveau as keyof typeof liste.roles].toLowerCase()}. Sa session est fermée : il se reconnectera avec ce rôle.`
              })
            }}
          >
            {Object.entries(liste.roles).map(([cle, libelle]) => (
              <option key={cle} value={cle}>
                {libelle}
              </option>
            ))}
          </select>
        ) : (
          <span className={`etiquette-role etiquette-role--${compte.role}`}>{compte.libelle_role}</span>
        )}

        <span className="comptes__niveaux" role="group" aria-label={`Niveaux d’approbation de ${compte.nom}`}>
          {SANS_NIVEAU.includes(compte.role) ? (
            <span className="comptes__sans">N’approuve pas</span>
          ) : (
            (Object.keys(liste.niveaux) as Niveau[]).map((niveau) => {
              const actif = compte.niveaux.includes(niveau)
              return modifiable && compte.actif ? (
                <button
                  key={niveau}
                  className="pastille-niveau"
                  aria-pressed={actif}
                  disabled={occupe}
                  onClick={() =>
                    agir(compte.id, async () => {
                      await api.modifierCompte(compte.id, { niveaux: basculer(compte.niveaux, niveau) })
                      return actif ? `${compte.nom} n’approuve plus en tant que ${liste.niveaux[niveau].toLowerCase()}.` : `${compte.nom} approuve désormais en tant que ${liste.niveaux[niveau].toLowerCase()}.`
                    })
                  }
                >
                  {actif && <Icone nom="coche" taille={12} />} {liste.niveaux[niveau]}
                </button>
              ) : (
                actif && (
                  <span key={niveau} className="pastille-niveau" aria-pressed>
                    {liste.niveaux[niveau]}
                  </span>
                )
              )
            })
          )}
        </span>

        {administrateur && (
          <span className="comptes__actions">
            {compte.actif && (
              <button
                className="bouton bouton--fantome bouton--petit"
                disabled={occupe}
                onClick={() =>
                  agir(compte.id, async () => {
                    await api.deconnecterCompte(compte.id)
                    return `${compte.nom} est déconnecté de tous ses appareils.`
                  })
                }
                title="Fermer toutes ses sessions : il devra se reconnecter"
              >
                Déconnecter
              </button>
            )}
            <button
              className={`bouton bouton--petit ${compte.actif ? 'bouton--fantome comptes__desactiver' : 'bouton--fantome'}`}
              disabled={occupe}
              onClick={() =>
                agir(compte.id, async () => {
                  await api.modifierCompte(compte.id, { actif: !compte.actif })
                  return compte.actif ? `${compte.nom} n’a plus accès à Verifac. Son historique reste au journal.` : `${compte.nom} a de nouveau accès à Verifac.`
                })
              }
            >
              {compte.actif ? 'Désactiver' : 'Réactiver'}
            </button>
          </span>
        )}
      </li>
    )
  }

  return (
    <div className="reglages">
      {message && (
        <p className={`connecteurs__message${message.erreur ? ' connecteurs__message--erreur' : ''}`} role={message.erreur ? 'alert' : 'status'}>
          {message.texte}
        </p>
      )}

      {administrateur && (
        <form
          className="bloc reglages__ajout"
          onSubmit={(evenement) => {
            evenement.preventDefault()
            agir('nouveau', async () => {
              const cree = await api.creerCompte(nom.trim(), email.trim(), role, SANS_NIVEAU.includes(role) ? [] : niveaux)
              setNom('')
              setEmail('')
              setNiveaux([])
              return `${cree.nom} peut maintenant se connecter avec ${cree.email} : il recevra un lien et un code.`
            })
          }}
        >
          <h2>Ajouter une personne</h2>
          <div className="reglages__champs">
            <label>
              Nom
              <input className="champ" value={nom} onChange={(e) => setNom(e.target.value)} placeholder="Claire Fabre" required maxLength={100} />
            </label>
            <label>
              Adresse mail
              <input className="champ" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="claire@votre-entreprise.fr" required />
            </label>
            <label>
              Rôle
              <select className="champ" value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {Object.entries(liste.roles).map(([cle, libelle]) => (
                  <option key={cle} value={cle}>
                    {libelle}
                  </option>
                ))}
              </select>
            </label>
            <button className="bouton bouton--plein" disabled={!nom.trim() || !email.trim() || enCours === 'nouveau'}>
              <Icone nom="plus" /> Ajouter
            </button>
          </div>
          <p className="comptes__aide">{AIDE_ROLES[role as keyof typeof AIDE_ROLES]}</p>
          {!SANS_NIVEAU.includes(role) && (
            <div className="comptes__niveaux" role="group" aria-label="Niveaux d’approbation">
              <span className="comptes__sans">Approuve en tant que</span>
              {(Object.keys(liste.niveaux) as Niveau[]).map((niveau) => (
                <button type="button" key={niveau} className="pastille-niveau" aria-pressed={niveaux.includes(niveau)} onClick={() => setNiveaux(basculer(niveaux, niveau))}>
                  {niveaux.includes(niveau) && <Icone nom="coche" taille={12} />} {liste.niveaux[niveau]}
                </button>
              ))}
            </div>
          )}
        </form>
      )}

      <section className="bloc reglages__role">
        <header>
          <h2>
            {actifs.length} {actifs.length > 1 ? 'personnes ont accès' : 'personne a accès'}
          </h2>
          <p>Le rôle dit ce que chacun peut faire ; les niveaux disent quelles factures il approuve.</p>
        </header>
        <ul>{actifs.map(ligne)}</ul>
      </section>

      {inactifs.length > 0 && (
        <section className="bloc reglages__role">
          <header>
            <h2>Sans accès</h2>
            <p>Comptes désactivés : leurs décisions passées restent au journal.</p>
          </header>
          <ul>{inactifs.map(ligne)}</ul>
        </section>
      )}
    </div>
  )
}
