import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const allowCloudflareTunnel = process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL === '1'
const backendProxyTarget = process.env.KYRGAME_BACKEND_PROXY_TARGET || 'http://backend:8000'
const configuredAllowedHosts = (process.env.KYRGAME_VITE_ALLOWED_HOSTS || 'willow.eventscripts.com')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean)
const tunnelAllowedHosts = Array.from(
  new Set([
    ...configuredAllowedHosts,
    ...(allowCloudflareTunnel ? ['.trycloudflare.com'] : []),
  ]),
)
const usePolling = process.env.KYRGAME_VITE_USE_POLLING === '1'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    watch: usePolling
      ? {
          usePolling: true,
          interval: 300,
        }
      : undefined,
    ...(tunnelAllowedHosts.length > 0 ? { allowedHosts: tunnelAllowedHosts } : {}),
    proxy: {
      '^/(auth|public|i18n|world|objects|spells|commands|players|content|ws)(/|\\?|$)|^/admin/(?!($|\\?))': {
        target: backendProxyTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
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
