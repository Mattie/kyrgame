import { ReactNode } from 'react'

import { gemstonePalette, getGemstoneVisual } from '../data/gemstonePalette'

export type PlayerVisual = {
  emoji: string
  className: string
  color: string
}

const creaturePalette: Record<
  string,
  { emoji: string; className: string; color: string }
> = {
  dragon: { emoji: '🐲', className: 'creature-dragon', color: '#ff6b5f' },
  zar: { emoji: '🐲', className: 'creature-dragon', color: '#ff6b5f' },
  dryad: { emoji: '🌱', className: 'creature-dryad', color: 'yellowgreen' },
  elf: { emoji: '🧝', className: 'creature-elf', color: 'green' },
  brownie: { emoji: '😈', className: 'creature-brownie', color: '#b07a4f' },
}

const escapeRegex = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * Parses text and renders legacy named things with emoji and color styling.
 * Matches names case-insensitively and replaces whole-word hits with styled spans.
 */
export const GemstoneText = ({
  text,
  playerVisuals = {},
}: {
  text: string
  playerVisuals?: Record<string, PlayerVisual>
}): JSX.Element => {
  const gemstoneNames = Object.keys(gemstonePalette)
  const creatureNames = Object.keys(creaturePalette)
  const playerEntries = Object.entries(playerVisuals)
  const playerVisualsByName = Object.fromEntries(
    playerEntries.map(([name, visual]) => [name.toLowerCase(), visual])
  )
  const playerNames = playerEntries.map(([name]) => name)
  // Live Player-IDs are matched first; the backend reserves creature names
  // so "dragon" and "dryad" remain unambiguous in console text.
  const inlineNames = [...playerNames, ...gemstoneNames, ...creatureNames]
    .map(escapeRegex)
    .sort((left, right) => right.length - left.length)

  if (inlineNames.length === 0) {
    return <>{text}</>
  }

  const pattern = new RegExp(`\\b(${inlineNames.join('|')})\\b`, 'gi')

  const parts: ReactNode[] = []
  let lastIndex = 0

  const matches = text.matchAll(pattern)

  for (const match of matches) {
    const matchedText = match[0]
    const matchIndex = match.index!

    if (matchIndex > lastIndex) {
      parts.push(text.slice(lastIndex, matchIndex))
    }

    const playerVisual = playerVisualsByName[matchedText.toLowerCase()]

    if (playerVisual) {
      parts.push(
        <span
          key={`player-${matchIndex}`}
          className={`player-inline ${playerVisual.className}`}
          style={{ color: playerVisual.color }}
        >
          {playerVisual.emoji} {matchedText}
        </span>
      )
    } else {
      const visual = getGemstoneVisual(matchedText)
      if (visual) {
        parts.push(
          <span
            key={`gem-${matchIndex}`}
            style={{ color: visual.lightColor }}
            className="gemstone-inline"
          >
            {visual.emoji} {matchedText}
          </span>
        )
      } else {
        const creatureVisual = creaturePalette[matchedText.toLowerCase()]
        if (creatureVisual) {
          parts.push(
            <span
              key={`creature-${matchIndex}`}
              className={`creature-inline ${creatureVisual.className}`}
              style={{ color: creatureVisual.color }}
            >
              {creatureVisual.emoji} {matchedText}
            </span>
          )
        } else {
          parts.push(matchedText)
        }
      }
    }

    lastIndex = matchIndex + matchedText.length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return <>{parts}</>
}
