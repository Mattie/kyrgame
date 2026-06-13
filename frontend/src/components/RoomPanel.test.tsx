import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { getGemstoneVisual } from '../data/gemstonePalette'
import { getGroundObjectVisual } from '../data/groundObjectVisuals'
import { RoomPanel } from './RoomPanel'

const highlightedGroundObjectNames = [
  'scroll',
  'elixir',
  'codex',
  'pinecone',
  'tome',
  'parchment',
] as const

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => ({
    world: {
      locations: [
        {
          id: 1,
          brfdes: 'Cavern of jewels',
          objlds: 'on a velvet pillow',
          objects: [0, 12, 32, 35, 36, 37, 38, 45],
        },
      ],
      objects: [
        { id: 0, name: 'ruby' },
        { id: 12, name: 'elixir' },
        { id: 32, name: 'pinecone' },
        { id: 35, name: 'scroll' },
        { id: 36, name: 'codex' },
        { id: 37, name: 'tome' },
        { id: 38, name: 'parchment' },
        { id: 45, name: 'dryad' },
      ],
      commands: [],
      messages: {},
    },
    currentRoom: 1,
    occupants: [],
    sendMove: vi.fn(),
  }),
}))

describe('RoomPanel', () => {
  it('renders gemstone badges with unique emoji and colors', () => {
    render(<RoomPanel />)

    const badge = screen.getByTestId('gemstone-badge-ruby')
    const visual = getGemstoneVisual('ruby')!

    expect(badge).toHaveTextContent(visual.emoji)
    expect(badge).toHaveTextContent(/ruby/i)
    expect(badge).toHaveStyle({
      '--gem-light': visual.lightColor,
      '--gem-dark': visual.darkColor,
    })

    expect(screen.getByText('🌱 dryad')).toHaveClass('creature-dryad')
  })

  it('renders highlighted ground object badges with configured emoji and colors', () => {
    render(<RoomPanel />)

    highlightedGroundObjectNames.forEach((name) => {
      const visual = getGroundObjectVisual(name)!
      const badge = screen.getByTestId(`ground-object-badge-${name}`)

      expect(badge).toHaveTextContent(visual.emoji)
      expect(badge).toHaveTextContent(visual.displayName)
      expect(badge).toHaveClass(visual.className)
      expect(badge).toHaveStyle({
        '--gem-light': visual.color,
        '--gem-dark': visual.darkColor,
      })
    })
  })
})
