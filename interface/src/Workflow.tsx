import type { FactureResume } from './api'
import { Circuit } from './Circuit'

export type OngletWorkflow = 'circuit' | 'versions' | 'executions'

const TITRES: Record<OngletWorkflow, { titre: string; texte: string }> = {
  circuit: { titre: 'Circuit de validation des factures', texte: 'Qui approuve, quand, et ce qui bloque une facture avant le paiement.' },
  versions: { titre: 'Versions publiées', texte: 'Chaque publication crée une version. Les factures en cours gardent la leur.' },
  executions: { titre: 'Exécutions', texte: 'Le chemin réellement suivi par les dernières factures.' },
}

export interface ProprietesWorkflow {
  onglet: OngletWorkflow
  auteur: string
  factures: FactureResume[]
  surSansAuteur: () => void
  surInformation: (message: string) => void
  surFacture: (id: string) => void
}

export function Workflow({ onglet, auteur, factures, surSansAuteur, surInformation }: ProprietesWorkflow) {
  if (onglet === 'circuit') return <Circuit auteur={auteur} factures={factures} surSansAuteur={surSansAuteur} surInformation={surInformation} />
  const { titre, texte } = TITRES[onglet]
  return (
    <div className="page">
      <header className="page__titre">
        <div>
          <h1>{titre}</h1>
          <p>{texte}</p>
        </div>
      </header>
    </div>
  )
}
