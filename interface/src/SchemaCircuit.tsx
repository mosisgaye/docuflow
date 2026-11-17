// Le canevas du circuit, comme n8n : on ajoute des étapes, on les déplace, on les relie à la souris.
// Début et Odoo sont fixes. Une Condition a deux sorties (Oui, Non) ; les autres étapes une seule.
import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  Controls,
  type Connection,
  type Edge,
  type EdgeChange,
  Handle,
  MarkerType,
  type Node,
  type NodeChange,
  type NodeProps,
  Position,
  ReactFlow,
  applyNodeChanges,
} from '@xyflow/react'
import type { Catalogue, Graphe, LienGraphe, NoeudGraphe, ResultatTest, TypeEtape } from './api'
import { Icone, type NomIcone } from './Icones'

export const ICONE_ETAPE: Record<TypeEtape, NomIcone> = {
  debut: 'reception',
  condition: 'embranchement',
  approbation: 'utilisateur',
  blocage: 'refus',
  fin: 'sortie',
}

const LIBELLE_TYPE: Record<TypeEtape, string> = {
  debut: 'Réception, lecture, contrôles',
  condition: 'Condition',
  approbation: 'Approbation',
  blocage: 'Blocage',
  fin: 'Fin du circuit',
}

interface DonneesEtape extends Record<string, unknown> {
  etape: NoeudGraphe
  nom: string
  detail: string
  surChemin: boolean | null // null : pas de test en cours
  sortieTest: 'oui' | 'non' | null
}

export function nomEtape(etape: NoeudGraphe, catalogue: Catalogue) {
  if (etape.nom?.trim()) return etape.nom.trim()
  if (etape.type === 'approbation') return catalogue.niveaux.find((n) => n.code === etape.niveau)?.libelle ?? 'Approbation'
  return { debut: 'Début', fin: 'Enregistrer dans Odoo', condition: 'Condition', blocage: 'Blocage' }[etape.type as 'debut']
}

function Etape({ data, selected }: NodeProps<Node<DonneesEtape>>) {
  const { etape, nom, detail, surChemin, sortieTest } = data
  const classes = [
    'etape',
    `etape--${etape.type}`,
    selected && 'etape--choisie',
    surChemin === true && 'etape--chemin',
    surChemin === false && 'etape--hors',
  ]
  return (
    <div className={classes.filter(Boolean).join(' ')}>
      {etape.type !== 'debut' && <Handle type="target" position={Position.Left} id="entree" className="poignee" />}
      <div className="etape__tuile">
        <Icone nom={ICONE_ETAPE[etape.type]} taille={22} />
        {(etape.type === 'debut' || etape.type === 'fin') && (
          <span className="etape__cadenas" title="Étape fixe : protège le paiement">
            <Icone nom="cadenas" taille={10} />
          </span>
        )}
        {surChemin === true && (
          <span className="etape__passe" aria-label="Sur le chemin de la facture testée">
            <Icone nom="coche" taille={10} />
          </span>
        )}
      </div>
      <div className="etape__nom">{nom}</div>
      <div className="etape__detail">{detail}</div>
      {etape.type === 'condition' ? (
        <>
          <Handle type="source" position={Position.Right} id="oui" className={`poignee poignee--oui${sortieTest === 'oui' ? ' poignee--prise' : ''}`} style={{ top: '28%' }} />
          <span className="etape__sortie etape__sortie--oui">Oui</span>
          <Handle type="source" position={Position.Right} id="non" className={`poignee poignee--non${sortieTest === 'non' ? ' poignee--prise' : ''}`} style={{ top: '62%' }} />
          <span className="etape__sortie etape__sortie--non">Non</span>
        </>
      ) : (
        etape.type !== 'fin' && etape.type !== 'blocage' && <Handle type="source" position={Position.Right} id="suite" className="poignee" />
      )}
    </div>
  )
}

const TYPES = { etape: Etape }

function detailEtape(etape: NoeudGraphe) {
  if (etape.type === 'condition') {
    const lignes = etape.si?.lignes?.length ?? 0
    return etape.si?.toujours ? 'Toujours' : `${lignes} critère${lignes > 1 ? 's' : ''}`
  }
  return LIBELLE_TYPE[etape.type]
}

const idLien = (lien: LienGraphe) => `${lien.de}:${lien.sortie ?? 'suite'}`

