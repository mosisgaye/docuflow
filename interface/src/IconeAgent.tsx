// L'icône de l'agent IA de Verifac : une étoile à quatre branches, en dégradé vert vers violet
// (la couleur de Verifac vers celle de l'IA). Dessin propre à Verifac.
import { useId } from 'react'

export function IconeAgent({ taille = 20 }: { taille?: number }) {
  const id = useId()
  return (
    <svg width={taille} height={taille} viewBox="0 0 24 24" aria-hidden="true" className="icone-agent" style={{ width: `${taille / 16}rem`, height: `${taille / 16}rem` }}>
      <defs>
        <linearGradient id={`${id}-degrade`} x1="3" y1="3" x2="21" y2="21" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#2bd397" />
          <stop offset="0.55" stopColor="#3aa6ff" />
          <stop offset="1" stopColor="#9b7bff" />
        </linearGradient>
      </defs>
      <path
        d="M12 2.5c.5 4.6 2.6 7.2 7.4 8.6.6.2.6 1 0 1.2-4.8 1.4-6.9 4-7.4 8.6-.1.7-1 .7-1.1 0-.5-4.6-2.6-7.2-7.4-8.6-.6-.2-.6-1 0-1.2 4.8-1.4 6.9-4 7.4-8.6.1-.7 1-.7 1.1 0Z"
        fill={`url(#${id}-degrade)`}
      />
      <circle cx="19" cy="5" r="1.6" fill="#9b7bff" />
      <circle cx="5.2" cy="18.6" r="1.1" fill="#2bd397" />
    </svg>
  )
}
