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
    setOccupants(unique)
  }, [])

  const handleRoomChange = useCallback(
    (roomId: number | null, origin: string) => {
      if (roomId !== null) {
        setCurrentRoom(roomId)
        // Don't append activity here - let the specific event handlers decide what to show
      }
      if (session?.playerId) {
        updateOccupants([session.playerId])
      }
    },
    [session?.playerId, updateOccupants]
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
            setOccupants((current) =>
              Array.from(new Set([...(current || []), message.payload.player]))
            )
          }
          break
        }
        case 'command_response': {
          let summary = message.payload?.event ?? message.payload?.verb ?? 'command_response'
          let payload = message.payload
          
          // Format movement events to match legacy client behavior
          // Legacy shows: "...{full_description}\nThere is a {object} lying on the {objlds}."
          if (message.payload?.event === 'location_description') {
            // Look up the full description from world.messages using message_id, just like RoomPanel does
            let text = message.payload?.text ?? message.payload?.description
            
            // Use worldRef for immediate access to loaded data (avoids race condition on first load)
            if (message.payload?.message_id && worldRef.current?.messages) {
              const fullDescription = worldRef.current.messages[message.payload.message_id]
              if (fullDescription) {
                text = fullDescription
              }
            }
            
            if (text) {
              // Match legacy format: "...{description}"
              summary = `...${text}`
            } else {
              summary = 'You look around.'
            }
            payload = null // Don't show raw JSON for descriptions
          } else if (message.payload?.event === 'location_update') {
            // Don't show location_update event separately - it will be followed by location_description
            handleRoomChange(message.payload.location ?? null, 'location_update')
            break // Skip adding this event to activity
          } else if (message.payload?.verb === 'move') {
            // Don't show move acknowledgment - just skip it
            break
          }
          
          appendActivity({
            type: 'command_response',
            room: message.room,
            summary,
            payload,
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
    [appendActivity, handleRoomChange, updateOccupants]
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
