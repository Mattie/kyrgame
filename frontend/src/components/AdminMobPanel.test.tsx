import { render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

import { AdminMobPanel } from './AdminMobPanel'

const fetchAdminMobs = vi.fn()

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => ({
    adminToken: 'dev-admin',
    currentRoom: 7,
    fetchAdminMobs,
    session: { playerId: 'hero', roomId: 7, token: 'session-token' },
    triggerElf: vi.fn(),
  }),
}))

describe('AdminMobPanel', () => {
  beforeEach(() => {
    fetchAdminMobs.mockReset()
    fetchAdminMobs.mockResolvedValue({
      animation: {
        next_routine: 'zarapp',
        routine_sequence: [],
        animation_tick_interval_seconds: 15,
        brownie_routine_interval_seconds: 90,
        brownie_full_path_interval_seconds: 3600,
      },
      mobs: [
        { id: 'dryad', name: 'Dryad', status: 'present', room_id: 0 },
        { id: 'brownie', name: 'Brownie', status: 'last_checked', room_id: 129 },
        { id: 'elf', name: 'Elf', status: 'between_encounters', room_id: 7 },
        {
          id: 'dragon',
          name: 'Zar',
          status: 'present',
          room_id: 302,
          next_attack: 'lightning',
          counter: 4,
        },
      ],
    })
  })

  it('renders mob names with creature inline styling', async () => {
    render(<AdminMobPanel />)

    await waitFor(() => expect(fetchAdminMobs).toHaveBeenCalled())

    expect(screen.getByText('🌱 Dryad')).toHaveClass('creature-dryad')
    screen.getAllByText('😈 Brownie').forEach((element) => {
      expect(element).toHaveClass('creature-brownie')
    })
    expect(screen.getByText('🧝 Elf')).toHaveClass('creature-elf')
    expect(screen.getByText('🐲 Zar')).toHaveClass('creature-dragon')
  })
})
