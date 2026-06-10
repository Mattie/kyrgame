/* eslint-disable react-refresh/only-export-components */
import {
  PropsWithChildren,
  createContext,
  useCallback,
  useContext,
  useEffect,
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
  expiresAt?: string | null
  expiresInSeconds?: number | null
  playerFlags?: number | null
  accountUserId?: string | null
  sessionKind?: SessionKind
  adminGrants?: AdminGrants
  lifecycle?: SessionLifecycle | null
}

export type SessionLifecycle = {
  state: string
  step?: number | null
}

export type PlayerVisual = {
  emoji: string
  className: string
  color: string
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
  hidden?: boolean
  meta?: Record<string, unknown>
}

export type AdminUpdatePayload = {
  altnam?: string
  attnam?: string
  flags?: string[]
  level?: number
  gamloc?: number
  pgploc?: number
  gold?: number
  spts?: number
  hitpts?: number
  gpobjs?: Array<number | null>
  npobjs?: number
  gemidx?: number
  stones?: number[]
  stumpi?: number
  spouse?: string
  clear_spouse?: boolean
  cap_gold?: number
  cap_hitpts?: number
  cap_spts?: number
  charms?: number[]
  grant_all_spells?: boolean
}

export type AdminPlayerRecord = {
  uidnam: string
  plyrid: string
  altnam: string
  attnam: string
  gpobjs: number[]
  nmpdes?: number | null
  modno?: number | null
  level: number
  gamloc: number
  pgploc: number
  flags: number
  gold: number
  npobjs: number
  obvals: number[]
  nspells: number
  spts: number
  hitpts: number
  charms: number[]
  offspls: number
  defspls: number
  othspls: number
  spells: number[]
  gemidx?: number | null
  stones: number[]
  macros?: number | null
  stumpi?: number | null
  spouse: string
}

export type AdminMobRoom = {
  id: number
  brief?: string | null
  object_landing?: string | null
}

export type AdminMobRecord = {
  id: string
  name: string
  kind: string
  status: string
  room_id?: number | null
  state_room_id?: number | null
  object_room_id?: number | null
  room?: AdminMobRoom | null
  next_room_id?: number | null
  next_room?: AdminMobRoom | null
  home_room_id?: number | null
  counter?: number
  attack_index?: number
  next_attack?: string
  path_index?: number
  path_length?: number
  next_outcome?: string
  hint_index?: number
  routine_interval_seconds?: number
  full_path_interval_seconds?: number
  legacy_source?: string
}

export type AdminMobSnapshot = {
  animation: {
    routine_index: number
    next_routine: string
    routine_sequence?: string[]
    tick_seconds: number
    animation_tick_interval_seconds: number
    brownie_routine_interval_seconds?: number
    brownie_full_path_interval_seconds?: number
    legacy_source?: string
  }
  mobs: AdminMobRecord[]
}

export type AdminElfTriggerResponse = {
  status: 'triggered' | 'no_active_player'
  room_id: number
  player_id: string
  outcome: 'hint' | 'gold' | 'no_active_player'
  snapshot: AdminMobSnapshot
}

type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'
type SessionKind = 'game' | 'admin'
type AccountAuthMode = 'legacy' | 'login' | 'register'

type AdminGrants = {
  roles: string[]
  flags: string[]
}

type StartSessionOptions = {
  createPlayer?: boolean
  background?: 'lord' | 'lady'
  password?: string
  authMode?: AccountAuthMode
  sessionKind?: SessionKind
}

type SendCommandOptions = {
  silent?: boolean
  skipLog?: boolean
  // Requests the backend's read-only fatigue bypass for satellite/status refreshes.
  // The server honors this only for its documented allowlist, so callers can safely
  // use it for panels like inventory, room description, and spells while gameplay
  // actions still pass through the legacy macros gate.
  fatigueBypass?: boolean
  meta?: Record<string, unknown>
}

