export type AnsiToken = {
  text: string
  className?: string
}

const fgColorMap: Record<number, string> = {
  30: 'ansi-fg-black',
  31: 'ansi-fg-red',
  32: 'ansi-fg-green',
  33: 'ansi-fg-yellow',
  34: 'ansi-fg-blue',
  35: 'ansi-fg-magenta',
  36: 'ansi-fg-cyan',
  37: 'ansi-fg-white',
  90: 'ansi-fg-bright-black',
  91: 'ansi-fg-bright-red',
  92: 'ansi-fg-bright-green',
  93: 'ansi-fg-bright-yellow',
  94: 'ansi-fg-bright-blue',
  95: 'ansi-fg-bright-magenta',
  96: 'ansi-fg-bright-cyan',
  97: 'ansi-fg-bright-white',
}

export const parseAnsiTokens = (text: string): AnsiToken[] => {
  const tokens: AnsiToken[] = []
  const sgrPattern = /\u001b\[([0-9;]*)m/g
  let lastIndex = 0
  let bold = false
  let fgClass: string | null = null

  const currentClassName = () => {
    const classes = []
    if (bold) classes.push('ansi-bold')
    if (fgClass) classes.push(fgClass)
    return classes.length > 0 ? classes.join(' ') : undefined
  }

  const pushToken = (value: string) => {
    if (!value) return
    tokens.push({ text: value, className: currentClassName() })
  }

  for (const match of text.matchAll(sgrPattern)) {
    const matchIndex = match.index ?? 0
    pushToken(text.slice(lastIndex, matchIndex))

    const rawCodes = match[1] ?? ''
    const codes = rawCodes
      .split(';')
      .filter((code) => code.length > 0)
      .map((code) => Number(code))

    if (codes.length === 0) {
      bold = false
      fgClass = null
    } else {
      codes.forEach((code) => {
        if (code === 0) {
          bold = false
          fgClass = null
          return
        }
        if (code === 1) {
          bold = true
          return
        }
        if (code === 22) {
          bold = false
          return
        }
        if (code === 39) {
          fgClass = null
          return
        }
        if (fgColorMap[code]) {
          fgClass = fgColorMap[code]
        }
      })
    }

    lastIndex = matchIndex + match[0].length
  }

  pushToken(text.slice(lastIndex))

  return tokens
}
