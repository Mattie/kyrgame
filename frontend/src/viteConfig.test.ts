// @vitest-environment node

import { afterEach, describe, expect, it, vi } from 'vitest'

const originalCloudflareEnv = process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL
const originalAllowedHostsEnv = process.env.KYRGAME_VITE_ALLOWED_HOSTS

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
    if (originalAllowedHostsEnv === undefined) {
      delete process.env.KYRGAME_VITE_ALLOWED_HOSTS
    } else {
      process.env.KYRGAME_VITE_ALLOWED_HOSTS = originalAllowedHostsEnv
    }
    vi.resetModules()
  })

  it('allows the named alpha host by default', async () => {
    delete process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL
    delete process.env.KYRGAME_VITE_ALLOWED_HOSTS

    const config = await loadConfig()

    expect(config.server?.allowedHosts).toEqual(['willow.eventscripts.com'])
    expect(config.server?.allowedHosts).not.toContain(true)
  })

  it('adds Cloudflare preview hosts when opted in', async () => {
    process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL = '1'
    process.env.KYRGAME_VITE_ALLOWED_HOSTS = 'willow.eventscripts.com'

    const config = await loadConfig()

    expect(config.server?.allowedHosts).toEqual([
      'willow.eventscripts.com',
      '.trycloudflare.com',
    ])
  })

  it('trims comma-separated named hosts', async () => {
    delete process.env.KYRGAME_ALLOW_CLOUDFLARE_TUNNEL
    process.env.KYRGAME_VITE_ALLOWED_HOSTS =
      'willow.eventscripts.com, preview.eventscripts.com '

    const config = await loadConfig()

    expect(config.server?.allowedHosts).toEqual([
      'willow.eventscripts.com',
      'preview.eventscripts.com',
    ])
  })

  it('serves the admin page route through Vite while proxying admin APIs', async () => {
    const config = await loadConfig()
    const proxyPatterns = Object.keys(config.server?.proxy ?? {}).map(
      (pattern) => new RegExp(pattern),
    )
    const isProxied = (path: string) =>
      proxyPatterns.some((pattern) => pattern.test(path))

    expect(isProxied('/admin')).toBe(false)
    expect(isProxied('/admin?panel=players')).toBe(false)
    expect(isProxied('/admin/fixtures')).toBe(true)
    expect(isProxied('/admin/players/Necro')).toBe(true)
  })
})
