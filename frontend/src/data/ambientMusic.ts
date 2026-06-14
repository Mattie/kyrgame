import goldenForaySrc from '../assets/GoldenForay.mp3'
import goldenLevelUpSrc from '../assets/GoldenForay_LevelUp.mp3'
import levelUpSfxSrc from '../assets/SFX_LevelUp.mp3'
import throughTheGateSrc from '../assets/ThroughTheGate.mp3'
import throughTheGateLevelUpSrc from '../assets/ThroughTheGate_LevelUp.mp3'
import willowDriftSrc from '../assets/WillowDrift1.mp3'
import willowLevelUpSrc from '../assets/WillowDrift_LevelUp.mp3'

export const AMBIENT_TRACK_WILLOW_DRIFT = 'willow-drift'
export const AMBIENT_TRACK_GOLDEN_FORAY = 'golden-foray'
export const AMBIENT_TRACK_THROUGH_GATE = 'through-the-gate'
export const AMBIENT_TRACK_WILLOW_LEVEL_UP = 'willow-drift-level-up'
export const AMBIENT_TRACK_GOLDEN_LEVEL_UP = 'golden-foray-level-up'
export const AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP = 'through-the-gate-level-up'
export const LEVEL_UP_SFX_SRC = levelUpSfxSrc

export type AmbientArea = 'dark-forest' | 'golden-forest' | 'castle'

export type AmbientTrack = {
  id: string
  label: string
  src: string
  area: AmbientArea
  levelUp?: boolean
}

export type AmbientLevelUpCueInput = {
  location?: number | null
}

export const AMBIENT_TRACKS: Record<string, AmbientTrack> = {
  [AMBIENT_TRACK_WILLOW_DRIFT]: {
    id: AMBIENT_TRACK_WILLOW_DRIFT,
    label: 'Dark forest',
    src: willowDriftSrc,
    area: 'dark-forest',
  },
  [AMBIENT_TRACK_GOLDEN_FORAY]: {
    id: AMBIENT_TRACK_GOLDEN_FORAY,
    label: 'Golden Foray',
    src: goldenForaySrc,
    area: 'golden-forest',
  },
  [AMBIENT_TRACK_THROUGH_GATE]: {
    id: AMBIENT_TRACK_THROUGH_GATE,
    label: 'Through the Gate',
    src: throughTheGateSrc,
    area: 'castle',
  },
  [AMBIENT_TRACK_WILLOW_LEVEL_UP]: {
    id: AMBIENT_TRACK_WILLOW_LEVEL_UP,
    label: 'Dark forest level up',
    src: willowLevelUpSrc,
    area: 'dark-forest',
    levelUp: true,
  },
  [AMBIENT_TRACK_GOLDEN_LEVEL_UP]: {
    id: AMBIENT_TRACK_GOLDEN_LEVEL_UP,
    label: 'Golden forest level up',
    src: goldenLevelUpSrc,
    area: 'golden-forest',
    levelUp: true,
  },
  [AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP]: {
    id: AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP,
    label: 'Castle level up',
    src: throughTheGateLevelUpSrc,
    area: 'castle',
    levelUp: true,
  },
}

const AMBIENT_TRACK_BY_AREA: Record<AmbientArea, string> = {
  'dark-forest': AMBIENT_TRACK_WILLOW_DRIFT,
  'golden-forest': AMBIENT_TRACK_GOLDEN_FORAY,
  castle: AMBIENT_TRACK_THROUGH_GATE,
}

const LEVEL_UP_TRACK_BY_AREA: Record<AmbientArea, string> = {
  'dark-forest': AMBIENT_TRACK_WILLOW_LEVEL_UP,
  'golden-forest': AMBIENT_TRACK_GOLDEN_LEVEL_UP,
  castle: AMBIENT_TRACK_THROUGH_GATE_LEVEL_UP,
}

export const getAmbientArea = (roomId: number | null | undefined): AmbientArea | null => {
  if (typeof roomId !== 'number') return null
  if (roomId >= 0 && roomId <= 171) return 'dark-forest'
  if (roomId >= 189 && roomId <= 218) return 'golden-forest'
  if (roomId >= 219 && roomId <= 302) return 'castle'
  return null
}

export const areRoomsInSameAmbientArea = (
  firstRoomId: number | null | undefined,
  secondRoomId: number | null | undefined
) => {
  const firstArea = getAmbientArea(firstRoomId)
  return firstArea !== null && firstArea === getAmbientArea(secondRoomId)
}

export const isLevelUpAmbientTrack = (track: AmbientTrack | null | undefined) =>
  Boolean(track?.levelUp)

export const resolveAmbientTrack = (roomId: number | null | undefined): AmbientTrack | null => {
  const area = getAmbientArea(roomId)
  return area ? AMBIENT_TRACKS[AMBIENT_TRACK_BY_AREA[area]] : null
}

export const resolveLevelUpTrack = (
  cue: AmbientLevelUpCueInput | null | undefined
): AmbientTrack | null => {
  const area = getAmbientArea(cue?.location)
  return area ? AMBIENT_TRACKS[LEVEL_UP_TRACK_BY_AREA[area]] : null
}
