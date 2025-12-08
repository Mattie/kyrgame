import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { getGemstoneVisual } from '../data/gemstonePalette'
import { RoomPanel } from './RoomPanel'

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => ({
    world: {
      locations: [
        {
          id: 1,
          brfdes: 'Cavern of jewels',
          objlds: 'on a velvet pillow',
          objects: [0],
        },
      ],
      objects: [{ id: 0, name: 'ruby' }],
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
  })
})
