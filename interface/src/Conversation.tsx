import { useEffect, useRef, useState } from 'react'
import { duree } from './format'

export interface Etape {
  id: string
  libelle: string
  fini: boolean
  duree?: number
  echec?: boolean
}

export interface Proposition {
  factureId: string
  numero: string | null
  decision: 'valider' | 'rejeter'
  motif: string
  statut: 'attente' | 'faite' | 'ignoree'
}

export interface Tour {
  id: number
  role: 'user' | 'assistant'
  texte: string
  envoye?: string // ce qui est réellement transmis à l'assistant, si différent du texte affiché
  fichiers?: string[]
  etapes: Etape[]
  propositions: Proposition[]
  enCours: boolean
  erreur?: string
}

interface Props {
  tours: Tour[]
  occupe: boolean
  surEnvoi: (texte: string) => void
  surFichiers: (fichiers: File[]) => void
  surProposition: (tourId: number, rang: number, accepter: boolean) => void
  surOuverture: (factureId: string) => void
}

const SUGGESTIONS = [
  'Quelles factures posent problème, et pourquoi ?',
  'Qu’est-ce qui attend ma validation ?',
  'Rédige un courriel au fournisseur de la facture FA-2026-0431 pour demander une facture corrigée.',
]

function Etapes({ etapes }: { etapes: Etape[] }) {
  if (etapes.length === 0) return null
  return (
    <ol className="etapes">
      {etapes.map((etape) => (
        <li key={etape.id} className={etape.fini ? (etape.echec ? 'etapes__echec' : 'etapes__faite') : 'etapes__encours'}>
          <span className="etapes__puce" aria-hidden="true" />
          <span>{etape.libelle}</span>
          {etape.fini && etape.duree !== undefined && <span className="etapes__duree">{duree(etape.duree)}</span>}
        </li>
      ))}
    </ol>
  )
}

export function Conversation({ tours, occupe, surEnvoi, surFichiers, surProposition, surOuverture }: Props) {
  const [saisie, setSaisie] = useState('')
  const fin = useRef<HTMLDivElement>(null)
  const champFichier = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fin.current?.scrollIntoView({ block: 'end' })
  }, [tours])

  function envoyer() {
    const texte = saisie.trim()
    if (!texte || occupe) return
    setSaisie('')
    surEnvoi(texte)
  }

  return (
    <main className="conversation">
      <div className="conversation__fil">
        {tours.length === 0 ? (
          <div className="accueil">
            <h1>Que voulez-vous traiter ?</h1>
            <p>
              Déposez une facture PDF : l’assistant la lit, vérifie les calculs et le fournisseur, puis vous dit quoi en faire. Vous pouvez aussi lui poser une
              question.
            </p>
            <ul>
              {SUGGESTIONS.map((suggestion) => (
                <li key={suggestion}>
                  <button onClick={() => surEnvoi(suggestion)}>{suggestion}</button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          tours.map((tour) =>
            tour.role === 'user' ? (
              <div key={tour.id} className="tour tour--vous">
                {tour.fichiers?.map((nom) => (
                  <span key={nom} className="piece">
                    {nom}
                  </span>
                ))}
                {tour.texte && <p>{tour.texte}</p>}
              </div>
            ) : (
              <div key={tour.id} className="tour tour--assistant">
                <Etapes etapes={tour.etapes} />
                {tour.texte && <p className="tour__texte">{tour.texte}</p>}
                {tour.enCours && !tour.texte && tour.etapes.every((etape) => etape.fini) && <p className="tour__attente">L’assistant réfléchit…</p>}
                {tour.erreur && <p className="tour__erreur">{tour.erreur}</p>}
                {tour.propositions.map((proposition, rang) => (
                  <div key={rang} className={`proposition proposition--${proposition.decision}`}>
                    <p className="proposition__titre">
                      {proposition.decision === 'valider' ? 'Valider' : 'Rejeter'} la facture n° {proposition.numero}
                    </p>
                    <p>{proposition.motif}</p>
                    {proposition.statut === 'attente' ? (
                      <div className="proposition__boutons">
                        <button className="bouton" onClick={() => surOuverture(proposition.factureId)}>
                          Voir la facture
                        </button>
                        <button className="bouton" onClick={() => surProposition(tour.id, rang, false)}>
                          Ignorer
                        </button>
                        <button
                          className={`bouton ${proposition.decision === 'valider' ? 'bouton--plein' : 'bouton--rejet'}`}
                          onClick={() => surProposition(tour.id, rang, true)}
                        >
                          {proposition.decision === 'valider' ? 'Confirmer la validation' : 'Confirmer le rejet'}
                        </button>
                      </div>
                    ) : (
                      <p className="proposition__suite">{proposition.statut === 'faite' ? 'Décision enregistrée.' : 'Proposition ignorée.'}</p>
                    )}
                  </div>
                ))}
              </div>
            ),
          )
        )}
        <div ref={fin} />
      </div>

      <form
        className="saisie"
        onSubmit={(evenement) => {
          evenement.preventDefault()
          envoyer()
        }}
      >
        <textarea
          value={saisie}
          onChange={(evenement) => setSaisie(evenement.target.value)}
          onKeyDown={(evenement) => {
            if (evenement.key === 'Enter' && !evenement.shiftKey) {
              evenement.preventDefault()
              envoyer()
            }
          }}
          rows={2}
          placeholder="Posez une question, ou déposez une facture PDF…"
          aria-label="Votre demande"
        />
        <div className="saisie__barre">
          <button type="button" className="bouton" onClick={() => champFichier.current?.click()} disabled={occupe}>
            Joindre une facture
          </button>
          <button type="submit" className="bouton bouton--plein" disabled={occupe || !saisie.trim()}>
            Envoyer
          </button>
        </div>
        <input
          ref={champFichier}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          onChange={(evenement) => {
            surFichiers([...(evenement.target.files ?? [])])
            evenement.target.value = ''
          }}
        />
      </form>
    </main>
  )
}
