import type { FactureResume } from './api'
import { Circuit } from './Circuit'
import { Executions, Versions } from './Versions'

export type OngletWorkflow = 'circuit' | 'versions' | 'executions'

export interface ProprietesWorkflow {
  onglet: OngletWorkflow
  auteur: string
  factures: FactureResume[]
  surSansAuteur: () => void
  surInformation: (message: string) => void
  surFacture: (id: string) => void
}

export function Workflow({ onglet, auteur, factures, surSansAuteur, surInformation, surFacture }: ProprietesWorkflow) {
  if (onglet === 'versions') return <Versions />
  if (onglet === 'executions') return <Executions surFacture={surFacture} />
  return <Circuit auteur={auteur} factures={factures} surSansAuteur={surSansAuteur} surInformation={surInformation} />
}
