import '@fontsource-variable/instrument-sans'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Application } from './Application'
import { appliquerTheme, themeInitial } from './theme'
import './styles.css'

// Le thème est posé avant le premier affichage : pas d'éclair blanc en thème sombre.
appliquerTheme(themeInitial())

createRoot(document.getElementById('racine')!).render(
  <StrictMode>
    <Application />
  </StrictMode>,
)
