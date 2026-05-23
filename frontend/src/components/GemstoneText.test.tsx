import { render, screen } from '@testing-library/react'

import { getGemstoneVisual } from '../data/gemstonePalette'
import { GemstoneText } from './GemstoneText'

describe('GemstoneText', () => {
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
})
