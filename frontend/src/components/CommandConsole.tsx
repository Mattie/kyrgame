import {
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  startTransition,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { useNavigator } from '../context/NavigatorContext'

const directionForKey: Record<string, 'north' | 'south' | 'east' | 'west'> = {
  w: 'north',
  s: 'south',
  a: 'west',
  d: 'east',
}

const formatEntry = (summary: string, payload?: unknown) => {
  if (payload && typeof payload === 'object') {
    return `${summary}: ${JSON.stringify(payload)}`
  }
  return summary
}

export const CommandConsole = () => {
  const { activity, connectionStatus, sendCommand, sendMove } = useNavigator()
  const [input, setInput] = useState('')
  const [navMode, setNavMode] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const consoleRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (navMode && consoleRef.current) {
      consoleRef.current.focus()
    }
  }, [navMode])

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    sendCommand(input)
    setInput('')
    setNavMode(false)
    inputRef.current?.focus()
  }

  const lines = useMemo(
    () =>
      activity.map((entry) =>
        entry.payload ? formatEntry(entry.summary, entry.payload) : entry.summary
      ),
    [activity]
  )

  const handleFocus = () => setNavMode(false)

  const handleKeyDown = (event: ReactKeyboardEvent) => {
    if (!navMode) return
    if (document.activeElement === inputRef.current) return
    const direction = directionForKey[event.key.toLowerCase()]
    if (direction) {
      event.preventDefault()
      startTransition(() => {
        sendMove(direction)
      })
    }
  }

  return (
    <section
      className="panel console"
      tabIndex={-1}
      onKeyDown={handleKeyDown}
      ref={consoleRef}
      data-testid="command-console"
    >
      <header className="console__header">
        <div>
          <p className="eyebrow">Command console</p>
          <h2>Terminal view</h2>
        </div>
        <div className="console__status">
          <span className={`mode-chip ${navMode ? 'active' : ''}`}>
            {navMode ? 'Navigation mode' : 'Prompt mode'}
          </span>
          <span className={`connection ${connectionStatus}`}>{connectionStatus}</span>
        </div>
      </header>

      <div className="console__viewport" role="log" aria-live="polite">
        {lines.length === 0 && <p className="muted">No activity yet. Type a command to begin.</p>}
        {lines.map((line, index) => (
          <p key={`${line}-${index}`} className="console__line">
            {line}
          </p>
        ))}
      </div>

      <form className="console__form" onSubmit={handleSubmit}>
        <label htmlFor="command-input">Command prompt</label>
        <div className="console__input-row">
          <button
            className={`compass ${navMode ? 'active' : ''}`}
            type="button"
            aria-label="Navigation mode toggle"
            onClick={() => setNavMode((state) => !state)}
            title="Click to route WASD to NWSE until you focus the prompt"
          >
            ☼
          </button>
          <input
            ref={inputRef}
            id="command-input"
            name="command-input"
            aria-label="Command prompt"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onFocus={handleFocus}
            placeholder="Enter MajorBBS-style commands"
            autoComplete="off"
          />
          <button type="submit" className="submit">
            Send
          </button>
        </div>
        <p className="muted nav-tip">
          Click the compass to enable navigation mode. WASD will move you north, west, south, east
          until you click back into the prompt.
        </p>
      </form>
    </section>
  )
}
