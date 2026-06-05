import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const allowCloudflareTunnel = process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL === '1'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: allowCloudflareTunnel
    ? {
        allowedHosts: ['.trycloudflare.com'],
      }
    : {},
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/setupTests.ts',
    css: true,
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/.{idea,git,cache,output,temp}/**',
      'tests/**/*',
    ],
  },
})
