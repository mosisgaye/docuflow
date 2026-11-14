import '@fontsource-variable/bricolage-grotesque'
import '@fontsource-variable/instrument-sans'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Application } from './Application'
import './styles.css'

createRoot(document.getElementById('racine')!).render(
  <StrictMode>
    <Application />
  </StrictMode>,
)
