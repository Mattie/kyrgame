import { ReactNode } from 'react'

import { gemstonePalette, getGemstoneVisual } from '../data/gemstonePalette'
import {
  getGroundObjectVisual,
  groundObjectVisualAliases,
} from '../data/groundObjectVisuals'
import {
  getTransformationVisual,
  transformationVisualAliases,
} from '../data/transformationVisuals'
import {
  INLINE_DECORATION_ALL,
  InlineDecorationPolicy,
  ResolvedInlineDecorationPolicy,
} from './inlineDecorations'

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

const resolveInlineDecorations = (
  inlineDecorations: InlineDecorationPolicy | undefined
): ResolvedInlineDecorationPolicy => ({
  ...INLINE_DECORATION_ALL,
  ...(inlineDecorations ?? {}),
})

/**
 * Parses text and renders legacy named things with emoji and color styling.
 * Matches names case-insensitively and replaces whole-word hits with styled spans.
 */
export const GemstoneText = ({
  text,
  playerVisuals = {},
  inlineDecorations,
}: {
  text: string
  playerVisuals?: Record<string, PlayerVisual>
  inlineDecorations?: InlineDecorationPolicy
}): JSX.Element => {
  const decorations = resolveInlineDecorations(inlineDecorations)
  const gemstoneNames = decorations.gemstones ? Object.keys(gemstonePalette) : []
  const creatureNames = decorations.creatures ? Object.keys(creaturePalette) : []
  const groundObjectNames = decorations.groundObjects ? groundObjectVisualAliases : []
  const transformationNames = decorations.transformations ? transformationVisualAliases : []
  const playerEntries = Object.entries(playerVisuals)
  const playerVisualsByName = Object.fromEntries(
    playerEntries.map(([name, visual]) => [name.toLowerCase(), visual])
  )
  const playerNames = decorations.players ? playerEntries.map(([name]) => name) : []
  // Live Player-IDs are matched first; the backend reserves creature names
  // so "dragon" and "dryad" remain unambiguous in console text.
  const inlineNames = [
    ...playerNames,
    ...transformationNames,
    ...groundObjectNames,
    ...gemstoneNames,
    ...creatureNames,
  ]
    .map(escapeRegex)
    .sort((left, right) => right.length - left.length)

  if (inlineNames.length === 0) {
    return <>{text}</>
  }

  const pattern = new RegExp(
    `(^|[^A-Za-z0-9_])(${inlineNames.join('|')})(?=$|[^A-Za-z0-9_])`,
    'giu'
  )

  const parts: ReactNode[] = []
  let lastIndex = 0

  const matches = text.matchAll(pattern)

  for (const match of matches) {
    const leadingText = match[1] ?? ''
    const matchedText = match[2]
    const matchIndex = match.index!
    const matchedTextIndex = matchIndex + leadingText.length

    if (matchedTextIndex > lastIndex) {
      parts.push(text.slice(lastIndex, matchedTextIndex))
    }

    const playerVisual = decorations.players
      ? playerVisualsByName[matchedText.toLowerCase()]
      : undefined

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
      const transformationVisual = decorations.transformations
        ? getTransformationVisual(matchedText)
        : null
      if (transformationVisual) {
        parts.push(
          <span
            key={`transformation-${matchedTextIndex}`}
            className={`transformation-inline ${transformationVisual.className}`}
            style={{
              color: transformationVisual.color,
              textShadow: transformationVisual.textShadow,
            }}
          >
            {transformationVisual.emoji} {matchedText}
          </span>
        )
      } else {
        const groundObjectVisual = decorations.groundObjects
          ? getGroundObjectVisual(matchedText)
          : null
        if (groundObjectVisual) {
          parts.push(
            <span
              key={`ground-object-${matchIndex}`}
              className={`ground-object-inline ${groundObjectVisual.className}`}
              style={{ color: groundObjectVisual.color }}
            >
              {groundObjectVisual.emoji} {matchedText}
            </span>
          )
        } else {
          const visual = decorations.gemstones ? getGemstoneVisual(matchedText) : null
          if (visual) {
            parts.push(
              <span
                key={`gem-${matchedTextIndex}`}
                style={{ color: visual.lightColor }}
                className="gemstone-inline"
              >
                {visual.emoji} {matchedText}
              </span>
            )
          } else {
            const creatureVisual = decorations.creatures
              ? creaturePalette[matchedText.toLowerCase()]
              : undefined
            if (creatureVisual) {
              parts.push(
                <span
                  key={`creature-${matchedTextIndex}`}
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
      }
    }

    lastIndex = matchedTextIndex + matchedText.length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return <>{parts}</>
}
