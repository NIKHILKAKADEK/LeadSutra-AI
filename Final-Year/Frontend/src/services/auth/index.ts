import { isAxiosError } from 'axios'
import { api } from '../api'
import type { AuthService, AuthUser, SignInCredentials, SignUpCredentials } from './authTypes'

type AuthResponse = { user: AuthUser }

function errorFromResponse(error: unknown): Error {
  if (isAxiosError<{ detail?: string }>(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return new Error(detail)
  }
  return new Error('Could not connect to the authentication service.')
}

export const authService: AuthService = {
  async signIn({ email, password, rememberMe }: SignInCredentials) {
    try {
      const { data } = await api.post<AuthResponse>('/api/v1/auth/login', {
        email,
        password,
        remember_me: rememberMe,
      })
      return data.user
    } catch (error) {
      throw errorFromResponse(error)
    }
  },

  async signUp(credentials: SignUpCredentials) {
    try {
      const { data } = await api.post<AuthResponse>('/api/v1/auth/signup', credentials)
      return data.user
    } catch (error) {
      throw errorFromResponse(error)
    }
  },

  async signOut() {
    try {
      await api.post('/api/v1/auth/logout')
    } catch (error) {
      throw errorFromResponse(error)
    }
  },

  async getCurrentUser() {
    try {
      const { data } = await api.get<AuthResponse>('/api/v1/auth/me')
      return data.user
    } catch (error) {
      if (isAxiosError(error) && error.response?.status === 401) return null
      throw errorFromResponse(error)
    }
  },
}

export type { AuthService, AuthUser, SignInCredentials, SignUpCredentials } from './authTypes'
