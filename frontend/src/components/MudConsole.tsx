import {
  CSSProperties,
  Fragment,
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import {
  ActivityEntry,
  formatLegacyRoomObjectLines,
  useNavigator,
} from '../context/NavigatorContext'
import { getConsoleStreamConfig } from '../config/consoleStream'
import { stripAnsiSgrSequences } from '../utils/ansi'
import { AnsiText } from './AnsiText'
import { ModemLineWriter } from './ModemLineWriter'
import {
  defaultFireBorderEffectPreset,
  defaultFireBorderInverted,
  defaultFireBorderPalette,
  defaultFireBorderRenderStyle,
  defaultFireBorderTuning,
  FireBorderPalette,
  FireBorderRenderStyle,
  FireBorderTuning,
  fireBorderEffectPresets,
  fireBorderPalettePresets,
  fireBorderRenderStyles,
  GamePanelFireBorder,
} from './CrtFireBorder'

const INTERACTIVE_FOCUS_SELECTOR =
  'button, a[href], input, textarea, select, summary, [role="button"], [contenteditable="true"], [tabindex]:not([tabindex="-1"])'

const formatLegacyRoomLines = (
  entry: ActivityEntry,
  world: ReturnType<typeof useNavigator>['world'],
  defaultRoom: number | null
): string[] => {
  if (!world) return []
  if (!entry.payload || typeof entry.payload !== 'object') return []
  if ((entry.payload as Record<string, unknown>).event !== 'location_description') return []

  const locationId =
    (entry.payload as Record<string, number | null | undefined>).location ?? defaultRoom
  const location = world.locations.find((loc) => loc.id === locationId)
  if (!location) return []

  return formatLegacyRoomObjectLines(location, world.objects, world.messages)
}

const directionByKey: Record<string, 'north' | 'south' | 'east' | 'west'> = {
  w: 'north',
  a: 'west',
  s: 'south',
  d: 'east',
}
const CONSOLE_BOTTOM_THRESHOLD_PX = 24
const TERMINAL_PAGER_DESKTOP_ROWS = 22
const TERMINAL_PAGER_MIN_ROWS = 6
const TERMINAL_PAGER_DEFAULT_LINE_HEIGHT_PX = 16
const TERMINAL_PAGER_PROMPT = '(N)onstop, (Q)uit, or (C)ontinue?'

type ConsoleLine = {
  id: string
  text: string
  className: string
  style?: CSSProperties
  promptSymbol?: boolean
  payloadText?: string
  pagerEligible?: boolean
}

type ScreenReaderConsoleLine = {
  id: string
  text: string
}

type TerminalPagerAction = 'continue' | 'nonstop' | 'quit'

type TerminalPagerLineState = {
  visibleRows: number
  pageRows?: number
  nonstop?: boolean
  quit?: boolean
}

type TerminalPagerRenderInfo = {
  text: string
  paused: boolean
  totalRows: number
  visibleRows: number
}

const SCREEN_READER_STREAM_HISTORY_LIMIT = 20

const formatConsoleLineForAnnouncement = (line: ConsoleLine): string =>
  [line.promptSymbol ? 'Command.' : null, line.text, line.payloadText]
    .map((part) => (part ? stripAnsiSgrSequences(part).trim() : ''))
    .filter((part): part is string => Boolean(part))
    .join(' ')
    .trim()

const fireTuningControls: Array<{
  key: keyof FireBorderTuning
  label: string
  min: number
  max: number
  precision: number
  step: number
}> = [
  { key: 'detail', label: 'Detail (sharpness)', min: 0.3, max: 1, precision: 3, step: 0.01 },
  { key: 'edgeFrequency', label: 'Edge frequency', min: 0.006, max: 0.05, precision: 3, step: 0.001 },
  { key: 'edgeAmplitude', label: 'Edge amplitude', min: 2, max: 50, precision: 0, step: 1 },
  { key: 'flickerAmount', label: 'Flicker amount', min: 0, max: 20, precision: 2, step: 0.5 },
  { key: 'flickerSpeed', label: 'Flicker speed', min: 0, max: 4, precision: 2, step: 0.05 },
  { key: 'driftSpeed', label: 'Drift speed', min: 0, max: 2, precision: 2, step: 0.02 },
  { key: 'charDepth', label: 'Char depth', min: 6, max: 44, precision: 0, step: 1 },
  { key: 'glowBleed', label: 'Glow bleed', min: 1, max: 16, precision: 2, step: 0.5 },
  { key: 'outerGlow', label: 'Outer glow', min: 0, max: 1.2, precision: 3, step: 0.02 },
  { key: 'glowRadius', label: 'Glow radius', min: 0, max: 24, precision: 0, step: 1 },
  { key: 'softness', label: 'Softness', min: 0, max: 6, precision: 2, step: 0.2 },
  { key: 'pulseSpeed', label: 'Pulse speed', min: 0, max: 6, precision: 2, step: 0.1 },
  { key: 'pulseDepth', label: 'Pulse depth', min: 0, max: 0.6, precision: 3, step: 0.02 },
  { key: 'embers', label: 'Embers', min: 0, max: 2, precision: 3, step: 0.05 },
]

const fireRenderStyleLabels: Record<FireBorderRenderStyle, string> = {
  paperMask: 'Burning paper',
  path: 'Current path',
  thresholdMask: 'Noise threshold',
}

const firePaletteControls: Array<{
  key: keyof FireBorderPalette
  label: string
}> = [
  { key: 'paper', label: 'Parchment' },
  { key: 'char', label: 'Char' },
  { key: 'flame', label: 'Flame core' },
  { key: 'deep', label: 'Flame deep' },
  { key: 'lip', label: 'Hot lip' },
  { key: 'emberBright', label: 'Ember bright' },
  { key: 'emberDim', label: 'Ember fade' },
  { key: 'void', label: 'Backdrop' },
]

const isHexColor = (value: string) => /^#[0-9a-fA-F]{6}$/.test(value)

const formatPayload = (payload: ActivityEntry['payload']): string | null => {
  if (payload === undefined || payload === null) return null
  if (typeof payload === 'object' && 'event' in payload) {
    return null
  }

  if (typeof payload === 'string') return payload
  if (typeof payload === 'number' || typeof payload === 'boolean') {
    return String(payload)
  }
  return null
}

const terminalRows = (text: string) => text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')

const terminalRowCount = (text: string) => terminalRows(text).length

const terminalTextForRows = (text: string, rows: number) =>
  terminalRows(text).slice(0, Math.max(0, rows)).join('\n')

const resolveTerminalPagerPageRows = (node: HTMLElement | null): number => {
  if (!node || node.clientHeight <= 0) return TERMINAL_PAGER_DESKTOP_ROWS

  const style = window.getComputedStyle(node)
  let lineHeight = Number.parseFloat(style.lineHeight)
  if (!Number.isFinite(lineHeight) || lineHeight <= 0) {
    const fontSize = Number.parseFloat(style.fontSize)
    lineHeight =
      Number.isFinite(fontSize) && fontSize > 0
        ? fontSize * 1.6
        : TERMINAL_PAGER_DEFAULT_LINE_HEIGHT_PX
  }

  const visibleRows = Math.floor(node.clientHeight / lineHeight)
  if (!Number.isFinite(visibleRows) || visibleRows <= 0) {
    return TERMINAL_PAGER_DESKTOP_ROWS
  }

  return Math.max(
    TERMINAL_PAGER_MIN_ROWS,
    Math.min(TERMINAL_PAGER_DESKTOP_ROWS, visibleRows - 1)
  )
}

const resolveTerminalPagerAction = (value: string): TerminalPagerAction | null => {
  const normalized = value.trim().toLowerCase()
  if (normalized === '' || normalized === 'c' || normalized === 'continue') return 'continue'
  if (normalized === 'n' || normalized === 'nonstop') return 'nonstop'
  if (normalized === 'q' || normalized === 'quit') return 'quit'
  return null
}

const isLifecycleMessagePayload = (payload: ActivityEntry['payload']) =>
  typeof payload === 'object' &&
  payload !== null &&
  (payload as Record<string, unknown>).event === 'lifecycle_message'

const getTerminalPagerRenderInfo = (
  line: ConsoleLine,
  state: TerminalPagerLineState | undefined,
  pageRows: number
): TerminalPagerRenderInfo | null => {
  if (!line.pagerEligible) return null
  const totalRows = terminalRowCount(line.text)
  if (totalRows <= pageRows) return null

  const visibleRows = Math.min(
    totalRows,
    state?.visibleRows ?? pageRows
  )
  const paused = !state?.quit && !state?.nonstop && visibleRows < totalRows

  return {
    text: terminalTextForRows(line.text, visibleRows),
    paused,
    totalRows,
    visibleRows,
  }
}

const formatTerminalPagerAnnouncement = (
  line: ConsoleLine,
  pagerInfo: TerminalPagerRenderInfo
): string => {
  const visibleText = formatConsoleLineForAnnouncement({ ...line, text: pagerInfo.text })
  return [visibleText, pagerInfo.paused ? TERMINAL_PAGER_PROMPT : null]
    .filter((part): part is string => Boolean(part))
    .join(' ')
}

export const MudConsole = () => {
  const {
    activity,
    connectionStatus,
    currentRoom,
    playerVisuals,
    sendCommand,
    sendMove,
    advanceLifecycle,
    session,
    world,
  } = useNavigator()
  const [input, setInput] = useState('')
  const [navMode, setNavMode] = useState(false)
  const [fireEffectPresetId, setFireEffectPresetId] = useState(defaultFireBorderEffectPreset.id)
  const [fireRenderStyle, setFireRenderStyle] =
    useState<FireBorderRenderStyle>(defaultFireBorderRenderStyle)
  const [fireTuning, setFireTuning] = useState<FireBorderTuning>(defaultFireBorderTuning)
  const [isFireBorderInverted, setIsFireBorderInverted] = useState(defaultFireBorderInverted)
  const [firePalettePresetId, setFirePalettePresetId] = useState(fireBorderPalettePresets[0].id)
  const [firePalette, setFirePalette] = useState<FireBorderPalette>(defaultFireBorderPalette)
  const [firePaletteDraft, setFirePaletteDraft] =
    useState<FireBorderPalette>(defaultFireBorderPalette)
  const [isVfxTuningCollapsed, setIsVfxTuningCollapsed] = useState(false)
  const [isVfxPaletteCollapsed, setIsVfxPaletteCollapsed] = useState(false)
  const [burnPresetCopyStatus, setBurnPresetCopyStatus] = useState('')
  const [paletteCopyStatus, setPaletteCopyStatus] = useState('')
  const [streamConfig] = useState(() => getConsoleStreamConfig())
  const [streamQueueIds, setStreamQueueIds] = useState<string[]>([])
  const [completedStreamLineIds, setCompletedStreamLineIds] = useState<Set<string>>(() => new Set())
  const [terminalPagerLineStates, setTerminalPagerLineStates] = useState<
    Record<string, TerminalPagerLineState>
  >({})
  const [terminalPagerPageRows, setTerminalPagerPageRows] = useState(
    TERMINAL_PAGER_DESKTOP_ROWS
  )
  const [screenReaderStreamLines, setScreenReaderStreamLines] = useState<
    ScreenReaderConsoleLine[]
  >([])
  const [hasNewOutputBelow, setHasNewOutputBelow] = useState(false)
  const [lifecycleAdvancePending, setLifecycleAdvancePending] = useState(false)
  const showVfxTuning =
    typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('vfxtune')
  const logRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const isConsoleFollowingRef = useRef(true)
  const lifecycleAdvancePendingRef = useRef(false)
  const isMountedRef = useRef(true)

  useLayoutEffect(() => {
    const updatePagerRows = () => {
      setTerminalPagerPageRows((current) => {
        const next = resolveTerminalPagerPageRows(logRef.current)
        return next === current ? current : next
      })
    }

    updatePagerRows()

    const node = logRef.current
    let observer: ResizeObserver | null = null
    if (node && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(updatePagerRows)
      observer.observe(node)
    }

    window.addEventListener('resize', updatePagerRows)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', updatePagerRows)
    }
  }, [])

  const location = useMemo(() => {
    if (!world || currentRoom === null) return null
    return world.locations.find((loc) => loc.id === currentRoom) ?? null
  }, [currentRoom, world])
  const lifecycleIntroActive = session?.lifecycle?.state === 'first_login_intro'

  const isConsoleNearBottom = useCallback((node: HTMLDivElement) => {
    return node.scrollHeight - node.scrollTop - node.clientHeight <= CONSOLE_BOTTOM_THRESHOLD_PX
  }, [])

  const scrollConsoleToBottom = useCallback(() => {
    const node = logRef.current
    if (!node) return
    isConsoleFollowingRef.current = true
    if (typeof node.scrollTo === 'function') {
      node.scrollTo({ top: node.scrollHeight })
    } else {
      node.scrollTop = node.scrollHeight
    }
    setHasNewOutputBelow(false)
  }, [])

  const handleConsoleOutputProgress = useCallback(() => {
    const node = logRef.current
    if (!node) return
    if (isConsoleFollowingRef.current || isConsoleNearBottom(node)) {
      scrollConsoleToBottom()
      return
    }
    setHasNewOutputBelow(true)
  }, [isConsoleNearBottom, scrollConsoleToBottom])

  useEffect(() => {
    const node = logRef.current
    if (!node) return

    const handleScroll = () => {
      const isNearBottom = isConsoleNearBottom(node)
      isConsoleFollowingRef.current = isNearBottom
      if (isNearBottom) {
        setHasNewOutputBelow(false)
      }
    }

    node.addEventListener('scroll', handleScroll)
    handleScroll()
    return () => node.removeEventListener('scroll', handleScroll)
  }, [isConsoleNearBottom])

  useEffect(() => {
    if (!navMode) return

    const handleKeydown = (event: KeyboardEvent) => {
      if (lifecycleIntroActive) return
      const direction = directionByKey[event.key.toLowerCase()]
      if (!direction) return
      event.preventDefault()
      sendMove(direction)
    }

    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  }, [lifecycleIntroActive, navMode, sendMove])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (lifecycleIntroActive) return
    lifecycleAdvancePendingRef.current = false
    setLifecycleAdvancePending(false)
  }, [lifecycleIntroActive])

  useEffect(() => {
    if (!lifecycleIntroActive) return
    inputRef.current?.focus()
  }, [lifecycleIntroActive])

  const advanceLifecycleFromPrompt = useCallback(
    (submitted: string) => {
      if (lifecycleAdvancePendingRef.current) return
      lifecycleAdvancePendingRef.current = true
      setLifecycleAdvancePending(true)
      setInput('')
      void (async () => {
        try {
          await advanceLifecycle(submitted.trim())
        } catch {
          // NavigatorContext surfaces lifecycle failures; keep the prompt usable.
        } finally {
          lifecycleAdvancePendingRef.current = false
          if (isMountedRef.current) {
            setLifecycleAdvancePending(false)
            inputRef.current?.focus()
          }
        }
      })()
    },
    [advanceLifecycle]
  )

  const markCustomFireEffect = () => {
    setFireEffectPresetId('custom')
    setBurnPresetCopyStatus('')
  }

  const markCustomFirePalette = () => {
    setFirePalettePresetId('custom')
    setPaletteCopyStatus('')
  }

  const applyFireEffectPreset = (presetId: string) => {
    const preset = fireBorderEffectPresets.find((entry) => entry.id === presetId)
    if (!preset) {
      setFireEffectPresetId('custom')
      setBurnPresetCopyStatus('')
      return
    }

    setFireEffectPresetId(preset.id)
    setFireRenderStyle(preset.renderStyle)
    setFireTuning(preset.tuning)
    setIsFireBorderInverted(preset.inverted)
    setBurnPresetCopyStatus('')
  }

  const applyFirePalettePreset = (presetId: string) => {
    const preset = fireBorderPalettePresets.find((entry) => entry.id === presetId)
    if (!preset) {
      markCustomFirePalette()
      return
    }

    const nextPalette = { ...preset.palette }
    setFirePalettePresetId(preset.id)
    setFirePalette(nextPalette)
    setFirePaletteDraft(nextPalette)
    setPaletteCopyStatus('')
  }

  const updateFireTuning = (key: keyof FireBorderTuning, value: number) => {
    markCustomFireEffect()
    setFireTuning((current) => ({ ...current, [key]: value }))
  }

  const updateFirePalette = (key: keyof FireBorderPalette, value: string) => {
    const normalized = value.toLowerCase()
    markCustomFirePalette()
    setFirePalette((current) => ({ ...current, [key]: normalized }))
    setFirePaletteDraft((current) => ({ ...current, [key]: normalized }))
  }

  const updateFirePaletteDraft = (key: keyof FireBorderPalette, value: string) => {
    const normalized = value.trim().toLowerCase()
    markCustomFirePalette()
    setFirePaletteDraft((current) => ({ ...current, [key]: normalized }))
    if (isHexColor(normalized)) {
      setFirePalette((current) => ({ ...current, [key]: normalized }))
    }
  }

  const resetFireVfx = () => {
    setFireRenderStyle(defaultFireBorderRenderStyle)
    setFireTuning(defaultFireBorderTuning)
    setIsFireBorderInverted(defaultFireBorderInverted)
    setFireEffectPresetId(defaultFireBorderEffectPreset.id)
    setBurnPresetCopyStatus('')
  }

  const resetFirePalette = () => {
    applyFirePalettePreset(fireBorderPalettePresets[0].id)
    setPaletteCopyStatus('')
  }

  const fireEffectPresetOutput = useMemo(
    () =>
      JSON.stringify(
        {
          inverted: isFireBorderInverted,
          renderStyle: fireRenderStyle,
          tuning: fireTuning,
        },
        null,
        2
      ),
    [fireRenderStyle, fireTuning, isFireBorderInverted]
  )

  const firePalettePresetOutput = useMemo(
    () => JSON.stringify(firePalette, null, 2),
    [firePalette]
  )

  const copyFireEffectPreset = async () => {
    if (!navigator.clipboard) {
      setBurnPresetCopyStatus('Clipboard unavailable')
      return
    }

    try {
      await navigator.clipboard.writeText(fireEffectPresetOutput)
      setBurnPresetCopyStatus('Copied')
    } catch {
      setBurnPresetCopyStatus('Copy failed')
    }
  }

  const copyFirePalettePreset = async () => {
    if (!navigator.clipboard) {
      setPaletteCopyStatus('Clipboard unavailable')
      return
    }

    try {
      await navigator.clipboard.writeText(firePalettePresetOutput)
      setPaletteCopyStatus('Copied')
    } catch {
      setPaletteCopyStatus('Copy failed')
    }
  }

  const bannerLines = useMemo(() => {
    if (!session) {
      return ['Connect to begin exploring the world of Kyrandia.']
    }
    if (lifecycleIntroActive) {
      return []
    }
    return [`Player ${session.playerId} connected.`, '']
  }, [lifecycleIntroActive, session])

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
    if (lifecycleIntroActive) return null
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
      location.id
    )

    return entry
  }, [hasLocationDescription, lifecycleIntroActive, location, world])

  const entriesToRender = useMemo(
    () => (initialDescriptionEntry ? [initialDescriptionEntry, ...activity] : activity),
    [activity, initialDescriptionEntry]
  )

  const visibleEntries = useMemo(
    () => entriesToRender.filter((entry) => !entry.hidden),
    [entriesToRender]
  )

  useEffect(() => {
    if (!lifecycleIntroActive) return

    setTerminalPagerLineStates((current) => {
      let changed = false
      const next = { ...current }

      visibleEntries.forEach((entry) => {
        const rowCount = terminalRowCount(entry.summary)
        const entryNeedsPager =
          isLifecycleMessagePayload(entry.payload) &&
          rowCount > terminalPagerPageRows
        if (!entryNeedsPager) return

        const currentState = next[entry.id]
        if (!currentState) {
          next[entry.id] = {
            visibleRows: terminalPagerPageRows,
            pageRows: terminalPagerPageRows,
          }
          changed = true
          return
        }

        if (currentState.pageRows === terminalPagerPageRows) return

        const previousPageRows = currentState.pageRows ?? currentState.visibleRows
        const isInitialPage =
          !currentState.nonstop &&
          !currentState.quit &&
          currentState.visibleRows === previousPageRows
        next[entry.id] = {
          ...currentState,
          visibleRows: isInitialPage
            ? Math.min(rowCount, terminalPagerPageRows)
            : currentState.visibleRows,
          pageRows: terminalPagerPageRows,
        }
        changed = true
      })

      return changed ? next : current
    })
  }, [lifecycleIntroActive, terminalPagerPageRows, visibleEntries])

  const consoleLines = useMemo<ConsoleLine[]>(() => {
    const lines: ConsoleLine[] = []

    bannerLines.forEach((line, index) => {
      lines.push({
        id: `banner-${index}-${line}`,
        text: line,
        className: 'crt-line muted',
      })
    })

    visibleEntries.forEach((entry) => {
      const payloadText = formatPayload(entry.payload)
      const legacyLines =
        entry.extraLines ??
        formatLegacyRoomLines(
          entry,
          world,
          currentRoom
        )

      const isUserCommand =
        entry.type === 'command_response' &&
        typeof entry.payload === 'object' &&
        entry.payload !== null &&
        'verb' in entry.payload &&
        !('event' in entry.payload)

      const isUnimplemented =
        entry.type === 'command_response' &&
        typeof entry.payload === 'object' &&
        entry.payload !== null &&
        'event' in entry.payload &&
        entry.payload.event === 'unimplemented'
      const pagerState = terminalPagerLineStates[entry.id]
      const pagerEligible =
        isLifecycleMessagePayload(entry.payload) &&
        terminalRowCount(entry.summary) > terminalPagerPageRows &&
        (lifecycleIntroActive || Boolean(pagerState))

      lines.push({
        id: entry.id,
        text: entry.summary,
        className: `crt-line ${entry.type}`,
        style: isUnimplemented ? { fontStyle: 'italic' } : undefined,
        promptSymbol: isUserCommand,
        payloadText: payloadText ?? undefined,
        pagerEligible,
      })

      legacyLines?.forEach((line, lineIndex) => {
        lines.push({
          id: `${entry.id}-extra-${lineIndex}`,
          text: line,
          className: `crt-line ${entry.type} detail`,
        })
      })
    })

    return lines
  }, [
    bannerLines,
    currentRoom,
    lifecycleIntroActive,
    session?.playerId,
    terminalPagerPageRows,
    terminalPagerLineStates,
    visibleEntries,
    world,
  ])

  const consoleLineIds = useMemo(() => consoleLines.map((line) => line.id), [consoleLines])
  const pagerLineIds = useMemo(
    () => new Set(consoleLines.filter((line) => line.pagerEligible).map((line) => line.id)),
    [consoleLines]
  )

  useEffect(() => {
    const currentLineIds = new Set(consoleLineIds)

    setStreamQueueIds((current) => {
      const previousQueueIds = new Set(current)
      const next = current.filter((id) => currentLineIds.has(id))
      const nextQueueIds = new Set(next)

      consoleLineIds.forEach((id) => {
        if (!previousQueueIds.has(id) && !nextQueueIds.has(id)) {
          next.push(id)
          nextQueueIds.add(id)
        }
      })

      if (next.length === current.length && next.every((id, index) => id === current[index])) {
        return current
      }
      return next
    })

    setCompletedStreamLineIds((current) => {
      let changed = false
      const next = new Set<string>()
      current.forEach((id) => {
        if (currentLineIds.has(id)) {
          next.add(id)
        } else {
          changed = true
        }
      })
      return changed ? next : current
    })

    setTerminalPagerLineStates((current) => {
      let changed = false
      const next: Record<string, TerminalPagerLineState> = {}
      Object.entries(current).forEach(([id, value]) => {
        if (currentLineIds.has(id)) {
          next[id] = value
        } else {
          changed = true
        }
      })
      return changed ? next : current
    })
  }, [consoleLineIds])

  const activeStreamLineId = useMemo(
    () =>
      streamQueueIds.find((id) => !completedStreamLineIds.has(id) && !pagerLineIds.has(id)) ??
      null,
    [completedStreamLineIds, pagerLineIds, streamQueueIds]
  )

  const activeTerminalPagerLineId = useMemo(
    () =>
      consoleLines.find((line) =>
        getTerminalPagerRenderInfo(
          line,
          terminalPagerLineStates[line.id],
          terminalPagerPageRows
        )?.paused
      )?.id ?? null,
    [consoleLines, terminalPagerLineStates, terminalPagerPageRows]
  )

  const terminalPagerAnnouncement = useMemo<ScreenReaderConsoleLine | null>(() => {
    if (!streamConfig.enabled) return null

    for (const line of consoleLines) {
      const pagerInfo = getTerminalPagerRenderInfo(
        line,
        terminalPagerLineStates[line.id],
        terminalPagerPageRows
      )
      if (!pagerInfo) continue

      const state = terminalPagerLineStates[line.id]
      const disposition = state?.quit ? 'quit' : pagerInfo.paused ? 'paused' : 'complete'
      return {
        id: `${line.id}-pager-${pagerInfo.visibleRows}-${disposition}`,
        text: formatTerminalPagerAnnouncement(line, pagerInfo),
      }
    }

    return null
  }, [consoleLines, streamConfig.enabled, terminalPagerLineStates, terminalPagerPageRows])

  useEffect(() => {
    if (!terminalPagerAnnouncement) return

    setScreenReaderStreamLines((current) => {
      if (current.some((line) => line.id === terminalPagerAnnouncement.id)) return current
      return [...current, terminalPagerAnnouncement].slice(
        -SCREEN_READER_STREAM_HISTORY_LIMIT
      )
    })
  }, [terminalPagerAnnouncement])

  const handleTerminalPagerCommand = useCallback(
    (rawCommand: string) => {
      if (!activeTerminalPagerLineId) return false
      const action = resolveTerminalPagerAction(rawCommand)
      if (!action) return false

      const line = consoleLines.find((candidate) => candidate.id === activeTerminalPagerLineId)
      if (!line) return false

      const totalRows = terminalRowCount(line.text)
      setInput('')
      setTerminalPagerLineStates((current) => {
        const currentState = current[activeTerminalPagerLineId]
        const currentVisibleRows = Math.min(
          totalRows,
          currentState?.visibleRows ?? terminalPagerPageRows
        )
        const pageRows = currentState?.pageRows ?? terminalPagerPageRows
        const nextState: TerminalPagerLineState =
          action === 'continue'
            ? {
                visibleRows: Math.min(
                  totalRows,
                  currentVisibleRows + pageRows
                ),
                pageRows,
              }
            : action === 'nonstop'
              ? { visibleRows: totalRows, pageRows, nonstop: true }
              : { visibleRows: currentVisibleRows, pageRows, quit: true }

        return {
          ...current,
          [activeTerminalPagerLineId]: nextState,
        }
      })
      return true
    },
    [activeTerminalPagerLineId, consoleLines, terminalPagerPageRows]
  )

  useEffect(() => {
    if (!lifecycleIntroActive) return

    const handleLifecycleKeyDown = (event: KeyboardEvent) => {
      const target = event.target instanceof HTMLElement ? event.target : null
      const interactiveTarget = target?.closest(INTERACTIVE_FOCUS_SELECTOR)

      if (activeTerminalPagerLineId) {
        const command = event.key === 'Enter' ? '' : event.key
        if (!resolveTerminalPagerAction(command)) return
        if (interactiveTarget) return

        event.preventDefault()
        handleTerminalPagerCommand(command)
        return
      }

      if (event.key !== 'Enter') return
      if (interactiveTarget) return

      const standaloneTarget =
        target === null ||
        target === document.body ||
        target === document.documentElement ||
        target.closest('.crt') === logRef.current
      if (!standaloneTarget) return

      event.preventDefault()
      advanceLifecycleFromPrompt(inputRef.current?.value ?? '')
    }

    window.addEventListener('keydown', handleLifecycleKeyDown)
    return () => window.removeEventListener('keydown', handleLifecycleKeyDown)
  }, [
    activeTerminalPagerLineId,
    advanceLifecycleFromPrompt,
    handleTerminalPagerCommand,
    lifecycleIntroActive,
  ])

  const handlePromptKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLInputElement>) => {
      if (activeTerminalPagerLineId) {
        const command = event.key === 'Enter' ? input : event.key
        if (!resolveTerminalPagerAction(command)) return

        event.preventDefault()
        handleTerminalPagerCommand(command)
        return
      }

      if (!lifecycleIntroActive || event.key !== 'Enter') return

      event.preventDefault()
      advanceLifecycleFromPrompt(inputRef.current?.value ?? input)
    },
    [
      activeTerminalPagerLineId,
      advanceLifecycleFromPrompt,
      handleTerminalPagerCommand,
      input,
      lifecycleIntroActive,
    ]
  )

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const submitted = input.trim()

    if (activeTerminalPagerLineId) {
      handleTerminalPagerCommand(submitted)
      return
    }

    if (lifecycleIntroActive) {
      advanceLifecycleFromPrompt(submitted)
      return
    }

    if (!submitted) return

    sendCommand(submitted)
    setInput('')
  }

  const compassLabel = navMode ? 'Navigation mode active' : 'Toggle navigation mode'
  const sendButtonLabel = activeTerminalPagerLineId
    ? 'Continue'
    : lifecycleIntroActive
      ? 'Enter'
      : 'Send'
  const promptControlsDisabled = lifecycleAdvancePending && !activeTerminalPagerLineId
  const canFocusCommandInput =
    connectionStatus === 'connected' && Boolean(session) && !promptControlsDisabled

  useEffect(() => {
    if (!canFocusCommandInput) return

    const focusCommandInput = () => inputRef.current?.focus()
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        focusCommandInput()
      }
    }

    focusCommandInput()
    window.addEventListener('focus', focusCommandInput)
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      window.removeEventListener('focus', focusCommandInput)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [canFocusCommandInput, session?.token])

  const handleGameFieldMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (!canFocusCommandInput) return
      if (event.button !== 0) return
      const target = event.target instanceof HTMLElement ? event.target : null
      if (target?.closest(INTERACTIVE_FOCUS_SELECTOR)) return
      inputRef.current?.focus()
    },
    [canFocusCommandInput]
  )

  const handleLineDone = (lineId: string) => {
    const completedLine = consoleLines.find((line) => line.id === lineId)

    setCompletedStreamLineIds((current) => {
      if (current.has(lineId)) return current
      const next = new Set(current)
      next.add(lineId)
      return next
    })

    if (!streamConfig.enabled || !completedLine) return

    const announcement = formatConsoleLineForAnnouncement(completedLine)
    if (!announcement) return

    setScreenReaderStreamLines((current) => {
      if (current.some((line) => line.id === lineId)) return current
      return [...current, { id: lineId, text: announcement }].slice(
        -SCREEN_READER_STREAM_HISTORY_LIMIT
      )
    })
  }

  useEffect(() => {
    handleConsoleOutputProgress()
  }, [activeStreamLineId, consoleLines, handleConsoleOutputProgress, terminalPagerLineStates])

  const renderLine = (line: ConsoleLine) => {
    const isStreamComplete = completedStreamLineIds.has(line.id)
    const pagerInfo = getTerminalPagerRenderInfo(
      line,
      terminalPagerLineStates[line.id],
      terminalPagerPageRows
    )
    const text = pagerInfo?.text ?? line.text
    const renderInstantly = Boolean(pagerInfo)

    const renderedLine =
      !streamConfig.enabled || isStreamComplete || renderInstantly ? (
        <p key={`${line.id}-text`} className={line.className} style={line.style}>
          {line.promptSymbol ? (
            <span className="prompt-symbol" aria-hidden>
              &gt;
            </span>
          ) : null}
          <AnsiText text={text} playerVisuals={playerVisuals} />
          {line.payloadText && <span className="payload-inline">{line.payloadText}</span>}
        </p>
      ) : null

    if (renderedLine) {
      return (
        <Fragment key={line.id}>
          {renderedLine}
          {pagerInfo?.paused && (
            <p className="crt-line command_response pager-prompt">
              {TERMINAL_PAGER_PROMPT}
            </p>
          )}
        </Fragment>
      )
    }

    if (line.id === activeStreamLineId) {
      return (
        <p key={line.id} className={line.className} style={line.style}>
          {line.promptSymbol ? (
            <span className="prompt-symbol" aria-hidden>
              &gt;
            </span>
          ) : null}
          <ModemLineWriter
            text={text}
            enabled
            charsPerSecond={streamConfig.charsPerSecond}
            charsPerTick={streamConfig.charsPerTick}
            onProgress={handleConsoleOutputProgress}
            onDone={() => handleLineDone(line.id)}
            playerVisuals={playerVisuals}
          />
          {line.payloadText && <span className="payload-inline">{line.payloadText}</span>}
        </p>
      )
    }

    return null
  }

  return (
    <section className="mud-shell">
      <GamePanelFireBorder
        inverted={isFireBorderInverted}
        palette={firePalette}
        renderStyle={fireRenderStyle}
        tuning={fireTuning}
      />
      <div className="mud-grid" data-testid="mud-grid">
        <div className="mud-window">
          <header className="mud-header">
            <p className="muted mud-session-line">
              {session ? (
                <AnsiText text={`Player ${session.playerId}`} playerVisuals={playerVisuals} />
              ) : (
                'No session yet'
              )}
            </p>
            <div className={`connection-pill ${connectionStatus}`}>
              {connectionStatus}
            </div>
          </header>

          <div
            className="crt"
            ref={logRef}
            aria-live={streamConfig.enabled ? 'off' : 'polite'}
            onMouseDown={handleGameFieldMouseDown}
          >
            <div className="crt-glow" />
            <div className="crt-lines">
              {consoleLines.map((line) => renderLine(line))}
            </div>
            {hasNewOutputBelow && (
              <button
                type="button"
                className="crt-new-output"
                aria-label="Scroll to latest console output"
                onClick={scrollConsoleToBottom}
              >
                <span aria-hidden>v</span>
                New output below
              </button>
            )}
          </div>

          {streamConfig.enabled && (
            <div
              className="sr-only"
              aria-live="polite"
              aria-atomic="false"
              data-testid="console-stream-announcements"
            >
              {screenReaderStreamLines.map((line) => (
                <p key={line.id}>{line.text}</p>
              ))}
            </div>
          )}

          {activeTerminalPagerLineId && (
            <div className="terminal-action-row pager-actions" aria-label="Pager controls">
              <button
                type="button"
                aria-label="Show all pager output"
                onClick={() => handleTerminalPagerCommand('n')}
              >
                Nonstop
              </button>
              <button
                type="button"
                aria-label="Quit pager output"
                onClick={() => handleTerminalPagerCommand('q')}
              >
                Quit
              </button>
              <button
                type="button"
                aria-label="Continue pager output"
                onClick={() => handleTerminalPagerCommand('c')}
              >
                Continue
              </button>
            </div>
          )}
          <form className="prompt-row" onSubmit={handleSubmit}>
            <button
              type="button"
              aria-label={compassLabel}
              className={`compass ${navMode ? 'active' : ''}`}
              onClick={() => setNavMode((prev) => !prev)}
            >
              *
            </button>
            <div className={`prompt-field ${navMode ? 'nav-active' : ''}`}>
              <span className="prompt-symbol">{navMode ? 'NAV>' : '>'}</span>
              <input
                ref={inputRef}
                aria-label="command input"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handlePromptKeyDown}
                onFocus={() => setNavMode(false)}
                placeholder="Type commands like LOOK, SAY HELLO, or INVENTORY"
                disabled={promptControlsDisabled}
              />
            </div>
            <button
              type="submit"
              className="send-button"
              disabled={promptControlsDisabled}
            >
              {sendButtonLabel}
            </button>
          </form>
          <p className="mode-hint">
            {navMode
              ? 'Navigation mode: WASD sends movement (click the prompt to exit).'
              : 'Enter a command to interact. Click the compass for WASD navigation.'}
          </p>
          {showVfxTuning && (
            <>
              <section
                className={`vfx-tuning-panel ${isVfxTuningCollapsed ? 'collapsed' : ''}`}
                aria-label="Temporary VFX tuning controls"
              >
                <header className="vfx-tuning-header">
                  <h3>Burn controls</h3>
                  <button
                    type="button"
                    aria-controls="vfx-tuning-body"
                    aria-expanded={!isVfxTuningCollapsed}
                    aria-label={
                      isVfxTuningCollapsed ? 'Expand burn controls' : 'Minimize burn controls'
                    }
                    className="vfx-tuning-collapse"
                    onClick={() => setIsVfxTuningCollapsed((current) => !current)}
                  >
                    {isVfxTuningCollapsed ? '+' : '-'}
                  </button>
                </header>
                <div id="vfx-tuning-body" hidden={isVfxTuningCollapsed}>
                  <div className="vfx-tuning-grid">
                    <label className="vfx-tuning-control">
                      <span>Burn preset</span>
                      <select
                        aria-label="Burn preset"
                        value={fireEffectPresetId}
                        onChange={(event) => applyFireEffectPreset(event.currentTarget.value)}
                      >
                        {fireBorderEffectPresets.map((preset) => (
                          <option key={preset.id} value={preset.id}>
                            {preset.label}
                          </option>
                        ))}
                        <option value="custom">Custom</option>
                      </select>
                    </label>
                    <label className="vfx-tuning-control">
                      <span>Burn style</span>
                      <select
                        aria-label="Burn style"
                        value={fireRenderStyle}
                        onChange={(event) => {
                          markCustomFireEffect()
                          setFireRenderStyle(event.currentTarget.value as FireBorderRenderStyle)
                        }}
                      >
                        {fireBorderRenderStyles.map((style) => (
                          <option key={style} value={style}>
                            {fireRenderStyleLabels[style]}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="vfx-tuning-checkbox">
                      <input
                        type="checkbox"
                        aria-label="Invert burn edge"
                        checked={isFireBorderInverted}
                        onChange={(event) => {
                          markCustomFireEffect()
                          setIsFireBorderInverted(event.currentTarget.checked)
                        }}
                      />
                      <span>Invert burn edge</span>
                    </label>
                    {fireTuningControls.map((control) => {
                      const value = fireTuning[control.key]
                      return (
                        <label key={control.key} className="vfx-tuning-control">
                          <span>
                            {control.label}
                            <span className="vfx-tuning-value">
                              {value.toFixed(control.precision)}
                            </span>
                          </span>
                          <input
                            type="range"
                            min={control.min}
                            max={control.max}
                            step={control.step}
                            value={value}
                            onChange={(event) =>
                              updateFireTuning(control.key, Number(event.currentTarget.value))
                            }
                          />
                        </label>
                      )
                    })}
                  </div>
                  <label className="vfx-palette-output">
                    <span>Burn preset output</span>
                    <textarea
                      aria-label="Burn preset output"
                      readOnly
                      rows={9}
                      value={fireEffectPresetOutput}
                    />
                  </label>
                  <div className="vfx-palette-actions">
                    <button type="button" onClick={copyFireEffectPreset}>
                      Copy burn preset
                    </button>
                    <button type="button" onClick={resetFireVfx}>
                      Reset defaults
                    </button>
                  </div>
                  {burnPresetCopyStatus && <p className="vfx-copy-status">{burnPresetCopyStatus}</p>}
                </div>
              </section>
              <section
                className={`vfx-palette-panel ${isVfxPaletteCollapsed ? 'collapsed' : ''}`}
                aria-label="Temporary VFX palette controls"
              >
                <header className="vfx-tuning-header">
                  <h3>Palette</h3>
                  <button
                    type="button"
                    aria-controls="vfx-palette-body"
                    aria-expanded={!isVfxPaletteCollapsed}
                    aria-label={
                      isVfxPaletteCollapsed ? 'Expand palette controls' : 'Minimize palette controls'
                    }
                    className="vfx-tuning-collapse"
                    onClick={() => setIsVfxPaletteCollapsed((current) => !current)}
                  >
                    {isVfxPaletteCollapsed ? '+' : '-'}
                  </button>
                </header>
                <div id="vfx-palette-body" hidden={isVfxPaletteCollapsed}>
                  <div className="vfx-palette-grid">
                    <label className="vfx-tuning-control">
                      <span>Palette preset</span>
                      <select
                        aria-label="Palette preset"
                        value={firePalettePresetId}
                        onChange={(event) => applyFirePalettePreset(event.currentTarget.value)}
                      >
                        {fireBorderPalettePresets.map((preset) => (
                          <option key={preset.id} value={preset.id}>
                            {preset.label}
                          </option>
                        ))}
                        <option value="custom">Custom</option>
                      </select>
                    </label>
                    {firePaletteControls.map((control) => {
                      const value = firePalette[control.key]
                      const draftValue = firePaletteDraft[control.key]
                      return (
                        <label key={control.key} className="vfx-palette-control">
                          <span>
                            {control.label}
                            <span className="vfx-tuning-value">{value}</span>
                          </span>
                          <span className="vfx-palette-inputs">
                            <input
                              type="color"
                              aria-label={`Palette ${control.label} swatch`}
                              value={value}
                              onChange={(event) =>
                                updateFirePalette(control.key, event.currentTarget.value)
                              }
                            />
                            <input
                              type="text"
                              aria-label={`Palette ${control.label} hex`}
                              spellCheck={false}
                              value={draftValue}
                              onChange={(event) =>
                                updateFirePaletteDraft(control.key, event.currentTarget.value)
                              }
                            />
                          </span>
                        </label>
                      )
                    })}
                  </div>
                  <label className="vfx-palette-output">
                    <span>Palette preset output</span>
                    <textarea
                      aria-label="Palette preset output"
                      readOnly
                      rows={8}
                      value={firePalettePresetOutput}
                    />
                  </label>
                  <div className="vfx-palette-actions">
                    <button type="button" onClick={copyFirePalettePreset}>
                      Copy preset
                    </button>
                    <button type="button" onClick={resetFirePalette}>
                      Reset palette
                    </button>
                  </div>
                  {paletteCopyStatus && <p className="vfx-copy-status">{paletteCopyStatus}</p>}
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
