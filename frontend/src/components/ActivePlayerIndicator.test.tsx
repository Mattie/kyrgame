import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ActivePlayerIndicator } from './ActivePlayerIndicator'

const navigatorState = vi.hoisted(() => ({
  value: {
    apiBaseUrl: 'http://api.local',
    connectionStatus: 'connected',
  },
}))

vi.mock('../context/NavigatorContext', () => ({
  useNavigator: () => navigatorState.value,
}))

describe('ActivePlayerIndicator', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('aborts pending active-player refreshes when unmounted', async () => {
    const signals: Array<AbortSignal | undefined> = []
    vi.spyOn(global, 'fetch').mockImplementation((_input, init) => {
      signals.push(init?.signal as AbortSignal | undefined)
      return new Promise<Response>(() => {})
    })

    const { unmount } = render(<ActivePlayerIndicator />)

    await waitFor(() => expect(signals).toHaveLength(2))

    unmount()

    expect(signals.every((signal) => signal?.aborted)).toBe(true)
  })

  it('marks connection durations with a machine-readable duration', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        active: [
          {
            player_id: 'hero',
            display_name: 'Hero',
            level: 12,
            rank_title: 'Wizard',
            active: true,
            connection_duration_seconds: 135,
          },
        ],
      }),
    } as unknown as Response)

    render(<ActivePlayerIndicator />)

    const trigger = await screen.findByRole('button', { name: /active players: 1/i })
    await userEvent.click(trigger)

    expect(screen.getByText('2m 15s').closest('time')).toHaveAttribute('dateTime', 'PT2M15S')
  })
})
