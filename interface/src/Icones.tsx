// Icônes au trait (Lucide) : 16 px, trait fin de 1,65 px, couleur du texte.
import {
  ArrowRight,
  Ban,
  Bot,
  Building2,
  Check,
  ChevronDown,
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
  Layers,
  LayoutGrid,
  ListFilter,
  Mail,
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
  ShieldCheck,
  Sparkles,
  Sun,
  TriangleAlert,
  Upload,
  User,
  Webhook,
  X,
  Zap,
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
