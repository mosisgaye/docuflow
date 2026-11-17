import { createContext, useContext } from 'react'
import type { Compte, Droit } from './api'

/** Le compte connecté, partagé par toute l'application. Sans comptes (démonstration), tout est permis.
 *  Le moteur vérifie chaque droit de son côté : ici, on évite seulement d'afficher des boutons inutiles. */
export const CompteConnecte = createContext<Compte | null>(null)

export function usePeut(): (droit: Droit) => boolean {
  const compte = useContext(CompteConnecte)
  return (droit) => compte === null || compte.droits.includes(droit)
}
