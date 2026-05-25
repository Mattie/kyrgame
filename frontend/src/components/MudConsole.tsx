import {
  FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import {
  ActivityEntry,
  formatLegacyRoomObjectLines,
  useNavigator,
} from '../context/NavigatorContext'
import { AnsiText } from './AnsiText'

const normalizeName = (name?: string | null) => (name ?? '').trim().toLowerCase()

const formatLegacyRoomLines = (
  entry: ActivityEntry,
  world: ReturnType<typeof useNavigator>['world'],
  defaultRoom: number | null,
  occupants: string[],
  playerId: string | null
): string[] => {
  if (!world) return []
  if (!entry.payload || typeof entry.payload !== 'object') return []
  if ((entry.payload as Record<string, unknown>).event !== 'location_description') return []

  const locationId =
    (entry.payload as Record<string, number | null | undefined>).location ?? defaultRoom
  const location = world.locations.find((loc) => loc.id === locationId)
  if (!location) return []

  const lines = formatLegacyRoomObjectLines(location, world.objects, world.messages)

  const current = normalizeName(playerId)
  const others = occupants
    .map((name) => ({ raw: name, normalized: normalizeName(name) }))
    .filter((entry) => entry.normalized && entry.normalized !== current)
    .map((entry) => entry.raw)
  // Mirrors locogps formatting from legacy/KYRUTIL.C lines 332-402 for players in the room.
  if (others.length === 1) {
    lines.push(`${others[0]} is here.`)
  } else if (others.length === 2) {
    lines.push(`${others[0]} and ${others[1]} are here.`)
  } else if (others.length > 2) {
    const [last, ...rest] = others.reverse()
    lines.push(`${rest.reverse().join(', ')}, and ${last} are here.`)
  }

  return lines
}

const directionByKey: Record<string, 'north' | 'south' | 'east' | 'west'> = {
  w: 'north',
  a: 'west',
  s: 'south',
  d: 'east',
}

const formatPayload = (payload: ActivityEntry['payload']): string | null => {
  if (payload === undefined || payload === null) return null
  if (typeof payload === 'object' && 'event' in payload) {
    return null
  }

  if (typeof payload === 'string') return payload
  if (typeof payload === 'number' || typeof payload === 'boolean') {
    return String(payload)
  }
  return null
}

export const MudConsole = () => {
  const {
    activity,
    connectionStatus,
    currentRoom,
    occupants,
    sendCommand,
    sendMove,
    session,
    world,
  } = useNavigator()
  const [input, setInput] = useState('')
  const [navMode, setNavMode] = useState(false)
  const logRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const location = useMemo(() => {
    if (!world || currentRoom === null) return null
    return world.locations.find((loc) => loc.id === currentRoom) ?? null
  }, [currentRoom, world])

  useEffect(() => {
    const node = logRef.current
    if (!node) return
    if (typeof node.scrollTo === 'function') {
      node.scrollTo({ top: node.scrollHeight })
    } else {
      node.scrollTop = node.scrollHeight
    }
  }, [activity])

  useEffect(() => {
    if (!navMode) return

    const handleKeydown = (event: KeyboardEvent) => {
      const direction = directionByKey[event.key.toLowerCase()]
      if (!direction) return
      event.preventDefault()
      sendMove(direction)
    }

    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  }, [navMode, sendMove])

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const command = input.trim()
    if (!command) return

    sendCommand(command)
    setInput('')
  }

  const compassLabel = navMode ? 'Navigation mode active' : 'Toggle navigation mode'

  const bannerLines = useMemo(() => {
    if (!session) {
      return ['Connect to begin exploring the world of Kyrandia.']
    }
    return [`Player ${session.playerId} connected.`, '']
  }, [session])

  const hasLocationDescription = useMemo(
    () =>
      activity.some((entry) => {
        if (!entry.payload || typeof entry.payload !== 'object') return false
        return (entry.payload as Record<string, unknown>).event === 'location_description'
      }),
    [activity]
  )

  const initialDescriptionEntry: ActivityEntry | null = useMemo(() => {
    if (!location || !world) return null
    if (hasLocationDescription) return null

    const messageId =
      typeof location.londes === 'string' || typeof location.londes === 'number'
        ? String(location.londes)
        : null
    const description = (messageId && world.messages?.[messageId]) || location.brfdes

    const payload = { event: 'location_description', location: location.id }
    const entry: ActivityEntry = {
      id: 'initial-room-description',
      type: 'command_response',
      summary: description ?? location.brfdes,
      payload,
    }

    entry.extraLines = formatLegacyRoomLines(
      entry,
      world,
      location.id,
      occupants,
      session?.playerId ?? null
    )

    return entry
  }, [hasLocationDescription, location, occupants, session?.playerId, world])

  const entriesToRender = useMemo(
    () => (initialDescriptionEntry ? [initialDescriptionEntry, ...activity] : activity),
    [activity, initialDescriptionEntry]
  )

  const visibleEntries = useMemo(
    () => entriesToRender.filter((entry) => !entry.hidden),
    [entriesToRender]
  )

  return (
    <section className="mud-shell">
      <div className="mud-grid" data-testid="mud-grid">
        <div className="mud-window">
          <header className="mud-header">
            <div>
              <p className="eyebrow">Kyrandia Line Interface</p>
              <h2 aria-hidden>{location?.brfdes ?? 'Awaiting world data'}</h2>
              <p className="muted">{session ? `Player ${session.playerId}` : 'No session yet'}</p>
            </div>
            <div className={`connection-pill ${connectionStatus}`}>
              {connectionStatus}
            </div>
          </header>

          <div className="crt" ref={logRef} aria-live="polite">
            <div className="crt-glow" />
            <div className="crt-lines">
              {bannerLines.map((line, index) => (
                <p key={line + index} className="crt-line muted">
                  {line}
                </p>
              ))}
              {visibleEntries.map((entry) => {
                const payloadText = formatPayload(entry.payload)
                const legacyLines =
                  entry.extraLines ??
                  formatLegacyRoomLines(
                    entry,
                    world,
                    currentRoom,
                    occupants,
                    session?.playerId ?? null
                  )

                const isUserCommand =
                  entry.type === 'command_response' &&
                  typeof entry.payload === 'object' &&
                  entry.payload !== null &&
                  'verb' in entry.payload &&
                  !('event' in entry.payload)

                const isUnimplemented =
                  entry.type === 'command_response' &&
                  typeof entry.payload === 'object' &&
                  entry.payload !== null &&
                  'event' in entry.payload &&
                  entry.payload.event === 'unimplemented'

                return (
                  <div key={entry.id} className="crt-entry">
                    <p
                      className={`crt-line ${entry.type}`}
                      style={isUnimplemented ? { fontStyle: 'italic' } : undefined}
                    >
                      {isUserCommand && (
                        <span className="prompt-symbol" aria-hidden>
                          &gt;
                        </span>
                      )}
                      <AnsiText text={entry.summary} />
                      {payloadText && <span className="payload-inline">{payloadText}</span>}
                    </p>
                    {legacyLines?.map((line, index) => (
                      <p key={`${entry.id}-extra-${index}`} className={`crt-line ${entry.type} detail`}>
                        <AnsiText text={line} />
                      </p>
                    ))}
                  </div>
                )
              })}
            </div>
          </div>

          <form className="prompt-row" onSubmit={handleSubmit}>
            <button
              type="button"
              aria-label={compassLabel}
              className={`compass ${navMode ? 'active' : ''}`}
              onClick={() => setNavMode((prev) => !prev)}
            >
              *
            </button>
            <div className={`prompt-field ${navMode ? 'nav-active' : ''}`}>
              <span className="prompt-symbol">{navMode ? 'NAV>' : '>'}</span>
              <input
                ref={inputRef}
                aria-label="command input"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onFocus={() => setNavMode(false)}
                placeholder="Type commands like LOOK, SAY HELLO, or INVENTORY"
              />
            </div>
            <button type="submit" className="send-button">
              Send
            </button>
          </form>
          <p className="mode-hint">
            {navMode
              ? 'Navigation mode: WASD sends movement (click the prompt to exit).'
              : 'Enter a command to interact. Click the compass for WASD navigation.'}
          </p>
        </div>
      </div>
    </section>
  )
}
