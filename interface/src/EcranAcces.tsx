import { useState } from 'react'
import * as api from './api'
import { Icone } from './Icones'

/** L'entrée de la démonstration en ligne : un code d'accès, demandé une fois par navigateur. */
export function EcranAcces({ surOuverture }: { surOuverture: () => void }) {
  const [code, setCode] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [occupe, setOccupe] = useState(false)

  return (
    <main className="acces-ecran">
      <form
        className="acces-ecran__carte"
        onSubmit={async (evenement) => {
          evenement.preventDefault()
          setOccupe(true)
          setErreur(null)
          try {
            await api.entrer(code)
            surOuverture()
          } catch (probleme) {
            setErreur((probleme as Error).message)
            setCode('')
          } finally {
            setOccupe(false)
          }
        }}
      >
        <span className="marque acces-ecran__marque" aria-hidden="true">
          <Icone nom="facture" taille={20} />
        </span>
        <h1>DocuFlow</h1>
        <p>Démonstration privée du traitement des factures fournisseurs. Entrez le code d’accès qui vous a été transmis.</p>
        <label className="acces-ecran__champ">
          Code d’accès
          <input
            className="champ"
            type="password"
            value={code}
            onChange={(evenement) => setCode(evenement.target.value)}
            autoFocus
            autoComplete="current-password"
            required
            aria-invalid={erreur ? true : undefined}
          />
        </label>
        {erreur && (
          <p className="acces-ecran__erreur" role="alert">
            <Icone nom="anomalie" taille={14} /> {erreur}
          </p>
        )}
        <button className="bouton bouton--plein acces-ecran__bouton" disabled={occupe || !code.trim()}>
          {occupe ? 'Vérification…' : 'Entrer'}
        </button>
      </form>
    </main>
  )
}
