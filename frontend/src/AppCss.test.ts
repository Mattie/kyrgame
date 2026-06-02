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
})
