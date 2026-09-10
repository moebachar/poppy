import { createRoot } from 'react-dom/client'
import '@fontsource/space-grotesk/400.css'
import '@fontsource/space-grotesk/500.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import './kiosk.css'
import KioskApp from './KioskApp'
import { connect } from './link'

connect()

// No StrictMode: the hologram module owns a WebGL context; dev double-mount
// would create/dispose it twice for nothing.
createRoot(document.getElementById('root')!).render(<KioskApp />)
