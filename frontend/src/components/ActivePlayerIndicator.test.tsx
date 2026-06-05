import { render, waitFor } from '@testing-library/react'
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
})
