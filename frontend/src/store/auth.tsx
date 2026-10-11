import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../lib/api'
import type { Me, Role } from '../lib/types'

interface AuthState {
  user: Me | null
  loading: boolean
  refresh: () => Promise<void>
  setUser: (user: Me | null) => void
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const me = await api<Me>('/auth/me')
      setUser(me.authenticated ? me : null)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const logout = useCallback(async () => {
    try {
      await api('/auth/logout', { method: 'POST' })
    } finally {
      setUser(null)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Any 401 from the API means the server-side session is gone; drop local
  // auth so route guards send the user back to the sign-in page.
  useEffect(() => {
    const onUnauthorized = () => setUser(null)
    window.addEventListener('obsidian:unauthorized', onUnauthorized)
    return () => window.removeEventListener('obsidian:unauthorized', onUnauthorized)
  }, [])

  const value = useMemo(
    () => ({ user, loading, refresh, setUser, logout }),
    [user, loading, refresh, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

export function homePathFor(role?: Role): string {
  switch (role) {
    case 'faculty':
    case 'recruiter':
      return '/app/home'
    case 'admin':
      return '/app/admin'
    default:
      return '/app/dashboard'
  }
}
