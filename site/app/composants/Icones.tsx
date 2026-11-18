import type { IconeGuide } from "@/contenu/guides";
import { SYMBOLE } from "@/lib/logo";

type Props = { taille?: number };

/** Le symbole Verifac (document plié et coche), en blanc par défaut : il se pose sur le carré vert de la marque. */
export function Logo({ taille = 16 }: Props) {
  return (
    <svg width={taille} height={taille} viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="4.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={SYMBOLE.document} />
      <path d={SYMBOLE.pli} />
      <path d={SYMBOLE.coche} strokeWidth="5.4" />
    </svg>
  );
}

export function Coche({ taille = 18 }: Props) {
  return (
    <svg width={taille} height={taille} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}

export function Jouer({ taille = 24 }: Props) {
  return (
    <svg width={taille} height={taille} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5.5v13l11-6.5z" />
    </svg>
  );
}

const TRACES: Record<IconeGuide, React.ReactNode> = {
  reception: <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />,
  approbation: <path d="M5 12.5l4.5 4.5L19 7" />,
  anomalie: (
    <>
      <path d="M12 8v5M12 16.5v.5" />
      <path d="M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" />
    </>
  ),
  circuit: (
    <>
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="18" cy="18" r="2.5" />
      <path d="M8.5 6H15a3 3 0 013 3v6.5" />
    </>
  ),
  branchement: <path d="M9 7H6a3 3 0 000 6h3M15 7h3a3 3 0 010 6h-3M8 10h8" />,
  api: <path d="M8 8l-4 4 4 4M16 8l4 4-4 4" />,
};

export function IconeDeGuide({ nom, taille = 16 }: { nom: IconeGuide; taille?: number }) {
  return (
    <svg width={taille} height={taille} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {TRACES[nom]}
    </svg>
  );
}
