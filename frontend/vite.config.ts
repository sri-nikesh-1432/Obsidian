import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      // Same-origin in development so session cookies behave like production.
      // Only the API prefix is proxied. The public share pages live at
      // `/s/:token` and must be served by the SPA (React Router renders the
      // document viewer there); the viewer then calls the API at
      // `/api/v1/s/:token`. Proxying `/s/` itself would return raw JSON
      // instead of the page — and a bare `/s` prefix would also swallow the
      // app's own `/src/...` modules.
      '^/api/': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:5000',
        changeOrigin: false,
      },
    },
  },
})
