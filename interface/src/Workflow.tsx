// La page Workflow, comme n8n : pas de barre latérale, les onglets en haut au centre,
// et le canevas qui prend toute la place.
import type { FactureResume } from './api'
import { Circuit } from './Circuit'
import { Executions, Versions } from './Versions'

export type OngletWorkflow = 'circuit' | 'versions' | 'executions'

const ONGLETS: { onglet: OngletWorkflow; nom: string }[] = [
  { onglet: 'circuit', nom: 'Circuit' },
  { onglet: 'versions', nom: 'Versions' },
  { onglet: 'executions', nom: 'Exécutions' },
]

export interface ProprietesWorkflow {
  onglet: OngletWorkflow
  surOnglet: (onglet: OngletWorkflow) => void
  auteur: string
  factures: FactureResume[]
  surSansAuteur: () => void
  surInformation: (message: string) => void
  surFacture: (id: string) => void
}

function Onglets({ onglet, surOnglet }: { onglet: OngletWorkflow; surOnglet: (onglet: OngletWorkflow) => void }) {
  return (
    <nav className="onglets-workflow" aria-label="Sections du workflow">
      {ONGLETS.map((entree) => (
        <button key={entree.onglet} aria-current={onglet === entree.onglet ? 'page' : undefined} onClick={() => surOnglet(entree.onglet)}>
          {entree.nom}
        </button>
      ))}
    </nav>
  )
}

export function Workflow({ onglet, surOnglet, auteur, factures, surSansAuteur, surInformation, surFacture }: ProprietesWorkflow) {
  const onglets = <Onglets onglet={onglet} surOnglet={surOnglet} />
  if (onglet === 'circuit') return <Circuit onglets={onglets} auteur={auteur} factures={factures} surSansAuteur={surSansAuteur} surInformation={surInformation} />
  return (
    <div className="workflow-page">
      <div className="workflow-page__haut">{onglets}</div>
      {onglet === 'versions' ? <Versions /> : <Executions surFacture={surFacture} />}
    </div>
  )
}
