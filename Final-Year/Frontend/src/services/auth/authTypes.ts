export type AuthUser = {
  id: string
  name: string
  email: string
}

export type SignInCredentials = {
  email: string
  password: string
  rememberMe: boolean
}

export type SignUpCredentials = {
  name: string
  email: string
  password: string
}

export interface AuthService {
  signIn(credentials: SignInCredentials): Promise<AuthUser>
  signUp(credentials: SignUpCredentials): Promise<AuthUser>
  signOut(): Promise<void>
  getCurrentUser(): Promise<AuthUser | null>
}
