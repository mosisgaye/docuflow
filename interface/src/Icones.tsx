// Petites icônes au trait, dessinées en SVG. Elles prennent la couleur du texte.

const TRACES: Record<string, string> = {
  accueil: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  document: 'M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM14 3v5h5M9 13h6M9 17h6',
  validation: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8 12.5l2.7 2.7L16 9.5',
  assistant: 'M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z',
  integration: 'M9 3v5M15 3v5M7 8h10v4a5 5 0 0 1-10 0zM12 17v4',
  recherche: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  horloge: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3.5 2',
  bouclier: 'M12 3l7 3v5.5c0 4.3-2.9 7.6-7 9.5-4.1-1.9-7-5.2-7-9.5V6zM8.8 12l2.3 2.3 4.2-4.6',
  alerte: 'M12 4l9 15.5H3zM12 10v4.5M12 17.2v.3',
  eclair: 'M13 3 5 13.5h6L10 21l8-10.5h-6z',
  reception: 'M4 6h16v12H4zM4 7l8 6 8-6',
  utilisateur: 'M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM5 20c.8-3.5 3.6-5.5 7-5.5s6.2 2 7 5.5',
  coche: 'M5 12.5l4.5 4.5L19 7.5',
  fleche: 'M5 12h14M13 6l6 6-6 6',
}

export function Icone({ nom, taille = 20 }: { nom: keyof typeof TRACES; taille?: number }) {
  return (
    <svg width={taille} height={taille} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={TRACES[nom]} />
    </svg>
  )
}
