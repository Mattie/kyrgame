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
  payload?: unknown
}

export type CharacterStatus = {
  hitpoints?: number
  spellPoints?: number
  description?: string
  inventory?: string[]
  effects?: string[]
  spellbook?: string[]
}

type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'

type NavigatorContextValue = {
  apiBaseUrl: string
  session: SessionRecord | null
  world: WorldData | null
  currentRoom: number | null
  occupants: string[]
  activity: ActivityEntry[]
  characterStatus: CharacterStatus | null
  statusRevealed: boolean
  connectionStatus: ConnectionStatus
  error: string | null
  startSession: (playerId: string, roomId?: number | null) => Promise<void>
  sendMove: (direction: 'north' | 'south' | 'east' | 'west') => void
  sendCommand: (input: string) => void
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
  const [characterStatus, setCharacterStatus] = useState<CharacterStatus | null>(null)
  const [statusRevealed, setStatusRevealed] = useState(false)
  const socketRef = useRef<WebSocket | null>(null)

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

  const updateStatusFromPayload = useCallback(
    (payload: unknown) => {
      if (!payload || typeof payload !== 'object') return
      const record = payload as Record<string, unknown>
      const hasStatusFields =
        record.hitpoints !== undefined ||
        record.spell_points !== undefined ||
        record.description !== undefined ||
        record.inventory !== undefined ||
        record.effects !== undefined ||
        record.spellbook !== undefined

      if (!hasStatusFields) return

      const normalized: CharacterStatus = {
        hitpoints:
          typeof record.hitpoints === 'number'
            ? record.hitpoints
            : characterStatus?.hitpoints,
        spellPoints:
          typeof record.spell_points === 'number'
            ? record.spell_points
            : characterStatus?.spellPoints,
        description:
          typeof record.description === 'string'
            ? record.description
            : characterStatus?.description,
        inventory: Array.isArray(record.inventory)
          ? (record.inventory as string[])
          : characterStatus?.inventory,
        effects: Array.isArray(record.effects)
          ? (record.effects as string[])
          : characterStatus?.effects,
        spellbook: Array.isArray(record.spellbook)
          ? (record.spellbook as string[])
          : characterStatus?.spellbook,
      }

      setCharacterStatus(normalized)
      setStatusRevealed(true)
    },
    [characterStatus]
  )

  const handleRoomChange = useCallback(
    (roomId: number | null, origin: string) => {
      if (roomId !== null) {
        setCurrentRoom(roomId)
        appendActivity({
          type: origin,
          room: roomId,
          summary: `${origin} (room ${roomId})`,
        })
      }
      if (session?.playerId) {
        updateOccupants([session.playerId])
      }
    },
    [appendActivity, session?.playerId, updateOccupants]
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
          updateStatusFromPayload(message.payload)
          if (message.payload?.event === 'player_enter' && message.payload.player) {
            setOccupants((current) =>
              Array.from(new Set([...(current || []), message.payload.player]))
            )
          }
          break
        }
        case 'command_response': {
          const summary = message.payload?.event ?? message.payload?.verb ?? 'command_response'
          appendActivity({
            type: 'command_response',
            room: message.room,
            summary,
            payload: message.payload,
          })
          updateStatusFromPayload(message.payload)
          if (message.payload?.event === 'location_update') {
            handleRoomChange(message.payload.location ?? null, 'location_update')
          }
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
    [appendActivity, handleRoomChange, updateOccupants, updateStatusFromPayload]
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
    (input: string) => {
      const sanitized = input.trim()
      if (sanitized === '') return
      if (!socketRef.current) {
        appendActivity({
          type: 'command_error',
          summary: 'WebSocket not connected',
        })
        return
      }
      appendActivity({ type: 'command', summary: `> ${sanitized}` })
      socketRef.current.send(
        JSON.stringify({ type: 'command', command: 'raw', input: sanitized })
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
      characterStatus,
      statusRevealed,
      connectionStatus,
      error,
      startSession,
      sendMove,
      sendCommand,
    }),
    [
      activity,
      apiBaseUrl,
      characterStatus,
      connectionStatus,
      currentRoom,
      error,
      occupants,
      sendCommand,
      sendMove,
      session,
      statusRevealed,
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