type NavigatorContextValue = {
  apiBaseUrl: string
  session: SessionRecord | null
  world: WorldData | null
  currentRoom: number | null
  occupants: string[]
  playerVisuals: Record<string, PlayerVisual>
  activity: ActivityEntry[]
  connectionStatus: ConnectionStatus
  error: string | null
  startSession: (
    playerId: string,
    roomId?: number | null,
    options?: StartSessionOptions
  ) => Promise<void>
  adminToken: string | null
  setAdminToken: (token: string | null) => void
  fetchAdminPlayer: (playerId: string) => Promise<AdminPlayerRecord>
  fetchAdminMobs: () => Promise<AdminMobSnapshot>
  triggerElf: (playerId: string, roomId: number) => Promise<AdminElfTriggerResponse>
  applyAdminUpdate: (playerId: string, payload: AdminUpdatePayload) => Promise<unknown>
  advanceLifecycle: (input: string) => Promise<void>
  sendMove: (direction: 'north' | 'south' | 'east' | 'west') => void
  sendCommand: (command: string, options?: SendCommandOptions) => void
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

const LEGACY_ROOM_PRESENCE_LINES = [
  {
    objectId: 45,
    objectName: 'dryad',
    messageId: 'KUTM05',
    fallback: 'There is a dryad standing here.',
  },
  {
    objectId: 52,
    objectName: 'dragon',
    messageId: 'KUTM06',
    fallback: 'By the way, there is a very large and angry dragon here too!',
  },
] as const

const normalizePlayerName = (name?: string | null) => (name ?? '').trim().toLowerCase()
const normalizeObjectName = (name?: string | null) => (name ?? '').trim().toLowerCase()
const PLAYER_FLAG_FEMALE = 0x00000002
const PLAYER_WIZARD_COLOR = '#a78bfa'

// Player-name styling is derived only from backend player flags carried on
// session, entrance, and occupant events. That keeps the visual treatment a
// client concern while preserving raw legacy message text and payload shapes.
const playerVisualFromFlags = (flags?: number | null): PlayerVisual => ({
  emoji:
    flags !== undefined && flags !== null && (flags & PLAYER_FLAG_FEMALE)
      ? '🧙‍♀️'
      : '🧙‍♂️',
  className: 'player-wizard',
  color: PLAYER_WIZARD_COLOR,
})

const formatVisibleRoomObjectsLine = (
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

export const formatLegacyRoomObjectLines = (
  location: LocationRecord | null,
  objects: GameObject[] | null,
  messages?: Record<string, string> | null
): string[] => {
  if (!location) return []

  const lines = [
    formatVisibleRoomObjectsLine(location, objects),
  ].filter(Boolean) as string[]
  const objectsById = new Map(objects?.map((obj) => [obj.id, obj]) ?? [])

  // Mirrors the hidden NPC presence append in legacy/KYRUTIL.C locobjs() lines 261-306.
  LEGACY_ROOM_PRESENCE_LINES.forEach((presence) => {
    const hasPresenceObject = (location.objects ?? []).some((id) => {
      const object = objectsById.get(id)
      return (
        id === presence.objectId ||
        normalizeObjectName(object?.name) === presence.objectName
      )
    })
    if (hasPresenceObject) {
      lines.push(messages?.[presence.messageId] ?? presence.fallback)
    }
  })

  return lines
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

const extractObjectIds = (objects: unknown): number[] => {
  if (!Array.isArray(objects)) return []
  return (objects as Array<{ id?: number; name?: string }>)
    .map(obj => (typeof obj === 'object' && obj?.id !== undefined ? obj.id : null))
    .filter((id): id is number => id !== null)
}

const parseSessionLifecycle = (value: unknown): SessionLifecycle | null => {
  if (!value || typeof value !== 'object') return null
  const payload = value as Record<string, unknown>
  if (typeof payload.state !== 'string' || payload.state.trim() === '') return null
  return {
    state: payload.state,
    step: typeof payload.step === 'number' ? payload.step : null,
  }
}

const parseAdminGrants = (value: unknown): AdminGrants => {
  if (!value || typeof value !== 'object') return { roles: [], flags: [] }
  const payload = value as Record<string, unknown>
  return {
    roles: Array.isArray(payload.roles)
      ? payload.roles.filter((role): role is string => typeof role === 'string')
      : [],
    flags: Array.isArray(payload.flags)
      ? payload.flags.filter((flag): flag is string => typeof flag === 'string')
      : [],
  }
}

const parseSessionKind = (value: unknown): SessionKind =>
  value === 'admin' ? 'admin' : 'game'

const formatAccountAuthError = (
  authMode: AccountAuthMode,
  responseStatus: number,
  playerId: string,
  detail: string
) => {
  const trimmedDetail = detail.trim()
  const isPlainNotFound = /^not found$/i.test(trimmedDetail)

  if (
    authMode === 'login' &&
    (responseStatus === 401 || responseStatus === 404 || isPlainNotFound)
  ) {
    return `No saved account matched ${playerId}. If this is a new character, use Create Character when the name check is available so we can remember that password.`
  }

  if (authMode === 'register' && (responseStatus === 404 || isPlainNotFound)) {
    return `Account creation is unavailable. ${playerId}'s password was not saved. Please try again after the server updates.`
  }

  return trimmedDetail || 'Unable to start session'
}

const isIntroLifecycle = (lifecycle?: SessionLifecycle | null) =>
  lifecycle?.state === 'first_login_intro'

const isFirstLoginEntryLifecycle = (lifecycle?: SessionLifecycle | null) =>
  lifecycle?.state === 'first_login_entry'

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
  const [playerVisuals, setPlayerVisuals] = useState<Record<string, PlayerVisual>>({})
  const [adminToken, setAdminToken] = useState<string | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const worldRef = useRef<WorldData | null>(null)
  const sessionRef = useRef<SessionRecord | null>(null)
  const occupantsRef = useRef<string[]>([])

  useEffect(() => {
    sessionRef.current = session
  }, [session])

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

  const mergePlayerVisuals = useCallback(
    (
      entries:
        | Array<{ player_id?: string; player?: string; flags?: number | null }>
        | null
        | undefined
    ) => {
      if (!entries || entries.length === 0) return
      setPlayerVisuals((prev) => {
        const next = { ...prev }
        entries.forEach((entry) => {
          const playerId = (entry.player_id ?? entry.player ?? '').trim()
          if (!playerId) return
          next[playerId] = playerVisualFromFlags(entry.flags)
        })
        return next
      })
    },
    []
  )

  const handleRoomChange = useCallback(
    (roomId: number | null, _origin: string) => {
      void _origin
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
    // WebSocket payloads are legacy-shaped event envelopes; narrow individual fields as used.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (message: any) => {
      if (!message || typeof message !== 'object') return
      const meta = message.meta ?? {}
      const hidden = Boolean(meta?.silent)
      switch (message.type) {
        case 'room_welcome':
        case 'room_change': {
          handleRoomChange(message.room ?? null, message.type)
          break
        }
        case 'room_broadcast': {
          const payload = message.payload ?? {}

          const excludedPlayer = payload.exclude_player ?? payload.excludePlayer
          const excludedPlayers = payload.exclude_players ?? payload.excludePlayers
          const currentPlayerId = sessionRef.current?.playerId ?? session?.playerId ?? null
          const currentPlayerName = normalizePlayerName(currentPlayerId)
          const directPlayer = payload.player ?? payload.player_id ?? payload.playerId
          if (
            (payload.scope === 'direct' &&
              directPlayer &&
              normalizePlayerName(directPlayer) !== currentPlayerName) ||
            (excludedPlayer && normalizePlayerName(excludedPlayer) === currentPlayerName) ||
            (Array.isArray(excludedPlayers) &&
              excludedPlayers.some(
                (player) =>
                  typeof player === 'string' && normalizePlayerName(player) === currentPlayerName
              ))
          ) {
            break
          }

          const resolvedRoomMessageText =
            payload.event === 'room_message' && !payload.text
              ? payload.message_id && worldRef.current?.messages
                ? worldRef.current.messages[payload.message_id]
                : undefined
              : payload.text

          const normalizedPayload =
            payload.event === 'room_message' && resolvedRoomMessageText
              ? { ...payload, text: resolvedRoomMessageText }
              : payload

          if (normalizedPayload.player && typeof normalizedPayload.player_flags === 'number') {
            mergePlayerVisuals([
              {
                player: normalizedPayload.player,
                flags: normalizedPayload.player_flags,
              },
            ])
          }

          // Handle chat events
          if (
            normalizedPayload.event === 'chat' &&
            normalizedPayload.text &&
            normalizedPayload.from
          ) {
            const chatText = `${payload.from} says, "${payload.text}"`
            appendActivity({
              type: 'room_broadcast',
              room: message.room,
              summary: chatText,
              payload: normalizedPayload,
            })
            break
          }

          // Handle player_enter events - update occupants but don't display (the text comes in a separate room_message)
          if (normalizedPayload.event === 'player_enter' && normalizedPayload.player) {
            const enteringPlayer = normalizedPayload.player
            // Don't add current player to occupants list (matches legacy KYRUTIL.C behavior)
            if (normalizePlayerName(enteringPlayer) !== normalizePlayerName(session?.playerId)) {
              setOccupants((current) => {
                const next = Array.from(new Set([...(current || []), enteringPlayer]))
                occupantsRef.current = next
                return next
              })
            }
            break // Don't display this event - the message text comes separately
          }

          if (normalizedPayload.event === 'room_occupants') {
            const nextOccupants = Array.isArray(normalizedPayload.occupants)
              ? (normalizedPayload.occupants as string[]).filter(Boolean)
              : []
            if (
              nextOccupants.some(
                (occupant) => normalizePlayerName(occupant) === currentPlayerName
              )
            ) {
              break
            }
            const occupantDetails = Array.isArray(normalizedPayload.occupant_details)
              ? (normalizedPayload.occupant_details as Array<{ player_id?: string; flags?: number | null }>)
              : []
            mergePlayerVisuals(occupantDetails)
            updateOccupants(nextOccupants)
            const occupantsText =
              normalizedPayload.text ??
              formatOccupantsLine(nextOccupants, currentPlayerId) ??
              'No one else is here.'
            appendActivity({
              type: 'room_broadcast',
              room: message.room,
              summary: occupantsText,
              payload: { ...normalizedPayload, occupants: nextOccupants, text: occupantsText },
            })
            break
          }

          // Handle room_objects events - update world state when gems spawn or objects change
          // Legacy: gem spawns broadcast room_objects via room_broadcast_envelope (KYRANIM.C)
          if (normalizedPayload.event === 'room_objects') {
            const locationId = normalizedPayload.location
            const newObjects = extractObjectIds(normalizedPayload.objects)

            if (locationId !== undefined && worldRef.current) {
              const targetLocationId = typeof locationId === 'number' ? locationId : parseInt(String(locationId), 10)
              if (!isNaN(targetLocationId)) {
                const updatedLocations = worldRef.current.locations.map(loc =>
                  loc.id === targetLocationId ? { ...loc, objects: newObjects } : loc
                )
                const updatedWorld = { ...worldRef.current, locations: updatedLocations }
                worldRef.current = updatedWorld
                setWorld(updatedWorld)
              }
            }
            break // Don't display these events in the console
          }

          const summary =
            normalizedPayload.event === 'room_message' && normalizedPayload.text
              ? normalizedPayload.text
              : normalizedPayload.event ?? 'room_broadcast'
          appendActivity({
            type: 'room_broadcast',
            room: message.room,
            summary,
            payload: normalizedPayload,
          })
          break
        }
        case 'command_response': {
          const payloadEvent = message.payload?.event
          let summary = message.payload?.event ?? message.payload?.verb ?? 'command_response'
          let payload = message.payload
          let extraLines: string[] | undefined

          // Skip command acknowledgments that have no event - they're just metadata
          if (!message.payload?.event && message.payload?.verb) {
            break
          }

          if (payloadEvent === 'room_message') {
            const resolvedRoomMessageText =
              !message.payload?.text && message.payload?.message_id && worldRef.current?.messages
                ? worldRef.current.messages[message.payload.message_id]
                : message.payload?.text
            summary = resolvedRoomMessageText ?? summary
            payload = { ...message.payload, text: resolvedRoomMessageText }
          }

          if (payloadEvent === 'spoiler') {
            const interaction =
              message.payload?.interaction ?? message.payload?.text ?? message.payload?.summary
            if (interaction) {
              summary = `... A mysterious voice whispers words of secret wisdom, "${interaction}"`
              payload = { ...message.payload, text: summary }
            }
          }

          if (payloadEvent === 'room_occupants') {
            const occupants = Array.isArray(message.payload?.occupants)
              ? (message.payload?.occupants as string[]).filter(Boolean)
              : []
            const occupantDetails = Array.isArray(message.payload?.occupant_details)
              ? (message.payload?.occupant_details as Array<{ player_id?: string; flags?: number | null }>)
              : []
            mergePlayerVisuals(occupantDetails)
            updateOccupants(occupants)
            summary =
              message.payload?.text ??
              formatOccupantsLine(occupants, session?.playerId ?? null) ??
              'No one else is here.'
            payload = { ...message.payload, occupants }
            appendActivity({
              type: 'command_response',
              room: message.room,
              summary,
              payload,
            })
            break
          }

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
            const objectLines = formatLegacyRoomObjectLines(
              locationRecord,
              worldRef.current?.objects ?? null,
              worldRef.current?.messages ?? null
            )
            extraLines = objectLines
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
                .map((item: { display_name?: string; name?: string } | null | undefined) => {
                  const name = item?.display_name ?? item?.name
                  // Return plain name - GemstoneText will add emoji and color when rendering
                  return name || null
                })
                .filter(Boolean)
            const inventoryText = message.payload?.text ?? summary

            summary = inventoryText
            payload = { ...message.payload, inventory: inventoryList, text: inventoryText }
          } else if (message.payload?.event === 'room_objects') {
            // Update world state with new room objects list
            const locationId = message.payload?.location
            const newObjects = extractObjectIds(message.payload?.objects)
            
            if (locationId !== undefined && worldRef.current) {
              // Ensure locationId is a number for comparison (message payload may contain string or number)
              const targetLocationId = typeof locationId === 'number' ? locationId : parseInt(String(locationId), 10)
              if (!isNaN(targetLocationId)) {
                // Update both the ref (for immediate access) and state (for re-renders)
                const updatedLocations = worldRef.current.locations.map(loc =>
                  loc.id === targetLocationId ? { ...loc, objects: newObjects } : loc
                )
                const updatedWorld = { ...worldRef.current, locations: updatedLocations }
                worldRef.current = updatedWorld
                setWorld(updatedWorld)
              }
            }
            // Don't display these events in the console
            break
          } else if (message.payload?.event === 'pickup_result') {
            // Don't display pickup_result events in the console - the inventory event shows the update
            break
          } else if (message.payload?.event === 'unimplemented') {
            summary = 'Sorry, that command exists, but it is not implemented (yet).'
            payload = { ...message.payload, text: summary }
          }

          appendActivity({
            type: 'command_response',
            room: message.room,
            summary,
            payload,
            extraLines,
            hidden,
            meta,
          })
          break
        }
        case 'command_error': {
          let errorSummary = message.payload?.detail ?? 'command_error'
          
          // Look up message from message_id if available (e.g., HUH for unknown commands)
          const messages = worldRef.current?.messages
          if (message.payload?.message_id && messages) {
            const messageText = messages[message.payload.message_id]
            if (messageText) {
              errorSummary = messageText
            }
          }
          
          appendActivity({
            type: 'command_error',
            room: message.room,
            summary: errorSummary,
            payload: message.payload,
            hidden,
            meta,
          })
          break
        }
        default:
          break
      }
    },
    [
      appendActivity,
      currentRoom,
      handleRoomChange,
      mergePlayerVisuals,
      session?.playerId,
      session?.roomId,
      updateOccupants,
    ]
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

      socket.onclose = (event) => {
        setConnectionStatus('disconnected')
        if (event.code !== 1000) {
          setError(event.reason || `WebSocket closed with code ${event.code}`)
        }
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

  const parseSessionError = useCallback(async (response: Response) => {
    const contentType = response.headers?.get?.('content-type') ?? ''
    if (contentType.includes('application/json')) {
      try {
        const payload = await response.json()
        const messages = Array.isArray(payload?.detail?.messages)
          ? payload.detail.messages
          : []
        const text = messages
          .map((message: { text?: string }) => message.text)
          .filter(Boolean)
          .join('\n')
        if (text) return text
        if (typeof payload?.detail === 'string') return payload.detail
      } catch {
        // Fall back to plain text below for non-conforming error responses.
      }
    }
    return response.text()
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

  const applyAdminUpdate = useCallback(
    async (playerId: string, payload: AdminUpdatePayload) => {
      if (!adminToken) {
        throw new Error('Admin token required for updates')
      }

      const response = await fetch(`${apiBaseUrl}/admin/players/${encodeURIComponent(playerId)}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${adminToken}`,
        },
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        const detail = await response.text()
        throw new Error(detail || 'Admin update failed')
      }

      const data = await response.json()
      return data.player
    },
    [adminToken, apiBaseUrl]
  )

  const fetchAdminPlayer = useCallback(
    async (playerId: string) => {
      if (!adminToken) {
        throw new Error('Admin token required to fetch player data')
      }

      const response = await fetch(`${apiBaseUrl}/admin/players/${encodeURIComponent(playerId)}`, {
        headers: {
          Authorization: `Bearer ${adminToken}`,
        },
      })

      if (!response.ok) {
        const detail = await response.text()
        throw new Error(detail || 'Admin player fetch failed')
      }

      const data = await response.json()
      return data.player as AdminPlayerRecord
    },
    [adminToken, apiBaseUrl]
  )

  const fetchAdminMobs = useCallback(
    async () => {
      if (!adminToken) {
        throw new Error('Admin token required to fetch mob data')
      }

      const response = await fetch(`${apiBaseUrl}/admin/mobs`, {
        headers: {
          Authorization: `Bearer ${adminToken}`,
        },
      })

      if (!response.ok) {
        const detail = await response.text()
        throw new Error(detail || 'Admin mob fetch failed')
      }

      return (await response.json()) as AdminMobSnapshot
    },
    [adminToken, apiBaseUrl]
  )

  const triggerElf = useCallback(
    async (playerId: string, roomId: number) => {
      if (!adminToken) {
        throw new Error('Admin token required to trigger the elf')
      }

      const response = await fetch(`${apiBaseUrl}/admin/mobs/elf/trigger`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${adminToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ player_id: playerId, room_id: roomId }),
      })

      if (!response.ok) {
        const detail = await response.text()
        throw new Error(detail || 'Admin elf trigger failed')
      }

      return (await response.json()) as AdminElfTriggerResponse
    },
    [adminToken, apiBaseUrl]
  )

  const startSession = useCallback(
    async (
      playerId: string,
      roomId?: number | null,
      options?: StartSessionOptions
    ) => {
      setConnectionStatus('connecting')
      setError(null)
      setActivity([])
      setPlayerVisuals({})
      resetSocket()
      try {
        const authMode: AccountAuthMode =
          options?.authMode ?? (options?.password ? 'login' : 'legacy')
        const useAccountAuth = authMode === 'login' || authMode === 'register'
        const endpoint = useAccountAuth
          ? authMode === 'register'
            ? '/auth/register'
            : '/auth/login'
          : '/auth/session'
        const payload: Record<string, string | number | boolean | null | undefined> =
          useAccountAuth
            ? {
                userid: playerId,
                password: options?.password,
                session_kind: options?.sessionKind ?? 'game',
              }
            : {
                player_id: playerId,
              }
        if (!useAccountAuth && options?.createPlayer) {
          payload.create_player = true
        }
        if (options?.background) {
          payload.background = options.background
        }
        if (roomId !== undefined && roomId !== null && !Number.isNaN(roomId)) {
          payload.room_id = roomId
        }
        const response = await fetch(`${apiBaseUrl}${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!response.ok) {
          const detail = await parseSessionError(response)
          const message = useAccountAuth
            ? formatAccountAuthError(authMode, response.status, playerId, detail)
            : detail.trim() || 'Unable to start session'
          throw new Error(message)
        }
        const data = await response.json()
        const sessionPayload = data.session
        const playerFlags =
          typeof sessionPayload.player_flags === 'number' ? sessionPayload.player_flags : null
        const lifecycle = parseSessionLifecycle(sessionPayload.lifecycle)
        const sessionKind = parseSessionKind(
          sessionPayload.session_kind ?? options?.sessionKind ?? 'game'
        )
        const record: SessionRecord = {
          token: sessionPayload.token,
          playerId: sessionPayload.player_id,
          roomId: sessionPayload.room_id,
          expiresAt: sessionPayload.expires_at ?? null,
          expiresInSeconds:
            typeof sessionPayload.expires_in_seconds === 'number'
              ? sessionPayload.expires_in_seconds
              : null,
          playerFlags,
          accountUserId:
            typeof sessionPayload.account_userid === 'string'
              ? sessionPayload.account_userid
              : null,
          sessionKind,
          adminGrants: parseAdminGrants(sessionPayload.admin_grants),
          lifecycle,
        }
        setSession(record)
        setPlayerVisuals({
          [record.playerId]: playerVisualFromFlags(playerFlags),
        })
        setCurrentRoom(record.roomId)
        updateOccupants([])
        // Load world data first and wait for it to complete before connecting WebSocket
        // worldRef.current is set immediately by loadWorldData, so messages will be available
        await loadWorldData()
        const lifecycleMessages = Array.isArray(sessionPayload.lifecycle_messages)
          ? sessionPayload.lifecycle_messages
          : []
        lifecycleMessages.forEach((message: { message_id?: string; text?: string }) => {
          appendActivity({
            type: 'command_response',
            room: record.roomId,
            summary: message.text ?? message.message_id ?? 'lifecycle_message',
            payload: {
              scope: 'player',
              event: 'lifecycle_message',
              type: 'lifecycle_message',
              message_id: message.message_id,
              text: message.text,
            },
          })
        })
        if (record.sessionKind === 'admin') {
          setAdminToken(record.token)
          setConnectionStatus('idle')
          return
        }
        if (isIntroLifecycle(record.lifecycle)) {
          setConnectionStatus('idle')
          return
        }
        connectWebSocket(record.token, record.roomId)
      } catch (err) {
        setConnectionStatus('error')
        setError(err instanceof Error ? err.message : 'Unknown error')
        throw err
      }
    },
    [
      apiBaseUrl,
      appendActivity,
      connectWebSocket,
      loadWorldData,
      parseSessionError,
      resetSocket,
      updateOccupants,
    ]
  )

  const advanceLifecycle = useCallback(
    async (input: string) => {
      const currentSession = sessionRef.current
      if (!currentSession) {
        appendActivity({
          type: 'command_error',
          summary: 'Session required',
        })
        return
      }

      const reportLifecycleError = (message: string) => {
        setError(message)
        setConnectionStatus('error')
        appendActivity({
          type: 'command_error',
          room: currentSession.roomId,
          summary: message,
          payload: { detail: message },
        })
      }

      try {
        const response = await fetch(`${apiBaseUrl}/auth/session/lifecycle/advance`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${currentSession.token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ input }),
        })
        if (!response.ok) {
          const detail = await parseSessionError(response)
          reportLifecycleError(detail || 'Unable to advance session lifecycle')
          return
        }

        const data = await response.json()
        const sessionPayload = data.session
        const playerFlags =
          typeof sessionPayload.player_flags === 'number'
            ? sessionPayload.player_flags
            : currentSession.playerFlags ?? null
        const lifecycle = parseSessionLifecycle(sessionPayload.lifecycle)
        const nextRecord: SessionRecord = {
          ...currentSession,
          token: sessionPayload.token ?? currentSession.token,
          playerId: sessionPayload.player_id ?? currentSession.playerId,
          roomId:
            typeof sessionPayload.room_id === 'number'
              ? sessionPayload.room_id
              : currentSession.roomId,
          expiresAt: sessionPayload.expires_at ?? currentSession.expiresAt ?? null,
          expiresInSeconds:
            typeof sessionPayload.expires_in_seconds === 'number'
              ? sessionPayload.expires_in_seconds
              : currentSession.expiresInSeconds ?? null,
          playerFlags,
          lifecycle,
        }
        setSession(nextRecord)
        sessionRef.current = nextRecord
        setPlayerVisuals((prev) => ({
          ...prev,
          [nextRecord.playerId]: playerVisualFromFlags(playerFlags),
        }))
        setCurrentRoom(nextRecord.roomId)

        const lifecycleMessages = Array.isArray(sessionPayload.lifecycle_messages)
          ? sessionPayload.lifecycle_messages
          : []
        lifecycleMessages.forEach((message: { message_id?: string; text?: string }) => {
          appendActivity({
            type: 'command_response',
            room: nextRecord.roomId,
            summary: message.text ?? message.message_id ?? 'lifecycle_message',
            payload: {
              scope: 'player',
              event: 'lifecycle_message',
              type: 'lifecycle_message',
              message_id: message.message_id,
              text: message.text,
            },
          })
        })

        if (isFirstLoginEntryLifecycle(nextRecord.lifecycle)) {
          const playableRecord = { ...nextRecord, lifecycle: null }
          setSession(playableRecord)
          sessionRef.current = playableRecord
          if (!worldRef.current) {
            await loadWorldData()
          }
          connectWebSocket(playableRecord.token, playableRecord.roomId)
        }
      } catch (err) {
        reportLifecycleError(
          err instanceof Error && err.message
            ? err.message
            : 'Unable to advance session lifecycle'
        )
      }
    },
    [
      apiBaseUrl,
      appendActivity,
      connectWebSocket,
      loadWorldData,
      parseSessionError,
    ]
  )

  const sendMove = useCallback(
    (direction: 'north' | 'south' | 'east' | 'west') => {
      if (isIntroLifecycle(sessionRef.current?.lifecycle)) {
        return
      }
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
    (command: string, options?: SendCommandOptions) => {
      const trimmed = command.trim()
      if (isIntroLifecycle(sessionRef.current?.lifecycle)) {
        void advanceLifecycle(trimmed)
        return
      }
      if (trimmed === '') return
      if (!socketRef.current) {
        appendActivity({
          type: 'command_error',
          summary: 'WebSocket not connected',
        })
        return
      }

      const isSilent = Boolean(options?.silent)
      const skipLog = Boolean(options?.skipLog)
      const meta = {
        ...(options?.meta ?? {}),
        ...(isSilent ? { silent: true } : {}),
        ...(options?.fatigueBypass ? { fatigue_bypass: true } : {}),
      }

      if (!skipLog) {
        appendActivity({ type: 'command', summary: `> ${trimmed}` })
      }
      const outgoing: Record<string, unknown> = {
        type: 'command',
        command: trimmed,
        args: { input: trimmed },
      }
      if (Object.keys(meta).length > 0) {
        outgoing.meta = meta
      }
      socketRef.current.send(JSON.stringify(outgoing))
    },
    [advanceLifecycle, appendActivity]
  )

  const value = useMemo(
    () => ({
      apiBaseUrl,
      session,
      world,
      currentRoom,
      occupants,
      playerVisuals,
      activity,
      connectionStatus,
      error,
      startSession,
      adminToken,
      setAdminToken,
      fetchAdminPlayer,
      fetchAdminMobs,
      triggerElf,
      applyAdminUpdate,
      advanceLifecycle,
      sendMove,
      sendCommand,
    }),
    [
      adminToken,
      activity,
      apiBaseUrl,
      applyAdminUpdate,
      advanceLifecycle,
      connectionStatus,
      currentRoom,
      error,
      fetchAdminMobs,
      fetchAdminPlayer,
      occupants,
      playerVisuals,
      setAdminToken,
      sendMove,
      sendCommand,
      session,
      startSession,
      triggerElf,
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
