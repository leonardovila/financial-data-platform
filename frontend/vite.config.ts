import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // REST API calls (GET /symbols, etc.)
      '/symbols': 'http://localhost:8000',
      '/ohlcv': 'http://localhost:8000',
      '/fundamentals': 'http://localhost:8000',
      '/performance': 'http://localhost:8000',
      '/volatility': 'http://localhost:8000',
      '/volume': 'http://localhost:8000',
      '/ws': {
        target: 'http://localhost:8000',
        ws: true,
      },
    },
  },
})
