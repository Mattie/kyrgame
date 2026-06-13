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
        gem_spawn_interval_seconds: 90,
        next_gem_spawn_attempt_seconds: 60,
        successful_spawns_until_random_gem: 4,
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
        {
          id: 'gem_spawner',
          name: 'Gem spawner',
          status: 'waiting',
          room_id: 167,
          room: { id: 167, brief: 'deep in the forest' },
          next_attempt_seconds: 60,
          successful_spawns_until_random_gem: 4,
          gem_counter: 7,
          last_attempt_room_id: 167,
          last_attempt_status: 'spawned',
          last_spawn_room_id: 167,
          last_spawn_object_id: 11,
          last_spawn_object_name: 'bloodstone',
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

  it('renders gemstone spawn timing status', async () => {
    render(<AdminMobPanel />)

    await waitFor(() => expect(fetchAdminMobs).toHaveBeenCalled())

    expect(screen.getByText('💎 Gems')).toHaveClass('gem-spawner-inline')
    expect(screen.getByText('Last spawn room 167: deep in the forest')).toBeInTheDocument()
    expect(
      screen.getByText((_content, element) =>
        Boolean(
          element?.tagName === 'SPAN' &&
            element.textContent?.includes('next 1m; last attempt succeeded room 167') &&
            element.textContent.includes('bloodstone') &&
            element.textContent.includes('room 167; random in 4')
        )
      )
    ).toBeInTheDocument()
    expect(screen.getByText('Gem spawn 1m 30s')).toBeInTheDocument()
  })

  it('keeps last successful gem visible after a skipped attempt', async () => {
    fetchAdminMobs.mockResolvedValueOnce({
      animation: {
        next_routine: 'gemakr',
        routine_sequence: [],
        animation_tick_interval_seconds: 15,
        brownie_routine_interval_seconds: 90,
        brownie_full_path_interval_seconds: 3600,
        gem_spawn_interval_seconds: 90,
        next_gem_spawn_attempt_seconds: 15,
        successful_spawns_until_random_gem: 4,
      },
      mobs: [
        {
          id: 'gem_spawner',
          name: 'Gem spawner',
          status: 'waiting',
          room_id: 167,
          room: { id: 167, brief: 'deep in the forest' },
          next_attempt_seconds: 15,
          successful_spawns_until_random_gem: 4,
          gem_counter: 7,
          last_attempt_room_id: 51,
          last_attempt_status: 'skipped_capacity',
          last_spawn_room_id: 167,
          last_spawn_object_id: 11,
          last_spawn_object_name: 'bloodstone',
        },
      ],
    })

    render(<AdminMobPanel />)

    await waitFor(() => expect(fetchAdminMobs).toHaveBeenCalled())

    expect(screen.getByText('Last spawn room 167: deep in the forest')).toBeInTheDocument()
    expect(
      screen.getByText((_content, element) =>
        Boolean(
          element?.tagName === 'SPAN' &&
            element.textContent?.includes('next 15s; last attempt skipped capacity room 51') &&
            element.textContent.includes('bloodstone') &&
            element.textContent.includes('room 167; random in 4')
        )
      )
    ).toBeInTheDocument()
  })
})
