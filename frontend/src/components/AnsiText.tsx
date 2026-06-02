import { parseAnsiTokens } from '../utils/ansi'
import { GemstoneText, PlayerVisual } from './GemstoneText'

export const AnsiText = ({
  text,
  playerVisuals,
}: {
  text: string
  playerVisuals?: Record<string, PlayerVisual>
}): JSX.Element => {
  const tokens = parseAnsiTokens(text)

  return (
    <>
      {tokens.map((token, index) => (
        <span
          key={`${index}-${token.text}`}
          className={['ansi-token', token.className].filter(Boolean).join(' ')}
        >
          <GemstoneText text={token.text} playerVisuals={playerVisuals} />
        </span>
      ))}
    </>
  )
}
