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

function App() {
  const [path, setPath] = useState(() => window.location.pathname || '/')

  useEffect(() => {
    const handlePopState = () => setPath(window.location.pathname || '/')
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const navigate = useCallback((nextPath: string) => {
    window.history.pushState(null, '', nextPath)
    setPath(nextPath)
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
