import { createContext, useContext, useState } from 'react'
import { MODE } from '../utils/constants'

const ModeContext = createContext()

export function ModeProvider({ children }) {
  const [mode, setMode] = useState(() => {
    return localStorage.getItem('polyedge-mode') || MODE.PAPER
  })

  const toggleMode = () => {
    setMode(m => {
      const next = m === MODE.PAPER ? MODE.LIVE : MODE.PAPER
      localStorage.setItem('polyedge-mode', next)
      return next
    })
  }

  const isPaper = mode === MODE.PAPER
  const isLive = mode === MODE.LIVE

  return (
    <ModeContext.Provider value={{ mode, setMode, toggleMode, isPaper, isLive }}>
      {children}
    </ModeContext.Provider>
  )
}

export const useMode = () => useContext(ModeContext)
