import { createRoot } from 'react-dom/client'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/space-grotesk/500.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/panels.css'
import './styles/voice.css'
import './styles/admin.css'
import App from './App'
import { connectWS } from './api'

connectWS()

// No StrictMode: the hologram module owns a WebGL context; dev double-mount
// would create/dispose it twice for nothing.
createRoot(document.getElementById('root')!).render(<App />)
