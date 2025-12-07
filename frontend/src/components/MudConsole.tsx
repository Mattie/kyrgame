import {
  FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { ActivityEntry, useNavigator } from '../context/NavigatorContext'

const directionByKey: Record<string, 'north' | 'south' | 'east' | 'west'> = {
  w: 'north',
  a: 'west',
  s: 'south',
  d: 'east',
}

const formatPayload = (payload: ActivityEntry['payload']): string | null => {
  if (payload === undefined || payload === null) return null
  if (typeof payload === 'string') return payload
  if (typeof payload === 'number' || typeof payload === 'boolean') {
    return String(payload)
  }
  return JSON.stringify(payload)
}

type HudState = {
  hitpoints?: { current: number; max: number }
  spellPoints?: { current: number; max: number }
  description?: string
  inventory?: string[]
  effects?: string[]
  spellbook?: string[]
}

const extractHudFromEntry = (entry: { summary?: string; payload?: any }): HudState => {
  const updates: HudState = {}
  const payload = entry.payload ?? {}

  if (payload.hitpoints) {
    updates.hitpoints = payload.hitpoints
  }

  if (payload.spell_points || payload.spellPoints) {
    updates.spellPoints = payload.spell_points ?? payload.spellPoints
  }

  if (payload.spellbook) {
    updates.spellbook = payload.spellbook
  }

  if (payload.description) {
    updates.description = payload.description
  }

  if (payload.inventory) {
    updates.inventory = payload.inventory
  }

  if (payload.effects) {
    updates.effects = payload.effects
  }

  if (entry.summary) {
    const hpMatch = /hitpoints[:\s]+(\d+)\/(\d+)/i.exec(entry.summary)
    if (hpMatch) {
      updates.hitpoints = { current: Number(hpMatch[1]), max: Number(hpMatch[2]) }
    }
  }

  return updates
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
  const [hud, setHud] = useState<HudState>({})
  const [hudVisible, setHudVisible] = useState(false)
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

  useEffect(() => {
    const latest = activity[activity.length - 1]
    if (!latest) return
    const updates = extractHudFromEntry(latest)
    const hasUpdates = Object.keys(updates).length > 0
    if (hasUpdates) {
      setHud((prev) => ({ ...prev, ...updates }))
      setHudVisible(true)
    }
  }, [activity])

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    sendCommand(input)
    setInput('')
  }

  const compassLabel = navMode ? 'Navigation mode active' : 'Toggle navigation mode'

  const bannerLines = useMemo(() => {
    if (!session) {
      return ['Connect to begin exploring the world of Kyrandia.']
    }
    // Only show connection message, no room info or descriptions at top
    return [
      `Player ${session.playerId} connected.`,
      '',  // Empty line for spacing
    ]
  }, [session])

  return (
    <section className="mud-shell">
      <div className="mud-grid">
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
              {activity.map((entry) => (
                <p key={entry.id} className={`crt-line ${entry.type}`}>
                  {formatPayload(entry.payload) && (
                    <span className="prompt-symbol" aria-hidden>
                      &gt;
                    </span>
                  )}
                  <span className="prompt-symbol">&gt;</span> {entry.summary}
                  {formatPayload(entry.payload) && (
                    <span className="payload-inline">{formatPayload(entry.payload)}</span>
                  )}
                </p>
              ))}
              {occupants.length > 0 && (
                <p className="crt-line occupants">
                  <span className="prompt-symbol">*</span> Occupants: {occupants.join(', ')}
                </p>
              )}
            </div>
          </div>

          <form className="prompt-row" onSubmit={handleSubmit}>
            <button
              type="button"
              aria-label={compassLabel}
              className={`compass ${navMode ? 'active' : ''}`}
              onClick={() => setNavMode((prev) => !prev)}
            >
              ☼
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

        <aside className={`hud-panel ${hudVisible ? 'visible' : 'hidden'}`} aria-live="polite">
          <p className="eyebrow">Status</p>
          <h3>Character readout</h3>
          {hud.hitpoints && (
            <p className="hud-line">Hitpoints: {hud.hitpoints.current}/{hud.hitpoints.max}</p>
          )}
          {hud.spellPoints && (
            <p className="hud-line">
              Spell points: {hud.spellPoints.current}/{hud.spellPoints.max}
            </p>
          )}
          {hud.description && <p className="hud-line">{hud.description}</p>}
          {hud.inventory && hud.inventory.length > 0 && (
            <p className="hud-line">
              Inventory:{' '}
              {hud.inventory.map((item) => (
                <strong key={item}>{item}</strong>
              ))}
            </p>
          )}
          {hud.effects && hud.effects.length > 0 && (
            <p className="hud-line">Effects: {hud.effects.join(', ')}</p>
          )}
          {hud.spellbook && hud.spellbook.length > 0 && (
            <div className="hud-line">
              <p className="eyebrow">Spellbook</p>
              <ul>
                {hud.spellbook.map((spell) => (
                  <li key={spell}>{spell}</li>
                ))}
              </ul>
            </div>
          )}
          {!hudVisible && <p className="muted">Cast or inspect to pin stats here.</p>}
        </aside>
      </div>
    </section>
  )
}
