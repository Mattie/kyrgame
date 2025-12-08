import {
  PropsWithChildren,
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react'

import { getApiBaseUrl, getWebSocketUrl } from '../config/endpoints'

export type LocationRecord = {
  id: number
  brfdes: string
  objlds?: string
  objects?: number[]
  londes?: number | string
  gi_north?: number
  gi_south?: number
  gi_east?: number
  gi_west?: number
}

export type GameObject = {
  id: number
  name: string
  flags?: string[]
}

export type CommandRecord = {
  id?: number
  verb?: string
  command?: string
}

export type SessionRecord = {
  token: string
  playerId: string
  roomId: number
}

export type WorldData = {
  locations: LocationRecord[]
  objects: GameObject[]
  commands: CommandRecord[]
  messages: Record<string, string>
}

export type ActivityEntry = {
  id: string
  type: string
  room?: number
  summary: string
  payload?: Record<string, unknown> | string | number | boolean | null
  extraLines?: string[]
}

type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'

type NavigatorContextValue = {
  apiBaseUrl: string
  session: SessionRecord | null
  world: WorldData | null
  currentRoom: number | null
  occupants: string[]
  activity: ActivityEntry[]
  connectionStatus: ConnectionStatus
  error: string | null
  startSession: (playerId: string, roomId?: number | null) => Promise<void>
  sendMove: (direction: 'north' | 'south' | 'east' | 'west') => void
  sendCommand: (command: string) => void
}

const NavigatorContext = createContext<NavigatorContextValue | undefined>(undefined)

const createActivityId = (() => {
  let counter = 0
  return () => {
    counter += 1
    return `${Date.now()}-${counter}`
  }
})()

const articleizedName = (object: GameObject | undefined): string => {
  if (!object) return 'an object'
  const needsAn = object.flags?.includes('NEEDAN')
  const article = needsAn ? 'an' : 'a'
  // Return plain name - GemstoneText will add emoji and color when rendering
  return `${article} ${object.name}`
}

const normalizePlayerName = (name?: string | null) => (name ?? '').trim().toLowerCase()

const formatRoomObjectsLine = (
  location: LocationRecord | null,
  objects: GameObject[] | null
): string | null => {
  if (!location) return null
  const objectsById = new Map(objects?.map((obj) => [obj.id, obj]) ?? [])
  const visibleNames = (location.objects ?? [])
    .map((id) => objectsById.get(id))
    .filter((obj) => !obj || !obj.flags || obj.flags.includes('VISIBL'))
    .map((obj) => articleizedName(obj))

  const landing = location.objlds ?? 'here'

  // Mirrors locobjs formatting from legacy/KYRUTIL.C for ground objects.【F:legacy/KYRUTIL.C†L256-L311】
  switch (visibleNames.length) {
    case 0:
      return `There is nothing lying ${landing}.`
    case 1:
      return `There is ${visibleNames[0]} lying ${landing}.`
    case 2:
      return `There is ${visibleNames[0]} and ${visibleNames[1]} lying ${landing}.`
    default: {
      const [last, ...rest] = visibleNames.reverse()
      return `There is ${rest.reverse().join(', ')}, and ${last} lying ${landing}.`
    }
  }
}

const formatOccupantsLine = (players: string[], currentPlayerId?: string | null): string | null => {
  const current = normalizePlayerName(currentPlayerId)
  const others = players
    .map((name) => ({ raw: name, normalized: normalizePlayerName(name) }))
    .filter((entry) => entry.normalized && entry.normalized !== current)
    .map((entry) => entry.raw)
  if (others.length === 0) return null

  // Mirrors locogps formatting from legacy/KYRUTIL.C for players in the room.【F:legacy/KYRUTIL.C†L332-L402】
  if (others.length === 1) {
    return `${others[0]} is here.`
  }

  if (others.length === 2) {
    return `${others[0]} and ${others[1]} are here.`
  }

  const [last, ...rest] = others.reverse()
  return `${rest.reverse().join(', ')}, and ${last} are here.`
}

export const NavigatorProvider = ({ children }: PropsWithChildren) => {
  const apiBaseUrl = useMemo(() => getApiBaseUrl(), [])
  const wsBaseUrl = useMemo(() => getWebSocketUrl(), [])
  const [session, setSession] = useState<SessionRecord | null>(null)
  const [world, setWorld] = useState<WorldData | null>(null)
  const [activity, setActivity] = useState<ActivityEntry[]>([])
  const [currentRoom, setCurrentRoom] = useState<number | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [occupants, setOccupants] = useState<string[]>([])
  const socketRef = useRef<WebSocket | null>(null)
  const worldRef = useRef<WorldData | null>(null)
  const occupantsRef = useRef<string[]>([])

  const resetSocket = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.close()
      socketRef.current = null
    }
  }, [])

  const appendActivity = useCallback((entry: Omit<ActivityEntry, 'id'>) => {
    setActivity((prev) => [...prev, { ...entry, id: createActivityId() }])
  }, [])

  const updateOccupants = useCallback((players: string[]) => {
    const unique = Array.from(new Set(players))
    occupantsRef.current = unique
    setOccupants(unique)
  }, [])

  const handleRoomChange = useCallback(
    (roomId: number | null, _origin: string) => {
      if (roomId !== null) {
        setCurrentRoom(roomId)
        // Don't append activity here - let the specific event handlers decide what to show
      }
      // Reset occupants to empty - the current player should never be in the occupants list
      // matching legacy behavior from KYRUTIL.C locogps() which excludes current player
      updateOccupants([])
    },
    [updateOccupants]
  )

  const handleIncoming = useCallback(
    (message: any) => {
      if (!message || typeof message !== 'object') return
      switch (message.type) {
        case 'room_welcome':
        case 'room_change': {
          handleRoomChange(message.room ?? null, message.type)
          break
        }
        case 'room_broadcast': {
          const summary = message.payload?.event ?? 'room_broadcast'
          appendActivity({
            type: 'room_broadcast',
            room: message.room,
            summary,
            payload: message.payload,
          })
          if (message.payload?.event === 'player_enter' && message.payload.player) {
            const enteringPlayer = message.payload.player
            // Don't add current player to occupants list (matches legacy KYRUTIL.C behavior)
            if (normalizePlayerName(enteringPlayer) !== normalizePlayerName(session?.playerId)) {
              setOccupants((current) => {
                const next = Array.from(new Set([...(current || []), enteringPlayer]))
                occupantsRef.current = next
                return next
              })
            }
          }
          break
        }
        case 'command_response': {
          let summary = message.payload?.event ?? message.payload?.verb ?? 'command_response'
          let payload = message.payload
          let extraLines: string[] | undefined

          if (message.payload?.event === 'location_description') {
            // Look up the full description from world.messages using message_id, just like RoomPanel does
            let text = message.payload?.text ?? message.payload?.description
            const locationId =
              message.payload?.location ?? currentRoom ?? session?.roomId ?? null

            // Use worldRef for immediate access to loaded data (avoids race condition on first load)
            if (message.payload?.message_id && worldRef.current?.messages) {
              const fullDescription = worldRef.current.messages[message.payload.message_id]
              if (fullDescription) {
                text = fullDescription
              }
            }

            summary = text ?? 'You look around.'
            payload = { event: 'location_description', location: locationId, text }

            const locationRecord =
              locationId !== null
                ? worldRef.current?.locations.find((loc) => loc.id === locationId) ?? null
                : null
            const objectLine = formatRoomObjectsLine(locationRecord, worldRef.current?.objects ?? null)
            const occupantsLine = formatOccupantsLine(
              occupantsRef.current,
              session?.playerId ?? null
            )
            extraLines = [objectLine, occupantsLine].filter(Boolean) as string[]
          } else if (message.payload?.event === 'location_update') {
            // Don't show location_update event separately - it will be followed by location_description
            handleRoomChange(message.payload.location ?? null, 'location_update')
            break // Skip adding this event to activity
          } else if (message.payload?.verb === 'move') {
            // Don't show move acknowledgment - just skip it
            break
          } else if (message.payload?.event === 'inventory') {
            const payloadItems = Array.isArray(message.payload?.items)
              ? message.payload.items
              : []
            const inventoryList =
              message.payload?.inventory ??
              payloadItems
                .map((item: any) => {
                  const name = item?.display_name ?? item?.name
                  // Return plain name - GemstoneText will add emoji and color when rendering
                  return name || null
                })
                .filter(Boolean)
            const inventoryText = message.payload?.text ?? summary

            summary = inventoryText
            payload = { ...message.payload, inventory: inventoryList, text: inventoryText }
          }
          
          appendActivity({
            type: 'command_response',
            room: message.room,
            summary,
            payload,
            extraLines,
          })
          break
        }
        case 'command_error': {
          appendActivity({
            type: 'command_error',
            room: message.room,
            summary: message.payload?.detail ?? 'command_error',
            payload: message.payload,
          })
          break
        }
        default:
          break
      }
    },
    [appendActivity, currentRoom, handleRoomChange, session?.playerId, updateOccupants]
  )

  const connectWebSocket = useCallback(
    (token: string, roomId: number) => {
      resetSocket()
      setConnectionStatus('connecting')
      const socket = new WebSocket(`${wsBaseUrl}/rooms/${roomId}?token=${token}`)
      socketRef.current = socket

      socket.onopen = () => {
        setConnectionStatus('connected')
      }

      socket.onclose = () => {
        setConnectionStatus('disconnected')
      }

      socket.onerror = () => {
        setConnectionStatus('error')
      }

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          handleIncoming(data)
        } catch (err) {
          appendActivity({
            type: 'parse_error',
            summary: err instanceof Error ? err.message : 'Invalid message',
          })
        }
      }
    },
    [appendActivity, handleIncoming, resetSocket, wsBaseUrl]
  )

  const fetchJson = useCallback(async (url: string, init?: RequestInit) => {
    const response = await fetch(url, init)
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(detail || `Request failed: ${response.status}`)
    }
    return response.json()
  }, [])

  const loadWorldData = useCallback(async () => {
    const locale = 'en-US'
    const [locations, objects, commands, messages] = await Promise.all([
      fetchJson(`${apiBaseUrl}/world/locations`),
      fetchJson(`${apiBaseUrl}/objects`),
      fetchJson(`${apiBaseUrl}/commands`),
      fetchJson(`${apiBaseUrl}/i18n/${locale}/messages`),
    ])
    const worldData: WorldData = {
      locations,
      objects,
      commands,
      messages: messages?.messages ?? {},
    }
    worldRef.current = worldData  // Store in ref for immediate access
    setWorld(worldData)
    return worldData
  }, [apiBaseUrl, fetchJson])

  const startSession = useCallback(
    async (playerId: string, roomId?: number | null) => {
      setConnectionStatus('connecting')
      setError(null)
      setActivity([])
      resetSocket()
      try {
        const payload: Record<string, string | number | boolean | null | undefined> = {
          player_id: playerId,
        }
        if (roomId !== undefined && roomId !== null && !Number.isNaN(roomId)) {
          payload.room_id = roomId
        }
        const response = await fetch(`${apiBaseUrl}/auth/session`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!response.ok) {
          const detail = await response.text()
          throw new Error(detail || 'Unable to start session')
        }
        const data = await response.json()
        const sessionPayload = data.session
        const record: SessionRecord = {
          token: sessionPayload.token,
          playerId: sessionPayload.player_id,
          roomId: sessionPayload.room_id,
        }
        setSession(record)
        setCurrentRoom(record.roomId)
        updateOccupants([record.playerId])
        // Load world data first and wait for it to complete before connecting WebSocket
        // worldRef.current is set immediately by loadWorldData, so messages will be available
        await loadWorldData()
        connectWebSocket(record.token, record.roomId)
      } catch (err) {
        setConnectionStatus('error')
        setError(err instanceof Error ? err.message : 'Unknown error')
        throw err
      }
    },
    [apiBaseUrl, connectWebSocket, loadWorldData, resetSocket, updateOccupants]
  )

  const sendMove = useCallback(
    (direction: 'north' | 'south' | 'east' | 'west') => {
      if (!socketRef.current) {
        appendActivity({
          type: 'command_error',
          summary: 'WebSocket not connected',
        })
        return
      }
      socketRef.current.send(
        JSON.stringify({ type: 'command', command: 'move', args: { direction } })
      )
    },
    [appendActivity]
  )

  const sendCommand = useCallback(
    (command: string) => {
      const trimmed = command.trim()
      if (trimmed === '') return
      if (!socketRef.current) {
        appendActivity({
          type: 'command_error',
          summary: 'WebSocket not connected',
        })
        return
      }

      appendActivity({ type: 'command', summary: `> ${trimmed}` })
      socketRef.current.send(
        JSON.stringify({ type: 'command', command: trimmed, args: { input: trimmed } })
      )
    },
    [appendActivity]
  )

  const value = useMemo(
    () => ({
      apiBaseUrl,
      session,
      world,
      currentRoom,
      occupants,
      activity,
      connectionStatus,
      error,
      startSession,
      sendMove,
      sendCommand,
    }),
    [
      activity,
      apiBaseUrl,
      connectionStatus,
      currentRoom,
      error,
      occupants,
      sendMove,
      sendCommand,
      session,
      startSession,
      world,
    ]
  )

  return <NavigatorContext.Provider value={value}>{children}</NavigatorContext.Provider>
}

export const useNavigator = () => {
  const context = useContext(NavigatorContext)
  if (!context) {
    throw new Error('useNavigator must be used within a NavigatorProvider')
  }
  return context
}
