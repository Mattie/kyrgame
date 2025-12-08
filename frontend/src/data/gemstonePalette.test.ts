import { formatGemstoneLabel, gemstonePalette, getGemstoneVisual } from './gemstonePalette'

const gemstoneNames = [
  'ruby',
  'emerald',
  'garnet',
  'pearl',
  'aquamarine',
  'moonstone',
  'sapphire',
  'diamond',
  'amethyst',
  'onyx',
  'opal',
  'bloodstone',
  'kyragem',
  'soulstone',
]

describe('gemstonePalette', () => {
  it('includes every gemstone from the item fixtures', () => {
    expect(Object.keys(gemstonePalette).sort()).toEqual(gemstoneNames.sort())
  })

  it('assigns unique emoji and color pairs to each gemstone', () => {
    const visuals = gemstoneNames.map((name) => {
      const visual = getGemstoneVisual(name)
      expect(visual).toBeTruthy()
      expect(visual?.emoji).toBeTruthy()
      expect(visual?.lightColor).toMatch(/^#/) // bright-mode color
      expect(visual?.darkColor).toMatch(/^#/) // dark-mode color
      return visual!
    })

    const emojis = new Set(visuals.map((visual) => visual.emoji))
    const colorPairs = new Set(
      visuals.map((visual) => `${visual.lightColor}|${visual.darkColor}`)
    )

    expect(emojis.size).toBe(visuals.length)
    expect(colorPairs.size).toBe(visuals.length)
  })

  it('formats gemstone labels with an emoji prefix and a capitalized name', () => {
    const rubyVisual = getGemstoneVisual('ruby')!
    expect(formatGemstoneLabel('ruby')).toContain(rubyVisual.emoji)
    expect(formatGemstoneLabel('ruby')).toContain('Ruby')

    expect(formatGemstoneLabel('unknown')).toBe('Unknown')
  })
})
