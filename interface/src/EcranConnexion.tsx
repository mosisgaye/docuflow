import { useEffect, useRef, useState } from 'react'
import * as api from './api'
import { Icone } from './Icones'

type Etape = { type: 'adresse' } | { type: 'code'; email: string } | { type: 'lien'; jeton: string }

/** La connexion sans mot de passe : l'adresse, puis le lien reçu par mail ou le code à 6 chiffres.
 *  Le lien du mail ouvre cet écran avec un bouton : c'est le clic qui connecte, pas l'ouverture du lien
 *  (les messageries d'entreprise ouvrent les liens pour les analyser). */
export function EcranConnexion({ jeton, demo = false, surConnexion }: { jeton: string | null; demo?: boolean; surConnexion: (compte: api.Compte) => void }) {
  const [etape, setEtape] = useState<Etape>(jeton ? { type: 'lien', jeton } : { type: 'adresse' })
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [information, setInformation] = useState<string | null>(null)
  const [occupe, setOccupe] = useState(false)
  const champCode = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (etape.type === 'code') champCode.current?.focus()
  }, [etape])

  const agir = async (action: () => Promise<void>) => {
    setOccupe(true)
    setErreur(null)
    try {
      await action()
    } catch (probleme) {
      setErreur((probleme as Error).message)
    } finally {
      setOccupe(false)
    }
  }

  const oublierLeLien = () => {
    // Le jeton ne doit pas rester dans la barre d'adresse ni dans l'historique.
    window.history.replaceState(null, '', window.location.pathname)
  }

  return (
    <main className="acces-ecran">
      <form
        className="acces-ecran__carte"
        onSubmit={(evenement) => {
          evenement.preventDefault()
          if (etape.type === 'adresse')
            agir(async () => {
              const reponse = await api.demanderConnexion(email.trim())
              setInformation(reponse.message)
              setEtape({ type: 'code', email: email.trim() })
            })
          else if (etape.type === 'code')
            agir(async () => {
              const { compte } = await api.connexionParCode(etape.email, code)
              surConnexion(compte)
            }).then(() => setCode(''))
          else
            agir(async () => {
              try {
                const { compte } = await api.connexionParLien(etape.jeton)
                oublierLeLien()
                surConnexion(compte)
              } catch (probleme) {
                oublierLeLien()
                setEtape({ type: 'adresse' })
                throw probleme
              }
            })
        }}
      >
        <span className="marque acces-ecran__marque" aria-hidden="true">
          <Icone nom="facture" taille={20} />
        </span>
        <h1>Verifac</h1>

        {etape.type === 'adresse' && demo && (
          <div className="acces-ecran__demo">
            <p>
              Essayez Verifac sur de fausses factures : une fraude à l’IBAN, des doublons, un circuit d’approbation à trois niveaux. Rien à installer, aucune adresse à
              donner. Vos essais sont effacés chaque nuit.
            </p>
            <button
              type="button"
              className="bouton bouton--plein acces-ecran__bouton"
              disabled={occupe}
              onClick={() =>
                agir(async () => {
                  const { compte } = await api.entrerDansLaDemo()
                  surConnexion(compte)
                })
              }
            >
              Entrer dans la démo
            </button>
            <p className="acces-ecran__separation">Vous avez déjà un compte ?</p>
          </div>
        )}

        {etape.type === 'adresse' && (
          <>
            <p>Saisissez votre adresse professionnelle. Vous recevrez un lien et un code pour vous connecter, sans mot de passe.</p>
            <label className="acces-ecran__champ">
              Adresse mail
              <input
                className="champ"
                type="email"
                value={email}
                onChange={(evenement) => setEmail(evenement.target.value)}
                autoFocus
                autoComplete="email"
                required
                aria-invalid={erreur ? true : undefined}
              />
            </label>
          </>
        )}

        {etape.type === 'code' && (
          <>
            <p role="status">{information}</p>
            <label className="acces-ecran__champ">
              Code reçu par mail
              <input
                ref={champCode}
                className="champ acces-ecran__code"
                value={code}
                onChange={(evenement) => setCode(evenement.target.value.replace(/[^\d ]/g, ''))}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={7}
                placeholder="123 456"
                required
                aria-invalid={erreur ? true : undefined}
              />
            </label>
          </>
        )}

        {etape.type === 'lien' && <p>Vous avez ouvert le lien reçu par mail. Cliquez pour ouvrir votre session sur cet appareil.</p>}

        {erreur && (
          <p className="acces-ecran__erreur" role="alert">
            <Icone nom="anomalie" taille={14} /> {erreur}
          </p>
        )}

        <button
          className={`bouton ${demo && etape.type === 'adresse' ? 'bouton--fantome' : 'bouton--plein'} acces-ecran__bouton`}
          disabled={occupe || (etape.type === 'adresse' && !email.trim()) || (etape.type === 'code' && code.replace(/\s/g, '').length !== 6)}
        >
          {occupe ? 'Un instant…' : etape.type === 'adresse' ? 'Recevoir un lien de connexion' : 'Se connecter'}
        </button>

        {etape.type === 'code' && (
          <button
            type="button"
            className="bouton bouton--fantome acces-ecran__bouton"
            onClick={() => {
              setEtape({ type: 'adresse' })
              setErreur(null)
              setCode('')
            }}
          >
            Changer d’adresse ou redemander un code
          </button>
        )}
      </form>
    </main>
  )
}
