// @vitest-environment node

import { afterEach, describe, expect, it, vi } from 'vitest'

const originalCloudflareEnv = process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL

const loadConfig = async () => {
  vi.resetModules()
  const configUrl = new URL('../vite.config.ts', import.meta.url).href
  return (await import(/* @vite-ignore */ configUrl)).default
}

describe('Vite config', () => {
  afterEach(() => {
    if (originalCloudflareEnv === undefined) {
      delete process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL
    } else {
      process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL = originalCloudflareEnv
    }
    vi.resetModules()
  })

  it('keeps dev-server host checks strict by default', async () => {
    delete process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL

    const config = await loadConfig()

    expect(config.server).not.toHaveProperty('allowedHosts')
  })

  it('allows Cloudflare preview hosts only when opted in', async () => {
    process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL = '1'

    const config = await loadConfig()

    expect(config.server?.allowedHosts).toEqual(['.trycloudflare.com'])
  })
})
