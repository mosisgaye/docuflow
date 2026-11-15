export type Theme = 'light' | 'dark'

const CLE = 'docuflow.theme'

/** Le choix de la personne s'il existe, sinon le réglage de son système. */
export function themeInitial(): Theme {
  try {
    const choisi = localStorage.getItem(CLE)
    if (choisi === 'light' || choisi === 'dark') return choisi
  } catch {
    // Stockage indisponible (navigation privée) : on suit le système.
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function appliquerTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
}

export function retenirTheme(theme: Theme) {
  appliquerTheme(theme)
  try {
    localStorage.setItem(CLE, theme)
  } catch {
    // Sans stockage, le choix vaut pour cette visite seulement.
  }
}
