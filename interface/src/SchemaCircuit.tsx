// Le schéma du circuit, dessiné à partir des règles : les étapes fixes, puis un nœud par niveau
// d'approbation, puis Odoo. Rien ne se déplace à la main ; on zoome et on déplace la vue.
import { Background, Controls, Handle, type Edge, type Node, type NodeProps, Position, ReactFlow, MarkerType } from '@xyflow/react'
import type { Catalogue, Niveau, Regle, ResultatTest } from './api'
import { Icone } from './Icones'

export type Selection = { genre: 'niveau'; niveau: Niveau } | { genre: 'blocage' } | null

type Etat = 'passe' | 'alerte' | 'arret' | 'attente' | 'hors' | null

interface DonneesNoeud extends Record<string, unknown> {
  titre: string
  sous: string
  etiquette?: string
  fixe?: boolean
  vide?: boolean
  modifie?: boolean
  choisi?: boolean
  ia?: boolean
  resultat?: { texte: string; etat: Etat }
  sur?: 'gauche' | 'droite' | 'bas' | 'haut'
}

const LARGEUR = 168
const ECART = 52
const LIGNE_HAUTE = 40
const LIGNE_BASSE = 230
const x = (colonne: number) => colonne * (LARGEUR + ECART)

function Poignees() {
  return (
    <>
      <Handle type="target" position={Position.Left} id="gauche" isConnectable={false} />
      <Handle type="source" position={Position.Right} id="droite" isConnectable={false} />
      <Handle type="source" position={Position.Bottom} id="bas" isConnectable={false} />
      <Handle type="target" position={Position.Top} id="haut" isConnectable={false} />
    </>
  )
}

function Resultat({ resultat }: { resultat?: DonneesNoeud['resultat'] }) {
  if (!resultat) return null
  return <span className={`noeud__resultat noeud__resultat--${resultat.etat}`}>{resultat.texte}</span>
}

function NoeudEtape({ data }: NodeProps<Node<DonneesNoeud>>) {
  const classes = ['noeud', data.fixe && 'noeud--fixe', data.vide && 'noeud--vide', data.choisi && 'noeud--choisi', data.resultat?.etat === 'passe' && 'noeud--passe', data.resultat?.etat === 'hors' && 'noeud--hors']
  return (
    <div className={classes.filter(Boolean).join(' ')}>
      <Poignees />
      <span className="noeud__etiquette">
        {data.etiquette}
        {data.fixe && <Icone nom="cadenas" taille={12} />}
        {data.modifie && <span className="noeud__modifie">Modifiée</span>}
      </span>
      <strong className={data.ia ? 'noeud__titre noeud__titre--ia' : 'noeud__titre'}>{data.titre}</strong>
      <span className="noeud__sous">{data.sous}</span>
      <Resultat resultat={data.resultat} />
    </div>
  )
}

function NoeudDecision({ data }: NodeProps<Node<DonneesNoeud>>) {
  return (
    <div className={`decision${data.resultat?.etat === 'passe' ? ' decision--passe' : ''}`}>
      <Poignees />
      <span className="decision__forme" aria-hidden="true" />
      <strong>{data.titre}</strong>
    </div>
  )
}

function NoeudIssue({ data }: NodeProps<Node<DonneesNoeud>>) {
  const classes = ['issue', data.fixe ? 'issue--fixe' : 'issue--regle', data.choisi && 'noeud--choisi', data.resultat && `issue--${data.resultat.etat}`, data.modifie && 'issue--modifiee']
  return (
    <div className={classes.filter(Boolean).join(' ')}>
      <Poignees />
      <span className="noeud__etiquette">
        {data.etiquette}
        {data.fixe && <Icone nom="cadenas" taille={12} />}
        {data.modifie && <span className="noeud__modifie">Modifiée</span>}
      </span>
      <strong className="noeud__titre">{data.titre}</strong>
      <span className="noeud__sous">{data.sous}</span>
      <Resultat resultat={data.resultat} />
    </div>
  )
}

const TYPES = { etape: NoeudEtape, decision: NoeudDecision, issue: NoeudIssue }

/** Les règles qui exigent un niveau. */
export const reglesDuNiveau = (regles: Regle[], niveau: Niveau) => regles.filter((regle) => regle.exige?.includes(niveau))
export const reglesDeBlocage = (regles: Regle[]) => regles.filter((regle) => regle.bloque)

