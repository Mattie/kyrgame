export type ConsoleStreamConfig = {
  enabled: boolean
  baud: number
  charsPerSecond: number
  charsPerTick: number
}

export const DEFAULT_CONSOLE_STREAM_CONFIG = {
  enabled: true,
  baud: 40000,
  charsPerTick: 500,
}

const LOCAL_STORAGE_KEY = 'kyrgame.console.modem'
const MODEM_QUERY_PARAM = 'modem'
const BAUD_QUERY_PARAM = 'modemBaud'
const CHARS_PER_TICK_QUERY_PARAM = 'modemCharsPerTick'

const parseBoolean = (value: string | null): boolean | undefined => {
  if (value === null) return undefined
  const normalized = value.toLowerCase().trim()
  if (normalized === 'on' || normalized === 'true' || normalized === '1') return true
  if (normalized === 'off' || normalized === 'false' || normalized === '0') return false
  return undefined
}

const parsePositiveInteger = (value: string | null): number | undefined => {
  if (!value) return undefined
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return undefined
  const integer = Math.floor(parsed)
  if (integer <= 0) return undefined
  return integer
}

const getWindowSearchParams = () => {
  if (typeof window === 'undefined') return new URLSearchParams('')
  return new URLSearchParams(window.location.search)
}

const readLocalStorageEnabled = () => {
  if (typeof window === 'undefined' || !window.localStorage) return undefined
  try {
    return parseBoolean(window.localStorage.getItem(LOCAL_STORAGE_KEY))
  } catch {
    return undefined
  }
}

const getQueryStringConfig = () => {
  const params = getWindowSearchParams()
  const enabled = parseBoolean(params.get(MODEM_QUERY_PARAM))
  const baud = parsePositiveInteger(params.get(BAUD_QUERY_PARAM))
  const charsPerTick = parsePositiveInteger(params.get(CHARS_PER_TICK_QUERY_PARAM))
  return { enabled, baud, charsPerTick }
}

export const getConsoleStreamConfig = (): ConsoleStreamConfig => {
  const query = getQueryStringConfig()
  const localStorageEnabled = readLocalStorageEnabled()
  const enabled =
    query.enabled !== undefined
      ? query.enabled
      : localStorageEnabled ?? DEFAULT_CONSOLE_STREAM_CONFIG.enabled
  const baud = query.baud ?? DEFAULT_CONSOLE_STREAM_CONFIG.baud
  const charsPerTick = query.charsPerTick ?? DEFAULT_CONSOLE_STREAM_CONFIG.charsPerTick

  return {
    enabled,
    baud,
    charsPerSecond: baud / 10,
    charsPerTick,
  }
}
