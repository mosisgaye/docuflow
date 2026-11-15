import { useEffect, useRef, useState } from 'react'
import { duree } from './format'
import { Icone } from './Icones'

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
  connecteurs: string[]  // noms des connecteurs branchés, où l'assistant peut chercher
  surConnecteurs: () => void
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

/** Ce que l'assistant a fait (outils appelés), repliable. Ouvert tant qu'il travaille. */
function Etapes({ etapes, enCours }: { etapes: Etape[]; enCours: boolean }) {
  if (etapes.length === 0) return null
  const finies = etapes.filter((etape) => etape.fini).length
  return (
    <details className="etapes" open={enCours || undefined}>
      <summary>
        <Icone nom="robot" taille={14} />
        {finies < etapes.length ? `${etapes[finies]?.libelle ?? 'En cours'}…` : `${etapes.length} vérification${etapes.length > 1 ? 's' : ''} faite${etapes.length > 1 ? 's' : ''}`}
        <Icone nom="deplier" taille={14} />
      </summary>
      <ol>
        {etapes.map((etape) => (
          <li key={etape.id} className={etape.fini ? (etape.echec ? 'etapes__echec' : 'etapes__faite') : 'etapes__encours'}>
            <span className="etapes__puce" aria-hidden="true" />
            <span>{etape.libelle}</span>
            {etape.fini && etape.duree !== undefined && <span className="etapes__duree">{duree(etape.duree)}</span>}
          </li>
        ))}
      </ol>
    </details>
  )
}

export function Conversation({ tours, occupe, connecteurs, surConnecteurs, surEnvoi, surFichiers, surProposition, surOuverture }: Props) {
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
            <span className="accueil__icone">
              <Icone nom="assistant" taille={20} />
            </span>
            <h1>Que voulez-vous traiter ?</h1>
            <p>
              Déposez une facture PDF : l’assistant la lit, vérifie les calculs et le fournisseur, puis vous dit quoi en faire. Vous pouvez aussi lui poser une
              question.
            </p>
            <ul>
              {SUGGESTIONS.map((suggestion) => (
                <li key={suggestion}>
                  <button className="question" onClick={() => surEnvoi(suggestion)}>
                    <Icone nom="conversation" /> {suggestion}
                  </button>
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
                    <Icone nom="document" taille={14} /> {nom}
                  </span>
                ))}
                {tour.texte && <p>{tour.texte}</p>}
              </div>
            ) : (
              <div key={tour.id} className="tour tour--assistant">
                <p className="tour__qui">
                  <span className="marque" aria-hidden="true">
                    <Icone nom="assistant" taille={12} />
                  </span>
                  Assistant DocuFlow
                </p>
                <Etapes etapes={tour.etapes} enCours={tour.enCours} />
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
                          className={`bouton ${proposition.decision === 'valider' ? 'bouton--plein' : 'bouton--danger'}`}
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

      <div className="saisie__zone">
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
          placeholder="Posez une question, ou joignez une facture (PDF ou photo)…"
          aria-label="Votre demande"
        />
        <div className="saisie__barre">
          <button type="button" className="bouton bouton--fantome" onClick={() => champFichier.current?.click()} disabled={occupe}>
            <Icone nom="joindre" /> Joindre une facture
          </button>
          <button type="submit" className="bouton bouton--plein bouton--icone" disabled={occupe || !saisie.trim()} aria-label="Envoyer">
            <Icone nom="envoyer" />
          </button>
        </div>
        <input
          ref={champFichier}
          type="file"
          accept="application/pdf,image/jpeg,image/png,image/webp"
          multiple
          hidden
          onChange={(evenement) => {
            surFichiers([...(evenement.target.files ?? [])])
            evenement.target.value = ''
          }}
        />
      </form>
      <p className="saisie__connecteurs">
        {connecteurs.length > 0 ? 'L’assistant cherche aussi dans : ' : 'Aucun connecteur branché. '}
        <button type="button" className="lien" onClick={surConnecteurs}>
          {connecteurs.length > 0 ? connecteurs.join(', ') : 'Brancher un logiciel'}
        </button>
      </p>
      </div>
    </main>
  )
}
