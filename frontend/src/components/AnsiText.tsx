import { parseAnsiTokens } from '../utils/ansi'
import { GemstoneText, PlayerVisual } from './GemstoneText'
import { InlineDecorationPolicy } from './inlineDecorations'

export const AnsiText = ({
  text,
  playerVisuals,
  inlineDecorations,
}: {
  text: string
  playerVisuals?: Record<string, PlayerVisual>
  inlineDecorations?: InlineDecorationPolicy
}): JSX.Element => {
  const tokens = parseAnsiTokens(text)

  return (
    <>
      {tokens.map((token, index) => (
        <span
          key={`${index}-${token.text}`}
          className={['ansi-token', token.className].filter(Boolean).join(' ')}
        >
          <GemstoneText
            text={token.text}
            playerVisuals={playerVisuals}
            inlineDecorations={inlineDecorations}
          />
        </span>
      ))}
    </>
  )
}