export function SchemaCircuit({
  graphe,
  catalogue,
  test,
  choisie,
  surGraphe,
  surChoix,
}: {
  graphe: Graphe
  catalogue: Catalogue
  test: ResultatTest | null
  choisie: string | null
  surGraphe: (graphe: Graphe) => void
  surChoix: (id: string | null) => void
}) {
  const parcourues = useMemo(() => (test ? new Map(test.chemin.map((etape) => [etape.id, etape.sortie])) : null), [test])

  const calcules = useMemo<Node<DonneesEtape>[]>(
    () =>
      graphe.noeuds.map((etape) => ({
        id: etape.id,
        type: 'etape',
        position: { x: etape.x, y: etape.y },
        selected: etape.id === choisie,
        deletable: etape.type !== 'debut' && etape.type !== 'fin',
        data: {
          etape,
          nom: nomEtape(etape, catalogue),
          detail: detailEtape(etape),
          surChemin: parcourues ? parcourues.has(etape.id) : null,
          sortieTest: parcourues?.get(etape.id) ?? null,
        },
      })),
    [graphe, catalogue, parcourues, choisie],
  )
  // React Flow mesure chaque étape avant de l'afficher : on garde ces mesures quand le graphe change.
  const [noeuds, setNoeuds] = useState<Node<DonneesEtape>[]>(calcules)
  useEffect(() => {
    setNoeuds((actuels) => calcules.map((noeud) => ({ ...noeud, measured: actuels.find((a) => a.id === noeud.id)?.measured })))
  }, [calcules])

  const liens: Edge[] = graphe.liens.map((lien) => {
    const pris = parcourues ? parcourues.has(lien.de) && parcourues.has(lien.vers) && (parcourues.get(lien.de) ?? null) === (lien.sortie ?? null) : false
    return {
      id: idLien(lien),
      source: lien.de,
      target: lien.vers,
      sourceHandle: lien.sortie ?? 'suite',
      targetHandle: 'entree',
      className: `lien${lien.sortie ? ` lien--${lien.sortie}` : ''}${pris ? ' lien--chemin' : ''}`,
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    }
  })

  const relier = (connexion: Connection) => {
    const sortie = connexion.sourceHandle === 'oui' || connexion.sourceHandle === 'non' ? connexion.sourceHandle : null
    // Une sortie ne mène qu'à une étape : relier de nouveau remplace l'ancien lien.
    const autres = graphe.liens.filter((lien) => !(lien.de === connexion.source && (lien.sortie ?? null) === sortie))
    surGraphe({ ...graphe, liens: [...autres, { de: connexion.source, vers: connexion.target, sortie }] })
  }

  const changerNoeuds = (changements: NodeChange<Node<DonneesEtape>>[]) => {
    setNoeuds((actuels) => applyNodeChanges(changements, actuels))
    const retires = new Set(changements.flatMap((c) => (c.type === 'remove' ? [c.id] : [])))
    const deplaces = new Map(changements.flatMap((c) => (c.type === 'position' && c.position && c.dragging === false ? [[c.id, c.position] as const] : [])))
    if (retires.size || deplaces.size) {
      surGraphe({
        noeuds: graphe.noeuds
          .filter((etape) => !retires.has(etape.id))
          .map((etape) => {
            const position = deplaces.get(etape.id)
            return position ? { ...etape, x: Math.round(position.x), y: Math.round(position.y) } : etape
          }),
        liens: graphe.liens.filter((lien) => !retires.has(lien.de) && !retires.has(lien.vers)),
      })
      if (choisie && retires.has(choisie)) surChoix(null)
    }
    const choix = changements.find((c) => c.type === 'select' && c.selected)
    if (choix && choix.type === 'select') surChoix(choix.id)
  }

  const changerLiens = (changements: EdgeChange[]) => {
    const retires = new Set(changements.flatMap((c) => (c.type === 'remove' ? [c.id] : [])))
    if (retires.size) surGraphe({ ...graphe, liens: graphe.liens.filter((lien) => !retires.has(idLien(lien))) })
  }

  return (
    <div className="schema" aria-label="Canevas du circuit">
      <ReactFlow
        nodes={noeuds}
        edges={liens}
        nodeTypes={TYPES}
        onNodesChange={changerNoeuds}
        onEdgesChange={changerLiens}
        onConnect={relier}
        onPaneClick={() => surChoix(null)}
        isValidConnection={(connexion) => connexion.source !== connexion.target && connexion.target !== 'debut'}
        deleteKeyCode={['Backspace', 'Delete']}
        fitView
        fitViewOptions={{ padding: 0.15, minZoom: 0.6, maxZoom: 1.1 }}
        minZoom={0.3}
        maxZoom={1.6}
        snapToGrid
        snapGrid={[20, 20]}
        attributionPosition="bottom-left"
      >
        <Background gap={20} size={1.2} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  )
}
