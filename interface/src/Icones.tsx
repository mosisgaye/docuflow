// Icônes au trait (Lucide) : 16 px, trait fin de 1,65 px, couleur du texte.
import {
  Activity,
  ArrowRight,
  Ban,
  Bot,
  BrushCleaning,
  Building2,
  Check,
  ChevronDown,
  LogOut,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Clock,
  Code,
  Copy,
  ExternalLink,
  FileText,
  History,
  House,
  Inbox,
  KeyRound,
  Lock,
  FlaskConical,
  Layers,
  LayoutGrid,
  ListFilter,
  Mail,
  Maximize,
  MessageSquarePlus,
  Moon,
  PanelLeft,
  Paperclip,
  Plug,
  Plus,
  Receipt,
  Search,
  Send,
  SendHorizontal,
  Settings,
  Users,
  ShieldCheck,
  Sparkles,
  Split,
  Sun,
  Trash2,
  TriangleAlert,
  Upload,
  User,
  Webhook,
  Workflow,
  X,
  Zap,
  ZoomIn,
  ZoomOut,
  type LucideIcon,
} from 'lucide-react'

const ICONES = {
  accueil: House,
  document: FileText,
  validation: CircleCheck,
  assistant: Sparkles,
  integration: Plug,
  recherche: Search,
  horloge: Clock,
  bouclier: ShieldCheck,
  alerte: TriangleAlert,
  eclair: Zap,
  reception: Inbox,
  utilisateur: User,
  coche: Check,
  fleche: ArrowRight,
  soleil: Sun,
  lune: Moon,
  plus: Plus,
  fermer: X,
  precedent: ChevronLeft,
  suivant: ChevronRight,
  deplier: ChevronDown,
  deposer: Upload,
  filtre: ListFilter,
  cle: KeyRound,
  crochet: Webhook,
  externe: ExternalLink,
  panneau: PanelLeft,
  journal: History,
  grouper: Layers,
  grille: LayoutGrid,
  conversation: MessageSquarePlus,
  joindre: Paperclip,
  envoyer: SendHorizontal,
  copier: Copy,
  mail: Mail,
  entreprise: Building2,
  facture: Receipt,
  code: Code,
  robot: Bot,
  anomalie: CircleAlert,
  refus: Ban,
  sortie: Send,
  deconnexion: LogOut,
  console: Activity,
  reglages: Settings,
  equipe: Users,
  workflow: Workflow,
  cadenas: Lock,
  test: FlaskConical,
  embranchement: Split,
  corbeille: Trash2,
  toutVoir: Maximize,
  zoomPlus: ZoomIn,
  zoomMoins: ZoomOut,
  ranger: BrushCleaning,
} satisfies Record<string, LucideIcon>

export type NomIcone = keyof typeof ICONES

export function Icone({ nom, taille = 16 }: { nom: NomIcone; taille?: number }) {
  const Trace = ICONES[nom]
  // La taille suit la base de l'interface (rem) : les icônes grandissent avec le texte.
  return (
    <Trace
      size={taille}
      strokeWidth={1.65}
      absoluteStrokeWidth
      aria-hidden="true"
      className="icone"
      style={{ width: `${taille / 16}rem`, height: `${taille / 16}rem` }}
    />
  )
}

/** Le symbole Verifac (document au coin plié et coche), le même que sur le site (site/lib/logo.ts).
 *  Blanc par défaut : il se pose sur le carré vert de la marque. */
export function LogoVerifac({ taille = 16 }: { taille?: number }) {
  return (
    <svg
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth={4.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ width: `${taille / 16}rem`, height: `${taille / 16}rem` }}
    >
      <path d="M12 5h16l11 11v22a5 5 0 0 1-5 5H12a5 5 0 0 1-5-5V10a5 5 0 0 1 5-5z" />
      <path d="M28 5v8a3 3 0 0 0 3 3h8" />
      <path d="M14.5 28.5l5.5 5.5 11-11.5" strokeWidth={5.4} />
    </svg>
  )
}
