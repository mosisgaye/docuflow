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
      <p className="secret__note">Copiez-le maintenant : Verifac n’en garde qu’une empreinte et ne pourra plus vous le montrer.</p>
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

/** Un exemple à copier : le texte tel quel, et un bouton Copier. */
function BlocCode({ titre, code }: { titre: string; code: string }) {
  const [copie, setCopie] = useState(false)
  return (
    <figure className="acces__code">
      <figcaption>
        {titre}
        <button
          type="button"
          className="bouton bouton--fantome bouton--petit"
          onClick={() =>
            navigator.clipboard.writeText(code).then(() => {
              setCopie(true)
              window.setTimeout(() => setCopie(false), 2000)
            })
          }
        >
          {copie ? 'Copié' : 'Copier'}
        </button>
      </figcaption>
      <pre>
        <code>{code}</code>
      </pre>
    </figure>
  )
}

const VERIFIER_SIGNATURE = `import hashlib, hmac, time

def message_valide(secret: str, entetes: dict, corps: bytes) -> bool:
    horodatage = entetes["X-Verifac-Horodatage"]
    attendue = hmac.new(secret.encode(), horodatage.encode() + b"." + corps, hashlib.sha256).hexdigest()
    recent = abs(time.time() - int(horodatage)) < 300  # refuser un message de plus de 5 minutes
    return recent and hmac.compare_digest(attendue, entetes["X-Verifac-Signature"])`

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
  // Derrière Vercel comme en local, le moteur répond sous /api de l'adresse de l'interface.
  const base = `${window.location.origin}/api/v1`
  const actives = (cles ?? []).filter((cle) => !cle.revoquee_le)
  const revoquees = (cles ?? []).filter((cle) => cle.revoquee_le)
  const tousCoches = Object.keys(evenements).length > 0 && Object.keys(evenements).every((nom) => choisis.includes(nom))

  const ligneCle = (cle: CleApi) => (
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
  )

  return (
    <div className="acces">
      {message && (
        <p className="connecteurs__message" role="status">
          {message}
        </p>
      )}
      {secret && <SecretUneFois titre={secret.titre} valeur={secret.valeur} surFermer={() => setSecret(null)} />}

      <section className="bloc acces__bloc">
        <h2>Claude</h2>
        <p className="acces__explication">
          Posez vos questions sur les factures directement dans Claude : « Qu’est-ce qui attend mon approbation ? », « Pourquoi la facture F26-1240 est-elle
          en anomalie ? ». Claude lit seulement, avec les droits de votre compte : rien n’est approuvé ni modifié depuis Claude.
        </p>
        <div className="acces__demarrer">
          <h3>Ajouter Verifac à Claude</h3>
          <ol className="acces__etapes">
            <li>Dans Claude : Paramètres › Connecteurs › Ajouter un connecteur personnalisé.</li>
            <li>
              Nom : <code>Verifac</code>. Adresse : <code>{`${window.location.origin}/api/mcp`}</code>
            </li>
            <li>Cliquez sur Se connecter : Verifac vous demande votre adresse mail, puis votre accord.</li>
          </ol>
          <BlocCode titre="Adresse du connecteur" code={`${window.location.origin}/api/mcp`} />
        </div>
      </section>

      <section className="bloc acces__bloc">
        <h2>Clés d’API</h2>
        <p className="acces__explication">
          Un autre logiciel (ERP, outil d’automatisation, script) peut déposer des factures et lire leur état avec une clé. Chaque clé a des droits précis
          et se révoque en un clic.
        </p>
        <div className="acces__demarrer">
          <h3>Démarrer</h3>
          <dl>
            <dt>Adresse</dt>
            <dd>
              <code>{base}</code>
            </dd>
            <dt>Clé</dt>
            <dd>
              chaque appel porte l’en-tête <code>Authorization: Bearer dfk_…</code>
            </dd>
            <dt>Documentation</dt>
            <dd>
              <a className="lien" href="/api/v1/docs" target="_blank" rel="noreferrer">
                toutes les adresses, à essayer en direct
              </a>
            </dd>
          </dl>
          <BlocCode titre="Lister les factures à valider" code={`curl -H "Authorization: Bearer $VERIFAC_CLE" \\\n  "${base}/factures?etat=a_valider"`} />
          <BlocCode titre="Déposer une facture" code={`curl -H "Authorization: Bearer $VERIFAC_CLE" \\\n  -F "fichier=@facture.pdf" \\\n  "${base}/factures"`} />
        </div>
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
        ) : (
          <>
            {actives.length === 0 ? <p className="note">Aucune clé active.</p> : <ul className="acces__liste">{actives.map(ligneCle)}</ul>}
            {revoquees.length > 0 && (
              <details className="acces__revoquees">
                <summary>Clés révoquées ({revoquees.length})</summary>
                <ul className="acces__liste">{revoquees.map(ligneCle)}</ul>
              </details>
            )}
          </>
        )}
      </section>

      <section className="bloc acces__bloc">
        <h2>Prévenir un autre logiciel</h2>
        <p className="acces__explication">
          Verifac envoie un message signé à l’adresse de votre choix quand une facture change d’état. En cas d’échec, il réessaie : 30 s, 2 min, 10 min,
          1 h, 6 h.
        </p>
        <details className="acces__signature">
          <summary>Vérifier qu’un message vient bien de Verifac</summary>
          <p className="acces__explication">
            Chaque message porte <code>X-Verifac-Horodatage</code> et <code>X-Verifac-Signature</code> : le HMAC-SHA256 de « horodatage.corps » avec le
            secret donné à la création de l’adresse. <code>X-Verifac-Livraison</code> reste le même à chaque nouvel essai : ignorez un identifiant déjà
            traité.
          </p>
          <BlocCode titre="En Python" code={VERIFIER_SIGNATURE} />
        </details>
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
            <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://erp.exemple.fr/verifac" required />
          </label>
          <fieldset className="acces__choix">
            <legend>Quand ?</legend>
            <button type="button" className="bouton bouton--fantome bouton--petit acces__tout" onClick={() => setChoisis(tousCoches ? [] : Object.keys(evenements))}>
              {tousCoches ? 'Tout décocher' : 'Tout cocher'}
            </button>
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
