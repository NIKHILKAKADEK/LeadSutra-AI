import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ArrowRight, Eye, EyeOff, LockKeyhole, Mail, Sparkles, UserRound } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Button, GlassCard, Input } from '../components/ui'

export function SignupPage() {
  const { isAuthenticated, isSigningIn, authError, signUp } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [formError, setFormError] = useState('')

  if (isAuthenticated) return <Navigate to="/dashboard" replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError('')
    try {
      await signUp({ name: name.trim(), email: email.trim(), password })
      navigate('/dashboard', { replace: true })
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Account creation failed.')
    }
  }

  return <div className="auth-page auth-page-premium">
    <div className="auth-atmosphere" aria-hidden="true"><span/><span/><span/></div>
    <GlassCard className="auth-card auth-card-premium signup-card">
      <Link to="/" className="auth-brand"><span className="brand-mark"><Sparkles size={17}/></span><span className="brand-name">leadsutra<span>AI</span></span></Link>
      <div className="auth-heading"><div className="eyebrow">START BUILDING BETTER PIPELINES</div><h1>Create your account<span>.</span></h1><p>Set up your secure LeadSutra workspace.</p></div>
      <form onSubmit={handleSubmit}>
        <label className="auth-field" htmlFor="signup-name">Your name<span className="auth-input-wrap"><UserRound size={15}/><Input id="signup-name" type="text" placeholder="Alex Morgan" autoComplete="name" minLength={2} maxLength={100} value={name} onChange={event => setName(event.target.value)} required /></span></label>
        <label className="auth-field" htmlFor="signup-email">Work email<span className="auth-input-wrap"><Mail size={15}/><Input id="signup-email" type="email" placeholder="you@company.com" autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} required /></span></label>
        <label className="auth-field" htmlFor="signup-password">Password<span className="auth-input-wrap"><LockKeyhole size={15}/><Input id="signup-password" type={showPassword ? 'text' : 'password'} placeholder="At least 8 characters" autoComplete="new-password" minLength={8} maxLength={128} value={password} onChange={event => setPassword(event.target.value)} required /><button className="password-toggle" type="button" onClick={() => setShowPassword(value => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff size={15}/> : <Eye size={15}/>}</button></span></label>
        {(formError || authError) && <div className="auth-feedback error" role="alert">{formError || authError}</div>}
        <Button type="submit" variant="primary" className="auth-submit" disabled={isSigningIn}>{isSigningIn ? <><span className="button-spinner"/>Creating account…</> : <>Create account <ArrowRight size={16}/></>}</Button>
      </form>
      <div className="auth-security-note"><LockKeyhole size={12}/> Passwords are securely hashed and never stored in plain text.</div>
      <p className="auth-switch">Already have an account? <Link to="/login">Sign in</Link></p>
    </GlassCard>
  </div>
}
