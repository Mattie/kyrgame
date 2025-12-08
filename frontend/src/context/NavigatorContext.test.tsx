import React from 'react'

import { act, renderHook, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

import { NavigatorProvider, useNavigator } from './NavigatorContext'

class MockWebSocket {
  static instances: MockWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  url: string

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send() {}

  close() {
    this.onclose?.()
  }

  emit(data: any) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

type FetchResponse = { body: any; status?: number }

describe('NavigatorProvider', () => {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <NavigatorProvider>{children}</NavigatorProvider>
  )

  const mockResponses: FetchResponse[] = []

  const enqueueResponse = (body: any, status = 200) => {
    mockResponses.push({ body, status })
  }

  beforeEach(() => {
    MockWebSocket.instances = []
    global.WebSocket = MockWebSocket as any
    mockResponses.splice(0, mockResponses.length)

    global.fetch = vi.fn().mockImplementation(async () => {
      if (mockResponses.length === 0) {
        throw new Error('No mock response available')
      }
      const next = mockResponses.shift() as FetchResponse
      return new Response(JSON.stringify(next.body), {
        status: next.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  })

  it('appends a room description after the initial welcome without duplicating the ellipsis prefix or listing the player as an occupant', async () => {
    enqueueResponse({
      session: { token: 'abc', player_id: 'Zonk', room_id: 1 },
    })
    enqueueResponse([
      {
        id: 1,
        brfdes: 'A brief description',
        objlds: 'on the path',
        objects: [1],
      },
    ])
    enqueueResponse([{ id: 1, name: 'emerald', flags: ['VISIBL', 'NEEDAN'] }])
    enqueueResponse([])
    enqueueResponse({ messages: { KRD001: '...A misty clearing' } })

    const { result } = renderHook(() => useNavigator(), { wrapper })

    await act(async () => {
      await result.current.startSession('Zonk')
    })

    const socket = MockWebSocket.instances[0]
    expect(socket).toBeDefined()

    act(() => {
      socket.emit({ type: 'room_welcome', room: 1 })
    })

    await waitFor(() => {
      expect(
        result.current.activity.some(
          (entry) => entry.payload && (entry.payload as any).event === 'location_description'
        )
      ).toBe(true)
    })

    const locationEntry = result.current.activity.find(
      (entry) => entry.payload && (entry.payload as any).event === 'location_description'
    )

    expect(locationEntry?.summary).toBe('...A misty clearing')
    expect(locationEntry?.extraLines?.some((line) => /is here\./i.test(line))).toBe(false)
  })
})
