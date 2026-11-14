import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En développement, /api est renvoyé vers le moteur Python (port 8010).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', rewrite: (chemin) => chemin.replace(/^\/api/, '') },
    },
  },
})
