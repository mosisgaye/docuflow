// Conversation avec l'assistant : la réponse arrive morceau par morceau.

export type EvenementAgent =
  | { type: 'texte'; contenu: string }
  | { type: 'outil'; id: string; etat: 'debut' | 'fin'; libelle?: string; duree_s?: number; echec?: boolean }
  | { type: 'facture'; id: string }
  | { type: 'proposition'; facture_id: string; numero: string | null; decision: 'valider' | 'rejeter'; motif: string }
  | { type: 'erreur'; message: string }
  | { type: 'fin' }

export interface MessageAgent {
  role: 'user' | 'assistant'
  content: string
}

export async function parler(
  messages: MessageAgent[],
  factureId: string | null,
  auteur: string | null,
  surEvenement: (evenement: EvenementAgent) => void,
) {
  let reponse: Response
  try {
    reponse = await fetch('/api/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, facture_id: factureId, auteur }),
    })
  } catch {
    surEvenement({ type: 'erreur', message: 'Le moteur ne répond pas. Vérifiez qu’il est démarré.' })
    return
  }
  if (!reponse.ok || !reponse.body) {
    surEvenement({ type: 'erreur', message: `L’assistant a répondu ${reponse.status}.` })
    return
  }
  const lecteur = reponse.body.getReader()
  const decodeur = new TextDecoder()
  let tampon = ''
  for (;;) {
    const { value, done } = await lecteur.read()
    if (done) break
    tampon += decodeur.decode(value, { stream: true })
    const blocs = tampon.split('\n\n')
    tampon = blocs.pop() ?? ''
    for (const bloc of blocs) {
      if (bloc.startsWith('data: ')) surEvenement(JSON.parse(bloc.slice(6)) as EvenementAgent)
    }
  }
}
