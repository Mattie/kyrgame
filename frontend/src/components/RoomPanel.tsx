import { useMemo } from 'react'

import { LocationRecord, useNavigator } from '../context/NavigatorContext'

const directionFields: Record<string, keyof LocationRecord> = {
  north: 'gi_north',
  south: 'gi_south',
  east: 'gi_east',
  west: 'gi_west',
}

const humanDirection: Record<string, string> = {
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
    if (!location) return [] as { direction: string; target: number }[]
    return Object.entries(directionFields)
      .map(([direction, field]) => ({ direction, target: location[field] ?? -1 }))
      .filter(({ target }) => typeof target === 'number' && target >= 0)
  }, [location])

  const groundObjects = useMemo(() => {
    if (!location || !world) return [] as string[]
    const objectNames = new Map(world.objects.map((obj) => [obj.id, obj.name]))
    return (location.objects ?? []).map((id) => objectNames.get(id) ?? `Object ${id}`)
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
        <div>
          <h3>Exits</h3>
          <div className="exits" data-testid="room-exits">
            {exits.length === 0 && <p className="muted">No exits</p>}
            {exits.map((exit) => (
              <button
                key={exit.direction}
                type="button"
                onClick={() => sendMove(exit.direction as keyof typeof directionFields)}
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
    </section>
  )
}