const pluriel = (n: number, mot: string) => `${n} ${mot}${n > 1 ? 's' : ''}`

/** Les nœuds et les liens du schéma, calculés à partir des règles (et du résultat d'un test, s'il y en a un). */
export function schema(regles: Regle[], catalogue: Catalogue, test: ResultatTest | null, selection: Selection, modifiees: Set<string>, relancesModifiees: Set<Niveau>) {
  const passe = (texte: string): DonneesNoeud['resultat'] => (test ? { texte, etat: 'passe' } : undefined)
  const arretee = test?.controles.arretee ?? false
  const alertes = test?.controles.anomalies.filter((anomalie) => anomalie.gravite !== 'bloquante') ?? []

  const noeuds: Node<DonneesNoeud>[] = [
    { id: 'reception', type: 'etape', position: { x: x(0), y: LIGNE_HAUTE }, data: { etiquette: 'Étape fixe', fixe: true, titre: 'Réception', sous: 'Mail, dépôt ou API', resultat: passe('✓ Reçue') } },
    { id: 'lecture', type: 'etape', position: { x: x(1), y: LIGNE_HAUTE }, data: { etiquette: 'Étape fixe', fixe: true, ia: true, titre: 'Lecture IA', sous: 'PDF, scan, photo, Factur-X', resultat: passe('✓ Lue') } },
    {
      id: 'controles',
      type: 'etape',
      position: { x: x(2), y: LIGNE_HAUTE },
      data: {
        etiquette: 'Étape fixe',
        fixe: true,
        titre: 'Contrôles',
        sous: 'Calculs, doublon, SIRET, IBAN, commande',
        resultat: test
          ? arretee
            ? { texte: 'Anomalie bloquante', etat: 'arret' }
            : alertes.length
              ? { texte: `${pluriel(alertes.length, 'alerte')} : ${alertes.map((a) => a.libelle).join(', ')}`, etat: 'alerte' }
              : { texte: '✓ Conforme', etat: 'passe' }
          : undefined,
      },
    },
    { id: 'conforme', type: 'decision', position: { x: x(3) + 24, y: LIGNE_HAUTE + 4 }, data: { titre: 'Facture conforme ?', sous: '', resultat: test && !arretee ? { texte: '', etat: 'passe' } : undefined } },
    {
      id: 'arretee',
      type: 'issue',
      position: { x: x(3), y: LIGNE_BASSE },
      data: {
        etiquette: 'Étape fixe',
        fixe: true,
        titre: 'Arrêtée aux contrôles',
        sous: 'Erreur de calcul, doublon, SIRET ou IBAN invalide : à corriger ou rejeter',
        resultat: test ? (arretee ? { texte: 'La facture s’arrête ici', etat: 'arret' } : { texte: 'Non concernée', etat: 'hors' }) : undefined,
      },
    },
  ]

  const exiges = new Set(test?.niveaux.map((n) => n.niveau) ?? [])
  catalogue.niveaux.forEach((niveau, rang) => {
    const siennes = reglesDuNiveau(regles, niveau.code)
    const raison = test?.niveaux.find((n) => n.niveau === niveau.code)?.raisons.join(', ')
    noeuds.push({
      id: niveau.code,
      type: 'etape',
      position: { x: x(4 + rang), y: LIGNE_HAUTE },
      data: {
        etiquette: `Niveau ${rang + 1}`,
        titre: niveau.libelle,
        sous: siennes.length === 0 ? 'Non utilisé : cliquez pour l’activer' : siennes.length === 1 ? siennes[0].nom : pluriel(siennes.length, 'règle'),
        vide: siennes.length === 0,
        modifie: siennes.some((regle) => modifiees.has(regle.nom)) || relancesModifiees.has(niveau.code),
        choisi: selection?.genre === 'niveau' && selection.niveau === niveau.code,
        resultat: test ? (arretee || test.bloque ? { texte: 'Non atteint', etat: 'hors' } : exiges.has(niveau.code) ? { texte: `Exigé : ${raison}`, etat: 'attente' } : { texte: 'Non concerné', etat: 'hors' }) : undefined,
      },
    })
  })

  const blocages = reglesDeBlocage(regles)
  const bloqueParRegle = Boolean(test && !arretee && test.bloque)
  noeuds.push(
    {
      id: 'blocage',
      type: 'issue',
      position: { x: x(4), y: LIGNE_BASSE },
      data: {
        etiquette: 'Réglable',
        titre: 'Bloquée par règle',
        sous: blocages.length ? blocages.map((regle) => regle.nom).join(', ') : 'Aucune règle de blocage',
        choisi: selection?.genre === 'blocage',
        modifie: blocages.some((regle) => modifiees.has(regle.nom)),
        resultat: test ? (bloqueParRegle ? { texte: test.bloque!, etat: 'arret' } : { texte: 'Non concernée', etat: 'hors' }) : undefined,
      },
    },
    {
      id: 'odoo',
      type: 'etape',
      position: { x: x(4 + catalogue.niveaux.length), y: LIGNE_HAUTE },
      data: {
        etiquette: 'Étape fixe',
        fixe: true,
        titre: 'Enregistrer dans Odoo',
        sous: 'Facture fournisseur et PDF',
        resultat: test ? (arretee || bloqueParRegle ? { texte: 'Non atteint', etat: 'hors' } : { texte: 'Après les approbations', etat: 'attente' }) : undefined,
      },
    },
  )

  const enTest = Boolean(test)
  const surChemin = (id: string) => {
    if (!test) return false
    if (['reception', 'lecture', 'controles'].includes(id)) return true
    if (arretee) return id === 'arretee'
    if (id === 'conforme') return true
    if (test.bloque) return id === 'blocage'
    return exiges.has(id as Niveau) || id === 'odoo'
  }
  const lien = (source: string, cible: string, options: Partial<Edge> = {}): Edge => {
    const vert = enTest && surChemin(source) && surChemin(cible)
    return {
      id: `${source}-${cible}`,
      source,
      target: cible,
      sourceHandle: 'droite',
      targetHandle: 'gauche',
      type: 'smoothstep',
      className: vert ? 'lien lien--chemin' : 'lien',
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      ...options,
    }
  }
  const chaine = ['reception', 'lecture', 'controles', 'conforme', ...catalogue.niveaux.map((n) => n.code), 'odoo']
  const liens: Edge[] = chaine.slice(1).map((cible, rang) => lien(chaine[rang], cible, chaine[rang] === 'conforme' ? { label: 'Oui', labelClassName: 'lien__etiquette lien__etiquette--oui' } as Partial<Edge> : {}))
  liens.push(
    lien('conforme', 'arretee', { sourceHandle: 'bas', targetHandle: 'haut', label: 'Non', className: `lien lien--non${enTest && arretee ? ' lien--chemin-arret' : ''}` }),
    lien('conforme', 'blocage', { sourceHandle: 'bas', targetHandle: 'haut', label: 'Si une règle bloque', className: `lien lien--non${bloqueParRegle ? ' lien--chemin-arret' : ''}` }),
  )
  return { noeuds, liens }
}

