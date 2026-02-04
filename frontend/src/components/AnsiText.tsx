import { parseAnsiTokens } from '../utils/ansi'
import { GemstoneText } from './GemstoneText'

export const AnsiText = ({ text }: { text: string }): JSX.Element => {
  const tokens = parseAnsiTokens(text)

  return (
    <>
      {tokens.map((token, index) => (
        <span
          key={`${index}-${token.text}`}
          className={['ansi-token', token.className].filter(Boolean).join(' ')}
        >
          <GemstoneText text={token.text} />
        </span>
      ))}
    </>
  )
}
