import { afterEach, describe, expect, it, vi } from 'vitest'

const setLocation = (url: string) => {
  Object.defineProperty(window, 'location', {
    value: new URL(url),
    writable: true,
  })
}

afterEach(() => {
  vi.resetModules()
  localStorage.clear()
  setLocation('http://localhost/')
})

describe('getConsoleStreamConfig', () => {
  it('uses default config when no overrides are supplied', async () => {
    setLocation('http://localhost/')
    const { getConsoleStreamConfig } = await import('./consoleStream')

    expect(getConsoleStreamConfig()).toEqual({
      enabled: true,
      baud: 20000,
      charsPerSecond: 2000,
      charsPerTick: 500,
    })
  })

  it('reads modem mode and speed overrides from query params', async () => {
    setLocation('http://localhost/?modem=on&modemBaud=3200&modemCharsPerTick=2')
    const { getConsoleStreamConfig } = await import('./consoleStream')

    expect(getConsoleStreamConfig()).toEqual({
      enabled: true,
      baud: 3200,
      charsPerSecond: 320,
      charsPerTick: 2,
    })
  })

  it('falls back to localStorage for enabled state when no query override is provided', async () => {
    localStorage.setItem('kyr.console.modem', 'off')
    setLocation('http://localhost/?foo=bar')
    const { getConsoleStreamConfig } = await import('./consoleStream')

    expect(getConsoleStreamConfig()).toEqual({
      enabled: false,
      baud: 20000,
      charsPerSecond: 2000,
      charsPerTick: 500,
    })
  })

  it('lets query param modem=off override localStorage on', async () => {
    localStorage.setItem('kyr.console.modem', 'on')
    setLocation('http://localhost/?modem=off')
    const { getConsoleStreamConfig } = await import('./consoleStream')

    expect(getConsoleStreamConfig().enabled).toBe(false)
  })
})
