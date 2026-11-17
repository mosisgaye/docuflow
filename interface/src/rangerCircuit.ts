// « Ranger » : replace les étapes du circuit de gauche à droite, dans l'ordre où la facture les traverse,
// en limitant les croisements de liens (placement par couches de dagre).
// La ligne principale reste droite ; les branches partent d'un seul côté, celui de la sortie qui les mène
// (« Oui » est en haut de la condition, « Non » en bas), pour que les liens ne se croisent pas en sortant.
import dagre from '@dagrejs/dagre'
import type { Graphe } from './api'

export interface Taille {
  width: number
  height: number
}

const TAILLE_PAR_DEFAUT: Taille = { width: 120, height: 100 }
const GRILLE = 20 // la grille du canevas : les étapes rangées tombent dessus

const surGrille = (valeur: number) => Math.round(valeur / GRILLE) * GRILLE

export function ranger(graphe: Graphe, tailles: Map<string, Taille>): Graphe {
  const g = new dagre.graphlib.Graph({ multigraph: true })
  // align « UL » : chaque étape s'aligne sur sa voisine du haut, ce qui garde la ligne principale droite.
  g.setGraph({ rankdir: 'LR', align: 'UL', ranksep: 100, nodesep: 60, edgesep: 20, marginx: 0, marginy: 0 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const etape of graphe.noeuds) g.setNode(etape.id, { ...(tailles.get(etape.id) ?? TAILLE_PAR_DEFAUT) })
  for (const lien of graphe.liens) {
    // Le « Non » pèse moins : la branche la plus longue reste droite, l'autre part sur le côté.
    g.setEdge(lien.de, lien.vers, { weight: lien.sortie === 'non' ? 1 : 2 }, `${lien.de}:${lien.sortie ?? 'suite'}`)
  }

  dagre.layout(g)

  // dagre donne le centre de chaque étape.
  const centres = new Map(graphe.noeuds.flatMap((etape) => (g.node(etape.id) ? [[etape.id, g.node(etape.id)] as const] : [])))

  // Les branches sont placées sous la ligne principale. Si elles partent surtout du « Oui » (en haut),
  // on retourne le schéma pour qu'elles montent : un lien sort alors du côté où il va.
  let ouiQuiDescend = 0
  let nonQuiDescend = 0
  for (const lien of graphe.liens) {
    const de = centres.get(lien.de)
    const vers = centres.get(lien.vers)
    if (!de || !vers || vers.y <= de.y) continue
    if (lien.sortie === 'oui') ouiQuiDescend++
    if (lien.sortie === 'non') nonQuiDescend++
  }
  const retourner = ouiQuiDescend > nonQuiDescend
  // Les étapes n'ont pas toutes la même hauteur (le nom passe sur 1 à 3 lignes) : on les aligne par le haut,
  // là où sont la tuile et les poignées, sinon les liens d'une même ligne feraient de petites marches.
  const hauteur = Math.max(...[...centres.values()].map((place) => place.height))

  return {
    ...graphe,
    noeuds: graphe.noeuds.map((etape) => {
      const place = centres.get(etape.id)
      if (!place) return etape
      const y = retourner ? -place.y : place.y
      // Le canevas attend le coin haut gauche.
      return { ...etape, x: surGrille(place.x - place.width / 2), y: surGrille(y - hauteur / 2) }
    }),
  }
}
