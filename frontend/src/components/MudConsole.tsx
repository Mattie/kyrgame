import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { ActivityEntry, useNavigator } from '../context/NavigatorContext'
import { GemstoneText } from './GemstoneText'

const articleizedName = (object?: { name: string; flags?: string[] }) => {
  if (!object) return 'an object'
  const needsAn = object.flags?.includes('NEEDAN')
  const article = needsAn ? 'an' : 'a'
  // Return plain name - GemstoneText will add emoji and color when rendering
  return `${article} ${object.name}`
}

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

  const visibleNames = (location.objects ?? [])
    .map((id) => world.objects.find((obj) => obj.id === id))
    .filter((obj): obj is { id: number; name: string; flags?: string[] } =>
      Boolean(obj && (!obj.flags || obj.flags.includes('VISIBL')))
    )
    .map((obj) => articleizedName(obj))

  const landing = location.objlds ?? 'here'
  const lines: string[] = []

  // Mirrors locobjs formatting from legacy/KYRUTIL.C for ground objects.【F:legacy/KYRUTIL.C†L256-L311】
  switch (visibleNames.length) {
    case 0:
      lines.push(`There is nothing lying ${landing}.`)
      break
    case 1:
      lines.push(`There is ${visibleNames[0]} lying ${landing}.`)
      break
    case 2:
      lines.push(`There is ${visibleNames[0]} and ${visibleNames[1]} lying ${landing}.`)
      break
    default: {
      const [last, ...rest] = visibleNames.reverse()
      lines.push(`There is ${rest.reverse().join(', ')}, and ${last} lying ${landing}.`)
      break
    }
  }

  const current = normalizeName(playerId)
  const others = occupants
    .map((name) => ({ raw: name, normalized: normalizeName(name) }))
    .filter((entry) => entry.normalized && entry.normalized !== current)
    .map((entry) => entry.raw)
  // Mirrors locogps formatting from legacy/KYRUTIL.C for players in the room.【F:legacy/KYRUTIL.C†L332-L402】
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
    if ((payload as Record<string, unknown>).event === 'location_description') {
      return null
    }
    return null
  }

  if (typeof payload === 'string') return payload
  if (typeof payload === 'number' || typeof payload === 'boolean') {
    return String(payload)
  }
  return null
}

type HudState = {
  hitpoints?: { current: number; max: number }
  spellPoints?: { current: number; max: number }
  description?: string
  inventory?: string[]
  effects?: string[]
  spellbook?: string[]
}

type StatusCardId = 'hitpoints' | 'inventory' | 'spellbook' | 'description' | 'effects'

type StatusCardState = {
  id: StatusCardId
  title: string
  command: string
  autoRefresh: boolean
  active: boolean
  lastSummary?: string
}

const STATUS_CARD_CONFIG: Record<StatusCardId, { title: string; command: string }> = {
  hitpoints: { title: 'Hitpoints', command: 'hitpoints' },
  inventory: { title: 'inventory', command: 'inv' },
  spellbook: { title: 'Spellbook', command: 'spellbook' },
  description: { title: 'Description', command: 'describe' },
  effects: { title: 'Effects', command: 'effects' },
}

const STATUS_CARD_ORDER: StatusCardId[] = [
  'hitpoints',
  'inventory',
  'spellbook',
  'effects',
  'description',
]

const createDefaultStatusCards = (): Record<StatusCardId, StatusCardState> =>
  (Object.keys(STATUS_CARD_CONFIG) as StatusCardId[]).reduce(
    (acc, id) => {
      acc[id] = {
        id,
        title: STATUS_CARD_CONFIG[id].title,
        command: STATUS_CARD_CONFIG[id].command,
        autoRefresh: true,
        active: false,
      }
      return acc
    },
    {} as Record<StatusCardId, StatusCardState>
  )

