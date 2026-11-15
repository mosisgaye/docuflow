import { useCallback, useEffect, useState } from 'react'
import * as api from './api'
import type { AbonnementSortant, CleApi } from './api'
import { jourEtHeure } from './format'

const LIBELLE_LIVRAISON = { en_attente: 'Nouvel essai prévu', livree: 'Livré', abandonnee: 'Abandonné' } as const

/** Un secret montré une seule fois, avec un bouton pour le copier. */
function SecretUneFois({ titre, valeur, surFermer }: { titre: string; valeur: string; surFermer: () => void }) {
  const [copie, setCopie] = useState(false)
  return (
    <div className="secret" role="status">
      <p className="secret__titre">{titre}</p>
      <code className="secret__valeur">{valeur}</code>
      <p className="secret__note">Copiez-le maintenant : DocuFlow n’en garde qu’une empreinte et ne pourra plus vous le montrer.</p>
      <div className="secret__actions">
        <button className="bouton bouton--plein" onClick={() => navigator.clipboard.writeText(valeur).then(() => setCopie(true))}>
          {copie ? 'Copié' : 'Copier'}
        </button>
        <button className="bouton" onClick={surFermer}>
          C’est noté
        </button>
      </div>
    </div>
  )
}

interface Props {
  auteur: string
  surSansAuteur: () => void
}