export function SchemaCircuit({
  regles,
  catalogue,
  test,
  selection,
  modifiees,
  relancesModifiees,
  surSelection,
}: {
  regles: Regle[]
  catalogue: Catalogue
  test: ResultatTest | null
  selection: Selection
  modifiees: Set<string>
  relancesModifiees: Set<Niveau>
  surSelection: (selection: Selection) => void
}) {
  const { noeuds, liens } = schema(regles, catalogue, test, selection, modifiees, relancesModifiees)
  const niveaux = new Set<string>(catalogue.niveaux.map((niveau) => niveau.code))
  return (
    <div className="schema" aria-label="Schéma du circuit">
      <ReactFlow
        nodes={noeuds}
        edges={liens}
        nodeTypes={TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        edgesFocusable={false}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.4}
        maxZoom={1.6}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, noeud) => {
          if (niveaux.has(noeud.id)) surSelection({ genre: 'niveau', niveau: noeud.id as Niveau })
          else if (noeud.id === 'blocage') surSelection({ genre: 'blocage' })
        }}
      >
        <Background gap={18} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
      <ul className="schema__legende">
        <li>
          <Icone nom="cadenas" taille={12} /> Étape fixe : protège le paiement
        </li>
        <li>Cliquez sur un niveau ou sur « Bloquée par règle » pour le régler</li>
      </ul>
    </div>
  )
}
