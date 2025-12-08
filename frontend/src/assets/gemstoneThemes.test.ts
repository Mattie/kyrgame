import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { GEMSTONE_THEMES, getGemstoneTheme } from './gemstoneThemes'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const gemstoneExpectations = {
  ruby: { emoji: '❤️', lightColor: '#f87171', darkColor: '#7f1d1d' },
  emerald: { emoji: '🍀', lightColor: '#34d399', darkColor: '#065f46' },
  garnet: { emoji: '🍒', lightColor: '#fb7185', darkColor: '#831843' },
  pearl: { emoji: '🦪', lightColor: '#f8fafc', darkColor: '#94a3b8' },
  aquamarine: { emoji: '💧', lightColor: '#67e8f9', darkColor: '#0ea5e9' },
  moonstone: { emoji: '🌙', lightColor: '#e0e7ff', darkColor: '#312e81' },
  sapphire: { emoji: '🔷', lightColor: '#60a5fa', darkColor: '#1e3a8a' },
  diamond: { emoji: '💎', lightColor: '#e2e8f0', darkColor: '#0f172a' },
  amethyst: { emoji: '🪻', lightColor: '#c084fc', darkColor: '#6b21a8' },
  onyx: { emoji: '🖤', lightColor: '#4b5563', darkColor: '#0b0f19' },
  opal: { emoji: '🌈', lightColor: '#fde68a', darkColor: '#7c2d12' },
  bloodstone: { emoji: '🩸', lightColor: '#fca5a5', darkColor: '#991b1b' },
} as const

describe('gemstone themes', () => {
  it('covers every gemstone listed in the fixtures', () => {
    const fixturePath = path.resolve(__dirname, '../../../backend/fixtures/objects.json')
    const objects = JSON.parse(fs.readFileSync(fixturePath, 'utf-8')) as { name: string }[]
    const gemstoneNames = Object.keys(gemstoneExpectations)

    gemstoneNames.forEach((name) => {
      expect(objects.map((obj) => obj.name)).toContain(name)
    })

    expect(Object.keys(GEMSTONE_THEMES).sort()).toEqual(gemstoneNames.sort())
  })

  it('assigns unique emojis and palettes to each gemstone', () => {
    const themes = Object.values(GEMSTONE_THEMES)
    const emojis = new Set(themes.map((theme) => theme.emoji))
    const palettes = new Set(themes.map((theme) => `${theme.lightColor}|${theme.darkColor}`))

    expect(emojis.size).toBe(themes.length)
    expect(palettes.size).toBe(themes.length)
  })

  it('returns the configured theme for a gemstone name', () => {
    const ruby = getGemstoneTheme('Ruby')
    expect(ruby).toMatchObject({
      name: 'ruby',
      ...gemstoneExpectations.ruby,
    })
  })

  it('matches the curated emoji and color scheme for every gemstone', () => {
    Object.entries(gemstoneExpectations).forEach(([name, expectation]) => {
      const theme = getGemstoneTheme(name)
      expect(theme).toMatchObject({ name, ...expectation })
    })
  })
})
