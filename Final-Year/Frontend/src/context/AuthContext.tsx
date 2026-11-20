import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authService, type AuthUser, type SignInCredentials, type SignUpCredentials } from '../services/auth'

type AuthContextValue = {
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  authError: string | null
  isSigningIn: boolean
  signIn: (credentials: SignInCredentials) => Promise<void>
  signUp: (credentials: SignUpCredentials) => Promise<void>
  signOut: () => Promise<void>
}
const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [authError, setAuthError] = useState<string | null>(null)
  const [isSigningIn, setIsSigningIn] = useState(false)
  useEffect(() => {
    let active = true
    authService.getCurrentUser()
      .then(currentUser => { if (active) { setUser(currentUser); setAuthError(null) } })
      .catch(error => {
        if (active) {
          setUser(null)
          setAuthError(error instanceof Error ? error.message : 'Could not restore your session.')
        }
      })
      .finally(() => { if (active) setIsLoading(false) })
    return () => { active = false }
  }, [])
  const signIn = useCallback(async (credentials: SignInCredentials) => {
    setIsSigningIn(true)
    setAuthError(null)
    try {
      setUser(await authService.signIn(credentials))
    } finally {
      setIsSigningIn(false)
    }
  }, [])
  const signUp = useCallback(async (credentials: SignUpCredentials) => {
    setIsSigningIn(true)
    setAuthError(null)
    try {
      setUser(await authService.signUp(credentials))
    } finally {
      setIsSigningIn(false)
    }
  }, [])
  const signOut = useCallback(async () => {
    await authService.signOut()
    setUser(null)
  }, [])
  const value = useMemo<AuthContextValue>(() => ({
    user,
    isAuthenticated: user !== null,
    isLoading,
    authError,
    isSigningIn,
    signIn,
    signUp,
    signOut,
  }), [user, isLoading, authError, isSigningIn, signIn, signUp, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
