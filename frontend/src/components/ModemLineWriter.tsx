import { useEffect, useMemo, useRef, useState } from 'react'

import { PlayerVisual } from '../context/NavigatorContext'
import { AnsiText } from './AnsiText'

type ModemLineWriterProps = {
  text: string
  enabled: boolean
  charsPerSecond: number
  charsPerTick: number
  onProgress?: () => void
  onDone?: () => void
  playerVisuals?: Record<string, PlayerVisual>
}

const ANSI_ESCAPE = String.fromCharCode(27)
const ANSI_SEQUENCE_PREFIX = `${ANSI_ESCAPE}[`
const ANSI_SEQUENCE_SUFFIX = 'm'
const ANSI_SEQUENCE_MATCH = new RegExp(`${ANSI_ESCAPE}\\[[0-9;]*m`, 'g')

const clampPositiveNumber = (value: number): number => {
  if (!Number.isFinite(value) || value <= 0) return 0
  return value
}

const clearAnsiCount = (value: string) => value.replace(ANSI_SEQUENCE_MATCH, '').length

const normalizeCharsPerSecond = (value: number) =>
  Math.max(1, Math.floor(clampPositiveNumber(value)))
const normalizeCharsPerTick = (value: number) => Math.max(1, Math.floor(clampPositiveNumber(value)))

const revealTextByVisibleCharacters = (text: string, visibleChars: number) => {
  const target = Math.max(0, Math.floor(visibleChars))
  if (target <= 0) return ''

  let cursor = 0
  let emitted = 0
  let result = ''

  while (cursor < text.length && emitted < target) {
    if (text.startsWith(ANSI_SEQUENCE_PREFIX, cursor)) {
      const end = text.indexOf(ANSI_SEQUENCE_SUFFIX, cursor + ANSI_SEQUENCE_PREFIX.length)
      if (end === -1) break
      result += text.slice(cursor, end + 1)
      cursor = end + 1
      continue
    }

    result += text[cursor]
    emitted += 1
    cursor += 1
  }

  return result
}

export const ModemLineWriter = ({
  text,
  enabled,
  charsPerSecond,
  charsPerTick,
  onProgress,
  onDone,
  playerVisuals,
}: ModemLineWriterProps) => {
  const totalVisibleChars = useMemo(() => clearAnsiCount(text), [text])
  const resolvedCharsPerSecond = normalizeCharsPerSecond(charsPerSecond)
  const resolvedCharsPerTick = normalizeCharsPerTick(charsPerTick)
  const tickDelayMs = useMemo(
    () => Math.max(1, Math.round((1000 * resolvedCharsPerTick) / resolvedCharsPerSecond)),
    [resolvedCharsPerSecond, resolvedCharsPerTick]
  )
  const [visibleChars, setVisibleChars] = useState(enabled ? 0 : totalVisibleChars)
  const doneRef = useRef(false)

  useEffect(() => {
    doneRef.current = false
    setVisibleChars(enabled ? 0 : totalVisibleChars)
  }, [enabled, totalVisibleChars, text, resolvedCharsPerSecond, resolvedCharsPerTick])

  useEffect(() => {
    if (!enabled) return
    if (visibleChars >= totalVisibleChars) return

    const timer = window.setInterval(() => {
      setVisibleChars((current) => Math.min(totalVisibleChars, current + resolvedCharsPerTick))
    }, tickDelayMs)

    return () => window.clearInterval(timer)
  }, [enabled, resolvedCharsPerTick, tickDelayMs, totalVisibleChars, visibleChars])

  useEffect(() => {
    if (!enabled) return
    onProgress?.()
  }, [enabled, onProgress, visibleChars])

  useEffect(() => {
    if (!enabled) return
    if (doneRef.current) return
    if (visibleChars >= totalVisibleChars) {
      doneRef.current = true
      onDone?.()
    }
  }, [enabled, onDone, visibleChars, totalVisibleChars])

  const renderedText = useMemo(
    () => (enabled ? revealTextByVisibleCharacters(text, visibleChars) : text),
    [enabled, text, visibleChars]
  )

  return <AnsiText text={renderedText} playerVisuals={playerVisuals} />
}
