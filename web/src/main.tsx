import '@fontsource-variable/big-shoulders-display'
import '@fontsource/ibm-plex-sans/latin-400'
import '@fontsource/ibm-plex-sans/latin-500'
import '@fontsource/ibm-plex-sans/latin-600'
import '@fontsource/ibm-plex-mono/latin-400'
import '@fontsource/ibm-plex-mono/latin-500'
import '@fontsource/ibm-plex-mono/latin-600'
import './styles/index.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
