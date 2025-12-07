import { useMemo } from 'react'

import { LocationRecord, useNavigator } from '../context/NavigatorContext'

type DirectionKey = 'north' | 'south' | 'east' | 'west'

const directionFields: Record<DirectionKey, keyof LocationRecord> = {
  north: 'gi_north',
  south: 'gi_south',
  east: 'gi_east',
  west: 'gi_west',
}

const humanDirection: Record<DirectionKey, string> = {
  north: 'North',
  south: 'South',
  east: 'East',
  west: 'West',
}

export const RoomPanel = () => {
  const { world, currentRoom, occupants, sendMove } = useNavigator()

  const location = useMemo(() => {
    if (!world || currentRoom === null) return null
    return world.locations.find((loc) => loc.id === currentRoom) ?? null
  }, [currentRoom, world])

  const exits = useMemo(() => {
    if (!location) return [] as { direction: DirectionKey; target: number }[]
    return (Object.entries(directionFields) as [DirectionKey, keyof LocationRecord][])
      .map(([direction, field]) => ({ direction, target: location[field] ?? -1 }))
      .filter(({ target }) => typeof target === 'number' && target >= 0)
  }, [location])

  const groundObjects = useMemo(() => {
    if (!location || !world) return [] as string[]
    const objectNames = new Map(world.objects.map((obj) => [obj.id, obj.name]))
    return (location.objects ?? []).map((id) => objectNames.get(id) ?? `Object ${id}`)
  }, [location, world])

  const availableCommands = useMemo(() => {
    if (!world) return [] as string[]
    const verbs = (world.commands ?? [])
      .map((cmd) => cmd.command ?? cmd.verb)
      .filter((verb): verb is string => Boolean(verb))
    return Array.from(new Set(verbs))
  }, [world])

  const lookDescription = useMemo(() => {
    if (!world || !location) return null
    const baseKey = (() => {
      if (location.londes !== undefined) {
        const raw = String(location.londes)
        if (raw.startsWith('KRD')) return raw
        return `KRD${raw.padStart(3, '0')}`
      }
      return `KRD${String(location.id).padStart(3, '0')}`
    })()
    return world.messages?.[baseKey] ?? null
  }, [location, world])

  if (!location) {
    return (
      <section className="panel room-panel">
        <header>
          <p className="eyebrow">Room</p>
          <h2>Awaiting room data…</h2>
        </header>
      </section>
    )
  }

  return (
    <section className="panel room-panel">
      <header>
        <p className="eyebrow">Room</p>
        <h2>{location.brfdes}</h2>
        <p className="muted">Room {location.id}</p>
        {location.objlds && <p className="muted">{location.objlds}</p>}
      </header>

      <div className="room-body">
        <div className="room-grid">
          <div>
            <h3>Look description</h3>
            <p className="muted" data-testid="room-look-description">
              {lookDescription ?? 'No description available'}
            </p>
          </div>

          <div>
            <h3>Available commands</h3>
            <div data-testid="room-commands" className="command-list">
              {availableCommands.length === 0 && (
                <p className="muted">No commands loaded</p>
              )}
              {availableCommands.length > 0 && (
                <ul>
                  {availableCommands.map((verb) => (
                    <li key={verb}>{verb}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>

        <div className="room-grid">
          <div>
            <h3>Exits</h3>
            <div className="exits" data-testid="room-exits">
              {exits.length === 0 && <p className="muted">No exits</p>}
              {exits.map((exit) => (
                <button
                  key={exit.direction}
                  type="button"
                  onClick={() => sendMove(exit.direction)}
                >
                  {humanDirection[exit.direction]}
                </button>
              ))}
            </div>
          </div>

          <div>
            <h3>Ground objects</h3>
            {groundObjects.length === 0 && <p className="muted">None</p>}
            {groundObjects.length > 0 && (
              <ul>
                {groundObjects.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3>Occupants</h3>
            {occupants.length === 0 && <p className="muted">No one here</p>}
            {occupants.length > 0 && (
              <ul>
                {occupants.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
