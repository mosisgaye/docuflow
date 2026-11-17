import { useCallback, useContext, useEffect, useState } from 'react'
import { Comptes } from './Comptes'
import { CompteConnecte } from './droits'
import * as api from './api'
import type { MailRecu, MembreEquipe, Niveau } from './api'
import { initiales, jourEtHeure, teinte } from './format'
import { Icone } from './Icones'

export type OngletReglages = 'equipe' | 'reception'

const ROLE: Record<Niveau, string> = {
  comptable: 'Approuve toutes les factures, en premier.',
  directeur_financier: 'Approuve en plus au-dessus de 1 000 €, et quand il y a un risque (IBAN, écart avec la commande).',
  gerant: 'Approuve en plus au-dessus de 5 000 €.',
}

function Equipe({ auteur, surSansAuteur }: { auteur: string; surSansAuteur: () => void }) {
  const [membres, setMembres] = useState<MembreEquipe[] | null>(null)
  const [niveaux, setNiveaux] = useState<Record<Niveau, string> | null>(null)
  const [nom, setNom] = useState('')
  const [email, setEmail] = useState('')
  const [niveau, setNiveau] = useState<Niveau>('comptable')
  const [message, setMessage] = useState<string | null>(null)

  const recharger = useCallback(async () => {
    const reponse = await api.equipe()
    setMembres(reponse.membres)
    setNiveaux(reponse.niveaux)
  }, [])

  useEffect(() => {
    recharger().catch((erreur: Error) => setMessage(erreur.message))
  }, [recharger])

  const ajouter = async () => {
    if (!auteur.trim()) {
      setMessage('Indiquez votre nom en haut à droite : l’ajout est inscrit à votre nom.')
      return surSansAuteur()
    }
    setMessage(null)
    try {
      const membre = await api.ajouterMembre(nom.trim(), email.trim(), niveau, auteur.trim())
      setNom('')
      setEmail('')
      await recharger()
      setMessage(`${membre.nom} recevra désormais les demandes d’approbation du rôle ${niveaux?.[niveau].toLowerCase()}.`)
    } catch (erreur) {
      setMessage((erreur as Error).message)
    }
  }

  const retirer = async (membre: MembreEquipe) => {
    setMessage(null)
    try {
      await api.retirerMembre(membre.id)
      await recharger()
      setMessage(`${membre.nom} ne recevra plus les demandes de ce rôle.`)
    } catch (erreur) {
      setMessage((erreur as Error).message)
    }
  }

  return (
    <div className="reglages">
      {message && (
        <p className="connecteurs__message" role="status">
          {message}
        </p>
      )}

      <form
        className="bloc reglages__ajout"
        onSubmit={(evenement) => {
          evenement.preventDefault()
          ajouter()
        }}
      >
        <h2>Ajouter une personne</h2>
        <div className="reglages__champs">
          <label>
            Nom
            <input id="membre-nom" className="champ" value={nom} onChange={(e) => setNom(e.target.value)} placeholder="Claire Fabre" required maxLength={100} />
          </label>
          <label>
            Adresse mail
            <input id="membre-email" className="champ" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="claire@votre-entreprise.fr" required />
          </label>
          <label>
            Rôle
            <select id="membre-niveau" className="champ" value={niveau} onChange={(e) => setNiveau(e.target.value as Niveau)}>
              {niveaux && Object.entries(niveaux).map(([cle, libelle]) => <option key={cle} value={cle}>{libelle}</option>)}
            </select>
          </label>
          <button className="bouton bouton--plein" disabled={!nom.trim() || !email.trim()}>
            <Icone nom="plus" /> Ajouter
          </button>
        </div>
      </form>

      {membres === null || niveaux === null ? (
        <p className="note">Chargement de l’équipe…</p>
      ) : (
        (Object.keys(niveaux) as Niveau[]).map((cle) => {
          const duRole = membres.filter((membre) => membre.niveau === cle)
          return (
            <section key={cle} className="bloc reglages__role">
              <header>
                <h2>{niveaux[cle]}</h2>
                <p>{ROLE[cle]}</p>
              </header>
              {duRole.length === 0 ? (
                <p className="reglages__vide">Personne pour l’instant : les demandes de ce rôle partent à l’adresse de secours du serveur.</p>
              ) : (
                <ul>
                  {duRole.map((membre) => (
                    <li key={membre.id}>
                      <span className={`avatar avatar--grand teinte-${teinte(membre.nom)}`} aria-hidden="true">
                        {initiales(membre.nom)}
                      </span>
                      <span className="reglages__personne">
                        <strong>{membre.nom}</strong>
                        <small>{membre.email}</small>
                      </span>
                      <button className="bouton bouton--fantome bouton--danger bouton--petit" onClick={() => retirer(membre)} aria-label={`Retirer ${membre.nom}`}>
                        Retirer
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )
        })
      )}
      <p className="note">Une même personne n’approuve jamais deux niveaux d’une même facture, même si elle a plusieurs rôles.</p>
    </div>
  )
}

function Reception() {
  const [donnees, setDonnees] = useState<{ adresse: string; active: boolean; mails: MailRecu[] } | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [copie, setCopie] = useState(false)

  const recharger = useCallback(() => {
    api.reception().then(setDonnees, (probleme: Error) => setErreur(probleme.message))
  }, [])

  useEffect(() => {
    recharger()
  }, [recharger])

  if (erreur) return <p className="connecteurs__message">{erreur}</p>
  if (!donnees) return <p className="note">Chargement…</p>

  const copier = () => {
    navigator.clipboard.writeText(donnees.adresse).then(
      () => setCopie(true),
      () => setCopie(false),
    )
  }

  return (
    <div className="reglages">
      <section className="bloc reglages__adresse">
        <h2>Votre adresse de réception</h2>
        <p>Toute facture envoyée à cette adresse, en pièce jointe (PDF ou photo), arrive toute seule dans Verifac.</p>
        <div className="reglages__copie">
          <code>{donnees.adresse}</code>
          <button className="bouton" onClick={copier}>
            <Icone nom={copie ? 'coche' : 'copier'} /> {copie ? 'Copiée' : 'Copier'}
          </button>
        </div>
        <p className={`etat ${donnees.active ? 'etat--validee' : 'etat--echec'}`}>{donnees.active ? 'Réception active' : 'Réception pas encore configurée'}</p>
      </section>

      <section className="bloc reglages__etapes">
        <h2>Faire suivre vos factures, sans rien changer pour vos fournisseurs</h2>
        <p>Vos fournisseurs continuent d’écrire à votre adresse habituelle. Une règle de transfert envoie une copie à Verifac.</p>
        <div className="reglages__deux">
          <div>
            <h3>Avec Gmail</h3>
            <ol>
              <li>Paramètres (la roue), puis « Voir tous les paramètres », puis « Transfert et POP/IMAP ».</li>
              <li>« Ajouter une adresse de transfert » : collez l’adresse ci-dessus.</li>
              <li>Gmail envoie un code de confirmation à cette adresse. Il apparaît plus bas, dans « Derniers mails reçus » : recopiez-le dans Gmail.</li>
              <li>Créez un filtre (par exemple « contient une pièce jointe » et le mot « facture »), avec l’action « Transférer à » cette adresse.</li>
            </ol>
          </div>
          <div>
            <h3>Avec Outlook</h3>
            <ol>
              <li>Paramètres, puis « Courrier », puis « Règles ».</li>
              <li>« Ajouter une nouvelle règle » : condition « contient des pièces jointes ».</li>
              <li>Action « Transférer à » : collez l’adresse ci-dessus, puis enregistrez.</li>
              <li>Si le transfert est refusé, votre administrateur Microsoft 365 doit autoriser le transfert vers l’extérieur.</li>
            </ol>
          </div>
        </div>
      </section>

      <section className="bloc reglages__mails">
        <header>
          <h2>Derniers mails reçus</h2>
          <button className="bouton bouton--fantome bouton--petit" onClick={recharger}>
            Actualiser
          </button>
        </header>
        {donnees.mails.length === 0 ? (
          <p className="reglages__vide">Aucun mail reçu pour l’instant. Envoyez-vous une facture à l’adresse ci-dessus pour essayer.</p>
        ) : (
          <ul>
            {donnees.mails.map((mail) => (
              <li key={mail.id}>
                <div className="reglages__mail">
                  <span>
                    <strong>{mail.objet || '(sans objet)'}</strong>
                    <small>
                      {mail.expediteur}, le {jourEtHeure(mail.recu_le)}
                    </small>
                  </span>
                  <span className={`etat ${mail.factures ? 'etat--validee' : 'etat--recue'}`}>
                    {mail.factures ? `${mail.factures} facture${mail.factures > 1 ? 's' : ''}` : 'Sans facture'}
                  </span>
                </div>
                {mail.texte && (
                  <details className="reglages__texte">
                    <summary>Lire le mail (code de confirmation, par exemple)</summary>
                    <p>{mail.texte}</p>
                  </details>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

export function Reglages({ onglet, auteur, surSansAuteur }: { onglet: OngletReglages; auteur: string; surSansAuteur: () => void }) {
  // Avec des comptes, l'équipe, ce sont les comptes ; sans comptes (démonstration), la liste des approbateurs par mail.
  const avecComptes = useContext(CompteConnecte) !== null
  return (
    <div className="page">
      <header className="page__titre">
        <div>
          <h1>{onglet === 'equipe' ? 'Mon équipe' : 'Réception des factures'}</h1>
          <p>
            {onglet === 'equipe'
              ? avecComptes
                ? 'Qui a accès à Verifac, et ce que chacun peut faire. Chaque personne reçoit par mail les demandes d’approbation de ses niveaux.'
                : 'Les personnes qui approuvent les factures. Chacune reçoit par mail les demandes de son rôle.'
              : 'Comment vos factures arrivent dans Verifac.'}
          </p>
        </div>
      </header>
      {onglet === 'equipe' ? avecComptes ? <Comptes /> : <Equipe auteur={auteur} surSansAuteur={surSansAuteur} /> : <Reception />}
    </div>
  )
}