const normalizeInventoryFromPayload = (payload: any): string[] | undefined => {
  if (!payload) return undefined
  if (Array.isArray(payload.inventory)) return payload.inventory

  const payloadItems = Array.isArray(payload.items) ? payload.items : []
  const inventoryList = payloadItems
    .map((item: any) => {
      const name = item?.display_name ?? item?.name
      return name || null
    })
    .filter(Boolean)

  return inventoryList.length > 0 ? (inventoryList as string[]) : undefined
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

  const payloadEvent = typeof payload.event === 'string' ? payload.event : ''

  if (payload.description) {
    updates.description = payload.description
  } else if (payloadEvent === 'description') {
    updates.description = payload.description ?? payload.text
  }

  const inventoryList = normalizeInventoryFromPayload(payload)
  if (inventoryList) {
    updates.inventory = inventoryList
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
  const [statusCards, setStatusCards] = useState<Record<StatusCardId, StatusCardState>>(
    () => createDefaultStatusCards()
  )
  const logRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const processedActivityRef = useRef(0)
  const defaultStatusCardsRef = useRef(createDefaultStatusCards())

  const hudVisible = useMemo(
    () => Object.values(statusCards).some((card) => card.active),
    [statusCards]
  )

  const activeStatusCards = useMemo(
    () =>
      STATUS_CARD_ORDER
        .map((id) => statusCards[id])
        .filter((card): card is StatusCardState => Boolean(card && card.active)),
    [statusCards]
  )

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
    const newEntries = activity.slice(processedActivityRef.current)
    if (newEntries.length === 0) return

    newEntries.forEach((entry) => {
      const updates = extractHudFromEntry(entry)
      const hasUpdates = Object.keys(updates).length > 0
      if (hasUpdates) {
        setHud((prev) => ({ ...prev, ...updates }))
      }

      const payload = entry.payload ?? {}
      const payloadRecord = typeof payload === 'object' && payload !== null ? (payload as Record<string, unknown>) : {}
      const candidateCards: StatusCardId[] = []
      if (updates.hitpoints || updates.spellPoints || payloadRecord.event === 'hitpoints') {
        candidateCards.push('hitpoints')
      }
      if (updates.inventory || payloadRecord.event === 'inventory') {
        candidateCards.push('inventory')
      }
      if (updates.spellbook || payloadRecord.event === 'spellbook') {
        candidateCards.push('spellbook')
      }
      if (updates.description || payloadRecord.event === 'description') {
        candidateCards.push('description')
      }
      if (updates.effects || payloadRecord.event === 'effects') {
        candidateCards.push('effects')
      }

      if (candidateCards.length > 0) {
        setStatusCards((prev) => {
          const next = { ...prev }
          candidateCards.forEach((id) => {
            const base = next[id] ?? { ...defaultStatusCardsRef.current[id] }
            const commandFromPayload =
              (typeof payloadRecord?.verb === 'string' && payloadRecord.verb.trim()) ||
              (typeof payloadRecord?.command === 'string' && payloadRecord.command.trim()) ||
              base.command

            next[id] = {
              ...base,
              command: commandFromPayload,
              autoRefresh: base.autoRefresh,
              active: true,
              lastSummary:
                entry.summary ??
                (typeof payloadRecord?.text === 'string' ? payloadRecord.text : undefined) ??
                base.lastSummary,
            }
          })
          return next
        })
      }
    })

    processedActivityRef.current = activity.length
  }, [activity])

  const renderCardContent = (card: StatusCardState) => {
    switch (card.id) {
      case 'hitpoints':
        return (
          <>
            {hud.hitpoints && (
              <p className="hud-line">Hitpoints: {hud.hitpoints.current}/{hud.hitpoints.max}</p>
            )}
            {hud.spellPoints && (
              <p className="hud-line">
                Spell points: {hud.spellPoints.current}/{hud.spellPoints.max}
              </p>
            )}
            {!hud.hitpoints && !hud.spellPoints && (
              <p className="muted">Use HITPOINTS to pin your vitals.</p>
            )}
          </>
        )
      case 'inventory':
        return card.lastSummary ? (
          <p className="hud-line">
            <GemstoneText text={card.lastSummary} />
          </p>
        ) : hud.inventory && hud.inventory.length > 0 ? (
          <p className="hud-line">
            <GemstoneText text={`You have ${hud.inventory.join(', ')}.`} />
          </p>
        ) : (
          <p className="muted">Type INV to inspect your pack.</p>
        )
      case 'spellbook':
        return hud.spellbook && hud.spellbook.length > 0 ? (
          <div className="hud-line">
            <p className="eyebrow">Spellbook</p>
            <ul>
              {hud.spellbook.map((spell) => (
                <li key={spell}>{spell}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="muted">Cast or study spells to refresh your book.</p>
        )
      case 'description':
        return (
          <p className="hud-line">
            <GemstoneText
              text={
                hud.description ??
                card.lastSummary ??
                'Look or DESCRIBE yourself to populate this panel.'
              }
            />
          </p>
        )
      case 'effects':
        return hud.effects && hud.effects.length > 0 ? (
          <p className="hud-line">Effects: {hud.effects.join(', ')}</p>
        ) : (
          <p className="muted">Active buffs and curses will appear here.</p>
        )
      default:
        return null
    }
  }

  const toggleAutoRefresh = useCallback((id: StatusCardId) => {
    setStatusCards((prev) => {
      const base = prev[id] ?? { ...defaultStatusCardsRef.current[id] }
      return { ...prev, [id]: { ...base, autoRefresh: !base.autoRefresh } }
    })
  }, [])

  const requestStatusRefresh = useCallback(() => {
    if (connectionStatus !== 'connected') return
    activeStatusCards
      .filter((card) => card.autoRefresh)
      .forEach((card) =>
        sendCommand(card.command, {
          silent: true,
          skipLog: true,
          meta: { status_card: card.id },
        })
      )
  }, [activeStatusCards, connectionStatus, sendCommand])

  useEffect(() => {
    if (connectionStatus !== 'connected') return
    if (!activeStatusCards.some((card) => card.autoRefresh)) return

    const interval = window.setInterval(() => {
      requestStatusRefresh()
    }, 5000)

    return () => window.clearInterval(interval)
  }, [activeStatusCards, connectionStatus, requestStatusRefresh])

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    sendCommand(input)
    requestStatusRefresh()
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
              {visibleEntries.map((entry) => {
                const payloadText = formatPayload(entry.payload)
                const legacyLines =
                  entry.extraLines ??
                  formatLegacyRoomLines(entry, world, currentRoom, occupants, session?.playerId ?? null)
                
                // Only show > for user-initiated commands (command acknowledgments with verb)
                const isUserCommand = entry.type === 'command_response' && 
                  typeof entry.payload === 'object' && 
                  entry.payload !== null &&
                  'verb' in entry.payload &&
                  !('event' in entry.payload)
                
                // Check if this is an unimplemented command
                const isUnimplemented = entry.type === 'command_response' &&
                  typeof entry.payload === 'object' &&
                  entry.payload !== null &&
                  'event' in entry.payload &&
                  entry.payload.event === 'unimplemented'
                
                return (
                  <div key={entry.id} className="crt-entry">
                    <p className={`crt-line ${entry.type}`} style={isUnimplemented ? { fontStyle: 'italic' } : undefined}>
                      {isUserCommand && (
                        <span className="prompt-symbol" aria-hidden>
                          &gt;
                        </span>
                      )}
                      <GemstoneText text={entry.summary} />
                      {payloadText && <span className="payload-inline">{payloadText}</span>}
                    </p>
                    {legacyLines?.map((line, index) => (
                      <p key={`${entry.id}-extra-${index}`} className={`crt-line ${entry.type} detail`}>
                        <GemstoneText text={line} />
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
          <div className="hud-heading">
            <p className="eyebrow">Status</p>
            <h3>Character readout</h3>
          </div>
          {activeStatusCards.map((card) => (
            <div key={card.id} className="hud-card">
              <div className="hud-card-header">
                <span className="hud-card-title">{card.title}</span>
                <label className="refresh-toggle" title="Auto-refresh">
                  <input
                    type="checkbox"
                    checked={card.autoRefresh}
                    onChange={() => toggleAutoRefresh(card.id)}
                    aria-label={`Enable auto-refresh for ${card.title}`}
                  />
                  <span role="img" aria-hidden>
                    ♻️
                  </span>
                </label>
              </div>
              <div className="hud-card-body">{renderCardContent(card)}</div>
            </div>
          ))}
          {!hudVisible && <p className="muted">Cast or inspect to pin stats here.</p>}
        </aside>
      </div>
    </section>
  )
}
