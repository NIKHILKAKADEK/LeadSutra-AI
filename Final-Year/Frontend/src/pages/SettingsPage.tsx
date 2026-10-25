import { useCallback, useEffect, useState, type ReactNode } from 'react'
import axios from 'axios'
import { LockKeyhole, Mail, RefreshCw, ShieldCheck, UserRound, Users, Volume2 } from 'lucide-react'
import { Badge, Button, ErrorState, GlassCard, Input, LoadingState, StatusBadge } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'
import { api, isApiConfigured } from '../services/api'

type Connection = { status: 'connected'; provider: 'omnidimension' }
type ConnectionState = { kind: 'idle' | 'loading' | 'ready' | 'error'; data?: Connection; message?: string }

async function fetchVoiceStatus() {
  const { data } = await api.get<Connection>('/api/v1/integrations/omnidimension/connection')
  return data
}

function getConnectionError(error: unknown) {
  if (axios.isAxiosError(error)) {
    if (!error.response) return 'Could not reach the configured API. Check the connection and try again.'
    if (error.response.status === 503) return 'Voice integration is unavailable because provider credentials are not configured on the backend.'
    if (error.response.status === 502) return 'The backend could not verify the voice provider connection.'
    return `Connection status could not be checked (HTTP ${error.response.status}).`
  }
  return 'Connection status could not be checked.'
}

function SettingsSection({ id, title, description, icon: Icon, children }: { id: string; title: string; description: string; icon: typeof UserRound; children: ReactNode }) {
  return <GlassCard className="settings-section" id={id}><div className="settings-section-heading"><span className="settings-icon"><Icon size={17}/></span><div><h2>{title}</h2><p>{description}</p></div></div>{children}</GlassCard>
}

function NotConfigured({ children }: { children: string }) { return <div className="settings-unavailable"><Badge>NOT CONNECTED</Badge><p>{children}</p></div> }

export function SettingsPage() {
  const [connection, setConnection] = useState<ConnectionState>({ kind: 'idle' })
  const checkConnection = useCallback(async () => {
    if (!isApiConfigured) { setConnection({ kind: 'error', message: 'Set VITE_API_BASE_URL to the trusted API gateway to check integration status.' }); return }
    setConnection({ kind: 'loading' })
    try { setConnection({ kind: 'ready', data: await fetchVoiceStatus() }) }
    catch (error) { setConnection({ kind: 'error', message: getConnectionError(error) }) }
  }, [])

  useEffect(() => { void checkConnection() }, [checkConnection])

  return <>
    <PageHeader eyebrow="PREFERENCES" title="Settings" description="Manage your account and connected workspace services." />
    <div className="settings-grid">
      <SettingsSection id="profile" title="Profile" description="Your personal account details." icon={UserRound}><NotConfigured>Your profile details are not available through the connected API.</NotConfigured><div className="settings-fields"><label>Name<Input disabled placeholder="Unavailable" /></label><label>Email<Input disabled type="email" placeholder="Unavailable" /></label></div></SettingsSection>
      <SettingsSection id="workspace" title="Workspace" description="Workspace identity and membership." icon={Users}><NotConfigured>Workspace configuration and member APIs are not available.</NotConfigured><div className="settings-fields"><label>Workspace name<Input disabled placeholder="Unavailable" /></label><label>Workspace domain<Input disabled placeholder="Unavailable" /></label></div></SettingsSection>
      <SettingsSection id="smtp" title="SMTP" description="Email delivery configuration." icon={Mail}><NotConfigured>No SMTP configuration endpoint is implemented. Credentials are not loaded into the browser.</NotConfigured><div className="settings-fields"><label>SMTP host<Input disabled placeholder="Not available" /></label><label>SMTP password<Input disabled type="password" value="" placeholder="Never exposed" /></label></div></SettingsSection>
      <SettingsSection id="voice" title="Voice integration" description="OmniDimension connectivity status." icon={Volume2}><div className="voice-status-row">{connection.kind === 'loading' && <LoadingState label="Checking connection"/>}{connection.kind === 'ready' && <><StatusBadge status="Connected"/><span>Provider: OmniDimension</span></>}{connection.kind === 'idle' && <Badge>UNKNOWN</Badge>}{connection.kind === 'error' && <ErrorState message={connection.message}/>}</div><p className="settings-help">This status check returns connectivity only. Provider credentials are never displayed.</p><Button variant="secondary" loading={connection.kind === 'loading'} onClick={() => void checkConnection()} disabled={connection.kind === 'loading'}><RefreshCw size={14}/> Check connection</Button></SettingsSection>
      <SettingsSection id="security" title="Security" description="Authentication and credential handling." icon={ShieldCheck}><div className="security-note"><LockKeyhole size={17}/><p>Session and access controls are handled by the connected backend. This frontend does not store bearer tokens in browser storage.</p></div><NotConfigured>No account security management endpoints are available.</NotConfigured></SettingsSection>
    </div>
  </>
}
