import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ArrowRight, Eye, EyeOff, LockKeyhole, Mail, Sparkles } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Button, GlassCard, Input } from '../components/ui'

export function LoginPage() {
  const { isAuthenticated, isSigningIn, authError, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [formError, setFormError] = useState('')
  const returnTo = (location.state as { from?: string } | null)?.from

  if (isAuthenticated) return <Navigate to={returnTo && returnTo !== '/login' ? returnTo : '/dashboard'} replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError('')
    try {
      await signIn({ email: email.trim(), password, rememberMe })
      navigate(returnTo && returnTo !== '/login' ? returnTo : '/dashboard', { replace: true })
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Sign in failed.')
    }
  }

  return <div className="auth-page auth-page-premium">
    <div className="auth-atmosphere" aria-hidden="true"><span/><span/><span/></div>
    <GlassCard className="auth-card auth-card-premium">
      <Link to="/" className="auth-brand"><span className="brand-mark"><Sparkles size={17}/></span><span className="brand-name">leadsutra<span>AI</span></span></Link>
      <div className="auth-heading"><div className="eyebrow">YOUR WORKSPACE AWAITS</div><h1>Welcome back<span>.</span></h1><p>Sign in to continue to your sales workspace.</p></div>
      <form onSubmit={handleSubmit}>
        <label className="auth-field" htmlFor="login-email">Email address<span className="auth-input-wrap"><Mail size={15}/><Input id="login-email" type="email" placeholder="you@company.com" autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} required /></span></label>
        <label className="auth-field" htmlFor="login-password">Password<span className="auth-input-wrap"><LockKeyhole size={15}/><Input id="login-password" type={showPassword ? 'text' : 'password'} placeholder="Enter your password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /><button className="password-toggle" type="button" onClick={() => setShowPassword(value => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff size={15}/> : <Eye size={15}/>}</button></span></label>
        <div className="auth-options"><label className="remember-option"><input type="checkbox" checked={rememberMe} onChange={event => setRememberMe(event.target.checked)}/><span className="custom-check"/>Remember me</label><span className="auth-session-hint">Secure session</span></div>
        {(formError || authError) && <div className="auth-feedback error" role="alert">{formError || authError}</div>}
        <Button type="submit" variant="primary" className="auth-submit" disabled={isSigningIn}>{isSigningIn ? <><span className="button-spinner"/>Signing in…</> : <>Sign in <ArrowRight size={16}/></>}</Button>
      </form>
      <div className="auth-security-note"><LockKeyhole size={12}/> Your session is protected with a secure HttpOnly cookie.</div>
      <p className="auth-switch">New to LeadSutra? <Link to="/signup">Create an account</Link></p>
    </GlassCard>
  </div>
}
