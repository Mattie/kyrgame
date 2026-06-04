import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const appCss = readFileSync(path.join(process.cwd(), 'src', 'App.css'), 'utf8')

const readRule = (selector: string) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = appCss.match(new RegExp(`${escaped}\\s*{([^}]*)}`))
  return match?.[1] ?? ''
}

describe('App CSS', () => {
  it('leaves the MUD window panel visually transparent for the burn-edge frame', () => {
    const rule = readRule('.mud-window')

    expect(rule).toContain('background: transparent;')
    expect(rule).toContain('border: none;')
    expect(rule).toContain('box-shadow: none;')
  })

  it('keeps the command mode hint compact', () => {
    const rule = readRule('.mode-hint')

    expect(rule).toContain('font-size: 0.7rem;')
  })

  it('reserves a legacy terminal-sized text viewport in the MUD console', () => {
    const crtRule = readRule('.crt')
    const linesRule = readRule('.crt-lines')

    expect(crtRule).toContain('min-height: calc(22lh + 1.7rem + 1px);')
    expect(crtRule).toContain('min-width: calc(80ch + 1.7rem);')
    expect(crtRule).toContain('line-height: 1.6;')
    expect(linesRule).toContain('min-width: 80ch;')
    expect(linesRule).toContain('min-height: calc(22lh + 1px);')
    expect(linesRule).toContain('gap: 0.3rem;')
  })

  it('compacts surrounding chrome on short viewports so the prompt stays visible', () => {
    expect(appCss).toContain('@media (min-width: 761px) and (max-height: 960px)')
    expect(appCss).toContain('.app-shell {\n    padding: 1rem 1.5rem;')
    expect(appCss).toContain('.navigator {\n    gap: 0.75rem;')
    expect(appCss).toContain('.mud-shell {\n    padding: 0.7rem;')
    expect(appCss).toContain('.prompt-row {\n    margin-top: 0.5rem;')
  })

  it('lets very short landscape viewports scroll instead of clipping the prompt', () => {
    expect(appCss).toContain('@media (min-width: 761px) and (max-height: 520px)')
    expect(appCss).toContain('.app-shell {\n    overflow-y: auto;')
    expect(appCss).toContain('.navigator {\n    height: auto;')
    expect(appCss).toContain('.layout {\n    flex: 0 0 auto;')
    expect(appCss).toContain('.primary {\n    min-height: max-content;')
  })

  it('uses an adaptive mobile console layout instead of hard-clipping desktop geometry', () => {
    expect(appCss).toContain('@media (max-width: 760px)')
    expect(appCss).toContain('height: 100dvh;')
    expect(appCss).toContain('overflow-y: auto;')
    expect(appCss).toContain('.mobile-controls-toggle')
    expect(appCss).toContain('.navigator.controls-closed .secondary')
    expect(appCss).toContain('.crt {\n    min-width: 0;')
    expect(appCss).toContain('.crt-lines {\n    min-width: 0;')
    expect(appCss).toContain('.prompt-row {\n    position: sticky;')
  })
})
