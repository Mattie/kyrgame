// @vitest-environment node

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const readText = (...segments: string[]) =>
  readFileSync(path.join(process.cwd(), ...segments), 'utf8').replace(/\r\n/g, '\n')

describe('static deployment hygiene', () => {
  it('ships an SPA fallback for direct public route visits', () => {
    const redirects = readText('public', '_redirects')

    expect(redirects).toContain('/* /index.html 200')
  })

  it('keeps local references and full desktop captures out of git staging', () => {
    const gitignore = readText('.gitignore')

    expect(gitignore).toContain('.local_references/')
    expect(gitignore).toContain('screenshots/play-page-logo-footer-desktop.png')
  })
})
