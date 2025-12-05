import { useEffect, useMemo, useState } from 'react'

import { getApiBaseUrl } from '../config/endpoints'

type HealthState =
  | { status: 'loading' }
  | { status: 'success'; locations: number }
  | { status: 'error'; detail: string }

export const HealthCheck = () => {
  const apiBaseUrl = useMemo(() => getApiBaseUrl(), [])
  const locationsUrl = useMemo(
    () => `${apiBaseUrl.replace(/\/$/, '')}/world/locations`,
    [apiBaseUrl]
  )
  const [state, setState] = useState<HealthState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false

    const fetchLocations = async () => {
      setState({ status: 'loading' })
      try {
        const response = await fetch(locationsUrl, {
          headers: {
            Accept: 'application/json',
          },
        })

        if (!response.ok) {
          const body = await response.json().catch(() => ({}))
          const detail =
            typeof body?.detail === 'string' && body.detail.trim().length > 0
              ? `: ${body.detail}`
              : ''

          if (!cancelled) {
            setState({
              status: 'error',
              detail: `${response.status} ${response.statusText}${detail}`.trim(),
            })
          }
          return
        }

        const payload = await response.json()
        const locations = Array.isArray(payload) ? payload.length : 0

        if (!cancelled) {
          setState({ status: 'success', locations })
        }
      } catch (error) {
        if (!cancelled) {
          const detail = error instanceof Error ? error.message : 'Unknown error'
          setState({ status: 'error', detail })
        }
      }
    }

    fetchLocations()

    return () => {
      cancelled = true
    }
  }, [locationsUrl])

  return (
    <main className="health-check">
      <header>
        <p className="eyebrow">View-only Navigator</p>
        <h1>Backend connectivity check</h1>
        <p className="endpoint">API base: {apiBaseUrl}</p>
        <p className="endpoint">Requesting {locationsUrl}</p>
      </header>

      {state.status === 'loading' && (
        <p className="status notice">Loading location catalog…</p>
      )}

      {state.status === 'success' && (
        <section className="status success">
          <h2>Locations reachable</h2>
          <p className="summary">{state.locations} locations loaded</p>
        </section>
      )}

      {state.status === 'error' && (
        <section className="status error">
          <h2>Locations unreachable</h2>
          <p className="summary">{state.detail}</p>
        </section>
      )}
    </main>
  )
}