export function AccesDeveloppeurs({ auteur, surSansAuteur }: Props) {
  const [cles, setCles] = useState<CleApi[] | null>(null)
  const [droits, setDroits] = useState<Record<string, string>>({})
  const [abonnements, setAbonnements] = useState<AbonnementSortant[] | null>(null)
  const [evenements, setEvenements] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [secret, setSecret] = useState<{ titre: string; valeur: string } | null>(null)
  const [nomCle, setNomCle] = useState('')
  const [droitsCle, setDroitsCle] = useState<string[]>(['factures:lire'])
  const [url, setUrl] = useState('')
  const [choisis, setChoisis] = useState<string[]>(['facture.validee'])

  const recharger = useCallback(async () => {
    const [c, a] = await Promise.all([api.clesApi(), api.abonnements()])
    setCles(c.cles)
    setDroits(c.droits)
    setAbonnements(a.abonnements)
    setEvenements(a.evenements)
  }, [])

  useEffect(() => {
    recharger().catch((erreur: Error) => setMessage(erreur.message))
  }, [recharger])

  const agir = async (action: () => Promise<unknown>, succes: string | null) => {
    setMessage(null)
    try {
      await action()
      await recharger()
      if (succes) setMessage(succes)
    } catch (erreur) {
      setMessage((erreur as Error).message)
    }
  }

  const signe = (): boolean => {
    if (auteur.trim()) return true
    setMessage('Indiquez votre nom en haut à droite : la création est inscrite à votre nom.')
    surSansAuteur()
    return false
  }

  const basculer = (liste: string[], valeur: string) => (liste.includes(valeur) ? liste.filter((v) => v !== valeur) : [...liste, valeur])

  return (
    <div className="acces">
      {message && (
        <p className="connecteurs__message" role="status">
          {message}
        </p>
      )}
      {secret && <SecretUneFois titre={secret.titre} valeur={secret.valeur} surFermer={() => setSecret(null)} />}

      <section className="bloc acces__bloc">
        <h2>Clés d’API</h2>
        <p className="acces__explication">
          Un autre logiciel (ERP, outil d’automatisation, script) peut déposer des factures et lire leur état avec une clé. Chaque clé a des droits précis
          et se révoque en un clic. Documentation : <a className="lien" href="/api/docs#/API%20publique" target="_blank" rel="noreferrer">/v1 en détail</a>.
        </p>
        <form
          className="acces__formulaire"
          onSubmit={(evenement) => {
            evenement.preventDefault()
            if (!signe()) return
            agir(async () => {
              const creee = await api.creerCle(nomCle.trim(), droitsCle, auteur.trim())
              setSecret({ titre: `Clé « ${creee.nom} »`, valeur: creee.cle })
              setNomCle('')
            }, null)
          }}
        >
          <label className="acces__champ">
            À quoi sert-elle ?
            <input value={nomCle} onChange={(e) => setNomCle(e.target.value)} placeholder="Logiciel de paie, Make, script de la compta…" required maxLength={100} />
          </label>
          <fieldset className="acces__choix">
            <legend>Droits</legend>
            {Object.entries(droits).map(([droit, libelle]) => (
              <label key={droit}>
                <input type="checkbox" checked={droitsCle.includes(droit)} onChange={() => setDroitsCle(basculer(droitsCle, droit))} /> {libelle}
              </label>
            ))}
          </fieldset>
          <button className="bouton bouton--plein" disabled={!nomCle.trim() || droitsCle.length === 0}>
            Créer la clé
          </button>
        </form>
        {cles === null ? (
          <p className="note">Chargement…</p>
        ) : cles.length === 0 ? (
          <p className="note">Aucune clé pour l’instant.</p>
        ) : (
          <ul className="acces__liste">
            {cles.map((cle) => (
              <li key={cle.id} className={cle.revoquee_le ? 'acces__ligne acces__ligne--eteinte' : 'acces__ligne'}>
                <div>
                  <strong>{cle.nom}</strong> <code>{cle.debut}</code>
                  <p className="acces__detail">
                    {cle.droits.map((d) => droits[d] ?? d).join(' ; ')}. Créée par {cle.creee_par} le {jourEtHeure(cle.creee_le)}.{' '}
                    {cle.revoquee_le ? `Révoquée le ${jourEtHeure(cle.revoquee_le)}.` : cle.utilisee_le ? `Dernier usage le ${jourEtHeure(cle.utilisee_le)}.` : 'Jamais utilisée.'}
                  </p>
                </div>
                {!cle.revoquee_le && (
                  <button className="bouton bouton--danger" onClick={() => agir(() => api.revoquerCle(cle.id), `La clé « ${cle.nom} » est révoquée : elle ne marche plus.`)}>
                    Révoquer
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="bloc acces__bloc">
        <h2>Prévenir un autre logiciel</h2>
        <p className="acces__explication">
          DocuFlow envoie un message signé à l’adresse de votre choix quand une facture change d’état. En cas d’échec, il réessaie : 30 s, 2 min, 10 min,
          1 h, 6 h.
        </p>
        <form
          className="acces__formulaire"
          onSubmit={(evenement) => {
            evenement.preventDefault()
            if (!signe()) return
            agir(async () => {
              const cree = await api.creerAbonnement(url.trim(), choisis, auteur.trim())
              setSecret({ titre: `Secret de signature pour ${cree.url}`, valeur: cree.secret })
              setUrl('')
            }, null)
          }}
        >
          <label className="acces__champ">
            Adresse à prévenir
            <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://erp.exemple.fr/docuflow" required />
          </label>
          <fieldset className="acces__choix">
            <legend>Quand ?</legend>
            {Object.entries(evenements).map(([nom, libelle]) => (
              <label key={nom}>
                <input type="checkbox" checked={choisis.includes(nom)} onChange={() => setChoisis(basculer(choisis, nom))} /> {libelle}
              </label>
            ))}
          </fieldset>
          <button className="bouton bouton--plein" disabled={!url.trim() || choisis.length === 0}>
            Ajouter l’adresse
          </button>
        </form>
        {abonnements === null ? (
          <p className="note">Chargement…</p>
        ) : abonnements.length === 0 ? (
          <p className="note">Aucune adresse à prévenir pour l’instant.</p>
        ) : (
          <ul className="acces__liste">
            {abonnements.map((abonnement) => (
              <li key={abonnement.id} className="acces__ligne acces__ligne--abonnement">
                <div>
                  <strong>{abonnement.url}</strong>
                  <p className="acces__detail">
                    {abonnement.evenements.join(', ')}. Ajoutée par {abonnement.cree_par} le {jourEtHeure(abonnement.cree_le)}.
                  </p>
                  {abonnement.livraisons.length > 0 && (
                    <ul className="acces__livraisons">
                      {abonnement.livraisons.map((livraison) => (
                        <li key={livraison.id} data-etat={livraison.etat}>
                          <span>{jourEtHeure(livraison.cree_le)}</span> <span>{livraison.evenement}</span>{' '}
                          <span>
                            {LIBELLE_LIVRAISON[livraison.etat]}
                            {livraison.reponse ? ` (${livraison.reponse}, ${livraison.tentatives} essai${livraison.tentatives > 1 ? 's' : ''})` : ''}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="acces__actions">
                  <button className="bouton" onClick={() => agir(() => api.essayerAbonnement(abonnement.id), 'Événement d’essai préparé : il part dans la seconde.')}>
                    Envoyer un essai
                  </button>
                  <button className="bouton bouton--danger" onClick={() => agir(() => api.arreterAbonnement(abonnement.id), 'Plus rien ne part vers cette adresse.')}>
                    Arrêter
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
