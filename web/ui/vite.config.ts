import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { existsSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

// Second entry (hologram test harness) belongs to track D; guard so the
// build passes before that file lands.
const harness = fileURLToPath(new URL('./holo-harness.html', import.meta.url))
const input: Record<string, string> = {
  index: fileURLToPath(new URL('./index.html', import.meta.url)),
  kiosk: fileURLToPath(new URL('./kiosk.html', import.meta.url)),
}
if (existsSync(harness)) input.harness = harness

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    rollupOptions: { input },
  },
})
