// @vitest-environment node

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const indexHtml = readFileSync(path.join(process.cwd(), 'index.html'), 'utf8').replace(
  /\r\n/g,
  '\n'
)

describe('index.html', () => {
  it('keeps the Kyrandia easter egg in page source before the app root', () => {
    const easterEgg = '<!-- Slayer must die... -->'

    expect(indexHtml).toContain(easterEgg)
    expect(indexHtml.indexOf(easterEgg)).toBeLessThan(indexHtml.indexOf('<div id="root"></div>'))
  })
})
