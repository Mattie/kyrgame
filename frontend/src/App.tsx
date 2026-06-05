import './App.css'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { NavigatorProvider } from './context/NavigatorContext'
import { Navigator } from './pages/Navigator'
import {
  AboutPage,
  EntryPage,
  LandingPage,
  LeaderboardPage,
} from './pages/PublicSite'

const normalizePath = (nextPath: string) => {
  const normalized = (nextPath || '/').replace(/\/+$/, '')
  return normalized === '' ? '/' : normalized
}

function App() {
  const [path, setPath] = useState(() => normalizePath(window.location.pathname))

  useEffect(() => {
    const handlePopState = () => setPath(normalizePath(window.location.pathname))
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const navigate = useCallback((nextPath: string) => {
    const normalizedPath = normalizePath(nextPath)
    window.history.pushState(null, '', normalizedPath)
    setPath(normalizedPath)
    window.scrollTo?.({ top: 0 })
  }, [])

  const route = useMemo(() => {
    if (path === '/admin') return <Navigator mode="admin" />
    if (path === '/play') return <Navigator mode="player" />
    if (path === '/enter') return <EntryPage navigate={navigate} />
    if (path === '/about') return <AboutPage navigate={navigate} />
    if (path === '/leaderboard') return <LeaderboardPage navigate={navigate} />
    return <LandingPage navigate={navigate} />
  }, [navigate, path])

  const shellClass = path === '/admin' || path === '/play' ? 'app-shell' : 'app-shell site-shell'

  return (
    <div className={shellClass}>
      <NavigatorProvider>{route}</NavigatorProvider>
    </div>
  )
}

export default App
