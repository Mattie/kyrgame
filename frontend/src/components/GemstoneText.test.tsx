import { render, screen } from '@testing-library/react'

import { getGemstoneVisual } from '../data/gemstonePalette'
import { getGroundObjectVisual } from '../data/groundObjectVisuals'
import { GemstoneText } from './GemstoneText'
import { INLINE_DECORATION_NONE } from './inlineDecorations'

describe('GemstoneText', () => {
  const ghostEmoji = '\u{1F47B}'
  const wingEmoji = '\u{1FABD}'
  const dragonEmoji = '\u{1F409}'
  const sparklesEmoji = '\u{2728}'
  const tearEmoji = '\u{1F4A7}'
  const amuletEmoji = '\u{1F9FF}'

  it('renders creature names with emoji and themed colors', () => {
    render(
      <GemstoneText text="Zar and the dragon menace the dryad, elf, and brownie." />
    )

    expect(screen.getByText('🐲 Zar')).toHaveClass('creature-dragon')
    expect(screen.getByText('🐲 dragon')).toHaveClass('creature-dragon')
    expect(screen.getByText('🌱 dryad')).toHaveClass('creature-dryad')
    expect(screen.getByText('🧝 elf')).toHaveClass('creature-elf')
    expect(screen.getByText('😈 brownie')).toHaveClass('creature-brownie')
    expect(screen.getByText('🐲 Zar')).toHaveStyle({ color: '#ff6b5f' })
    expect(screen.getByText('🌱 dryad')).toHaveStyle({ color: 'rgb(154, 205, 50)' })
    expect(screen.getByText('🧝 elf')).toHaveStyle({ color: 'rgb(0, 128, 0)' })
    expect(screen.getByText('😈 brownie')).toHaveStyle({ color: '#b07a4f' })
  })

  it('does not style dragonstaff as a dragon name', () => {
    const { container } = render(<GemstoneText text="rub dragonstaff near dragon's lair" />)

    expect(container.querySelectorAll('.creature-dragon')).toHaveLength(1)
    expect(screen.getByText("🐲 dragon")).toBeInTheDocument()
    expect(container).toHaveTextContent("dragonstaff")
  })

  it('renders legacy transformation aliases with dedicated form visuals', () => {
    render(
      <GemstoneText text="Some Unseen Force, Some pegasus, Some psuedo dragon, and Some willowisp arrive." />
    )

    const unseen = screen.getByText(`${ghostEmoji} Some Unseen Force`)
    const pegasus = screen.getByText(`${wingEmoji} Some pegasus`)
    const pseudoDragon = screen.getByText(`${dragonEmoji} Some psuedo dragon`)
    const willowisp = screen.getByText(`${sparklesEmoji} Some willowisp`)

    expect(unseen).toHaveClass('transformation-inline', 'form-unseen-force')
    expect(pegasus).toHaveClass('transformation-inline', 'form-pegasus')
    expect(pseudoDragon).toHaveClass('transformation-inline', 'form-pseudo-dragon')
    expect(willowisp).toHaveClass('transformation-inline', 'form-willowisp')
    expect(unseen).toHaveStyle({ color: '#ffe4f1' })
    expect((unseen as HTMLElement).style.textShadow).toBe(
      '0 0 6px rgba(255,255,255,0.57), 0 0 14px rgba(255,228,241,0.45)'
    )
    expect(pseudoDragon).toHaveStyle({ color: '#b6402b' })
    expect(willowisp).toHaveStyle({ color: '#facc15' })
    expect(pegasus).toHaveStyle({ color: '#ffffff' })
  })

  it('protects pseudo-dragon forms and midword dragon text from generic dragon styling', () => {
    const { container } = render(
      <GemstoneText text="Some pseudo dragon, psuedo dragon, puesdo dragon, pseudodragon, psuedodragon, dragonstaff, and dragon." />
    )

    expect(screen.getByText(`${dragonEmoji} Some pseudo dragon`)).toHaveClass(
      'form-pseudo-dragon'
    )
    expect(screen.getByText(`${dragonEmoji} psuedo dragon`)).toHaveClass(
      'form-pseudo-dragon'
    )
    expect(screen.getByText(`${dragonEmoji} puesdo dragon`)).toHaveClass(
      'form-pseudo-dragon'
    )
    expect(screen.getByText('🐲 dragon')).toHaveClass('creature-dragon')
    expect(container.querySelectorAll('.creature-dragon')).toHaveLength(1)
    expect(container).toHaveTextContent('pseudodragon')
    expect(container).toHaveTextContent('psuedodragon')
    expect(container).toHaveTextContent('dragonstaff')
  })

  it('renders parchment like scrolls and tome like codexes', () => {
    const scroll = getGroundObjectVisual('scroll')!
    const codex = getGroundObjectVisual('codex')!
    const parchment = getGroundObjectVisual('parchment')!
    const tome = getGroundObjectVisual('tome')!

    expect(parchment.emoji).toBe(scroll.emoji)
    expect(parchment.color).toBe(scroll.color)
    expect(parchment.darkColor).toBe(scroll.darkColor)
    expect(tome.emoji).toBe(codex.emoji)
    expect(tome.color).toBe(codex.color)
    expect(tome.darkColor).toBe(codex.darkColor)

    render(<GemstoneText text="A parchment and a tome are here." />)

    expect(screen.getByText(`${parchment.emoji} parchment`)).toHaveClass(
      'ground-object-inline',
      'object-parchment'
    )
    expect(screen.getByText(`${tome.emoji} tome`)).toHaveClass(
      'ground-object-inline',
      'object-tome'
    )
  })

  it('renders shard and amulet as dedicated ground object visuals', () => {
    const shard = getGroundObjectVisual('shard')!
    const amulet = getGroundObjectVisual('amulet')!

    expect(shard.emoji).toBe(tearEmoji)
    expect(shard.color).toBe('#7498db')
    expect(shard.darkColor).toBe('#7498db')
    expect(shard.className).toBe('object-shard')
    expect(amulet.emoji).toBe(amuletEmoji)
    expect(amulet.color).toBe('#8ecae6')
    expect(amulet.darkColor).toBe('#1d4ed8')
    expect(amulet.className).toBe('object-amulet')

    render(<GemstoneText text="A shard rests near an amulet." />)

    const shardInline = screen.getByText(`${tearEmoji} shard`)
    const amuletInline = screen.getByText(`${amuletEmoji} amulet`)

    expect(shardInline).toHaveClass('ground-object-inline', 'object-shard')
    expect(shardInline).toHaveStyle({ color: '#7498db' })
    expect((shardInline as HTMLElement).style.textShadow).toBe('')
    expect(amuletInline).toHaveClass('ground-object-inline', 'object-amulet')
  })

  it('keeps gemstone styling intact', () => {
    const ruby = getGemstoneVisual('ruby')
    expect(ruby).not.toBeNull()
    const { container } = render(<GemstoneText text="A ruby rests beside Zar." />)

    expect(screen.getByText(`${ruby!.emoji} ruby`)).toHaveClass('gemstone-inline')
    expect(screen.getByText('🐲 Zar')).toHaveClass('creature-dragon')
    expect(container.querySelector('.gemstone-inline')).toHaveStyle({
      color: ruby!.lightColor,
    })
  })

  it('renders known player names with wizard emoji and violet styling', () => {
    render(
      <GemstoneText
        text="Merlin greets Morgana while Zar watches."
        playerVisuals={{
          Merlin: {
            emoji: '🧙‍♂️',
            className: 'player-wizard',
            color: '#a78bfa',
          },
          Morgana: {
            emoji: '🧙‍♀️',
            className: 'player-wizard',
            color: '#a78bfa',
          },
        }}
      />
    )

    expect(screen.getByText('🧙‍♂️ Merlin')).toHaveClass('player-wizard')
    expect(screen.getByText('🧙‍♀️ Morgana')).toHaveClass('player-wizard')
    expect(screen.getByText('🐲 Zar')).toHaveClass('creature-dragon')
    expect(screen.getByText('🧙‍♂️ Merlin')).toHaveStyle({ color: '#a78bfa' })
  })

  it('can suppress all inline decorations for fixed-width or prose-only text', () => {
    const { container } = render(
      <GemstoneText
        text="Spell Book of Lord Merlin near Zar and a ruby"
        inlineDecorations={INLINE_DECORATION_NONE}
        playerVisuals={{
          Merlin: {
            emoji: '\u{1F9D9}\u200D\u2642\uFE0F',
            className: 'player-wizard',
            color: '#a78bfa',
          },
        }}
      />
    )

    expect(container).toHaveTextContent('Spell Book of Lord Merlin near Zar and a ruby')
    expect(container.querySelector('.player-wizard')).toBeNull()
    expect(container.querySelector('.creature-dragon')).toBeNull()
    expect(container.querySelector('.gemstone-inline')).toBeNull()
  })
})
