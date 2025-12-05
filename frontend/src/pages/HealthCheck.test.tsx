import { render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

import { HealthCheck } from './HealthCheck'

vi.mock('../config/endpoints', () => ({
  getApiBaseUrl: () => 'http://api.local',
}))

describe('HealthCheck', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('requests locations at startup and shows the count on success', async () => {
    const locations = [{ id: 1 }, { id: 2 }, { id: 3 }]
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(locations),
    } as unknown as Response)

    render(<HealthCheck />)

    expect(global.fetch).toHaveBeenCalledWith(
      'http://api.local/world/locations',
      expect.objectContaining({ headers: expect.any(Object) })
    )

    await waitFor(() =>
      expect(
        screen.getByText(/locations reachable/i)
      ).toBeInTheDocument()
    )
    expect(screen.getByText(/3 locations loaded/i)).toBeInTheDocument()
  })

  it('surfaces error details when the request fails', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 503,
      statusText: 'Service Unavailable',
      json: () => Promise.resolve({ detail: 'backend offline' }),
    } as unknown as Response)

    render(<HealthCheck />)

    await waitFor(() =>
      expect(
        screen.getByText(/locations unreachable/i)
      ).toBeInTheDocument()
    )
    expect(screen.getByText(/503/)).toBeInTheDocument()
  })
})
