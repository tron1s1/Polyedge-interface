import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
    watch: {
      // Don't HMR-reload the browser when the scanner writes logs or
      // when the local JSON DB updates on every trade — these aren't source files.
      ignored: [
        '**/node1-scanner/**',
        '**/local_data/**',
        '**/*.log',
        '**/*.json.bak',
        '**/.venv/**',
        '**/__pycache__/**',
      ],
    },
  },
})
