import { useCallback, useEffect, useState } from 'react'
import { Activity, CalendarClock, RefreshCw, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Button, EmptyState, GlassCard, LoadingState } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'
import { leadService, type LeadListItem } from '../services/leads'
import { outreachService, type CallHistoryItem, type FollowUpItem } from '../services/outreach'
import { classifyApiError } from '../utils/apiErrors'

export function CrmPage() {
  const [leads, setLeads] = useState<LeadListItem[]>([])
  const [followUps, setFollowUps] = useState<FollowUpItem[]>([])
  const [calls, setCalls] = useState<CallHistoryItem[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error' | 'unconfigured'>(leadService.isConfigured ? 'loading' : 'unconfigured')
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    if (!leadService.isConfigured) { setState('unconfigured'); return }
    setState('loading'); setError('')
    try {
      const [leadPage, followUpPage, callPage] = await Promise.all([
        leadService.list({ limit: 100, offset: 0 }),
        outreachService.followUps({ limit: 100, offset: 0 }),
        outreachService.callHistory({ limit: 100, offset: 0 }),
      ])
      setLeads(leadPage.leads); setFollowUps(followUpPage.follow_ups); setCalls(callPage.calls); setState('ready')
    } catch (cause) { setError(classifyApiError(cause).message); setState('error') }
  }, [])
  useEffect(() => { void load() }, [load])
  const leadNames = new Map(leads.map(lead => [lead.lead_id, lead.business_name || lead.lead_id]))
  const activities = [
    ...followUps.map(item => ({ id: item.follow_up_id, when: item.updated_at, label: `Follow-up ${item.status}`, leadId: item.lead_id, detail: item.notes || `Scheduled ${new Date(item.scheduled_at).toLocaleString()}` })),
    ...calls.map(item => ({ id: item.call_id, when: item.updated_at, label: `Call ${item.dispatch_status}`, leadId: item.lead_id, detail: item.call_outcome || 'Call outcome not provided' })),
  ].sort((a, b) => Date.parse(b.when) - Date.parse(a.when))
  return <>
    <PageHeader eyebrow="SALES DEVELOPMENT" title="CRM workspace" description="Review lead records, scheduled follow-ups, and recorded call activity." actions={<Button variant="secondary" loading={state === 'loading'} onClick={() => void load()} disabled={state === 'loading'}><RefreshCw size={15}/> Refresh</Button>} />
    {state === 'loading' && <GlassCard className="crm-state"><LoadingState label="Loading CRM records"/></GlassCard>}
    {state === 'unconfigured' && <GlassCard className="crm-state"><EmptyState icon={Users} title="Connect the protected lead API" description="Lead records, follow-ups, and calls require the configured trusted API/BFF session."/></GlassCard>}
    {state === 'error' && <GlassCard className="crm-state"><EmptyState title="CRM records unavailable" description={error} action={<Button onClick={() => void load()}>Try again</Button>}/></GlassCard>}
    {state === 'ready' && <>
      <div className="crm-summary"><GlassCard><strong>{leads.length}</strong><span>Lead records loaded</span><small>API returns at most 100 in this view</small></GlassCard><GlassCard><strong>{followUps.filter(item => item.status === 'pending').length}</strong><span>Pending follow-ups</span><small>From the follow-up endpoint</small></GlassCard><GlassCard><strong>{calls.length}</strong><span>Call records loaded</span><small>Not a lifetime total</small></GlassCard></div>
      <div className="crm-columns"><GlassCard className="crm-panel"><div className="crm-heading"><div><h2>Lead pipeline</h2><p>Backend qualification status, shown as returned.</p></div><Badge>{leads.length} LOADED</Badge></div>{leads.length ? <div className="crm-table-wrap"><table className="crm-table"><thead><tr><th>Lead</th><th>Status</th><th>Score</th><th>Phone</th></tr></thead><tbody>{leads.map(lead => <tr key={lead.lead_id}><td><Link to={`/leads/${encodeURIComponent(lead.lead_id)}`}><strong>{lead.business_name || 'Unnamed business'}</strong><small>{lead.lead_id}</small></Link></td><td>{lead.qualification_status || '—'}</td><td>{lead.lead_score ?? '—'}</td><td>{lead.phone_numbers[0] || '—'}</td></tr>)}</tbody></table></div> : <EmptyState icon={Users} title="No lead records" description="No leads were returned by the backend."/>}<p className="crm-footnote">Status editing and lead notes are not supported by the available API contract.</p></GlassCard>
      <div className="crm-side"><GlassCard className="crm-panel"><div className="crm-heading"><div><h2>Upcoming follow-ups</h2><p>Scheduled work from the follow-up service.</p></div><CalendarClock size={17}/></div>{followUps.filter(item => item.status === 'pending').length ? <div className="crm-list">{followUps.filter(item => item.status === 'pending').map(item => <div key={item.follow_up_id}><strong>{leadNames.get(item.lead_id) || item.lead_id}</strong><span>{new Date(item.scheduled_at).toLocaleString()}</span><small>{item.notes || 'No notes'}</small></div>)}</div> : <p className="crm-muted">No pending follow-ups are available.</p>}<Link className="crm-action" to="/outreach?tab=followups">Manage follow-ups</Link></GlassCard>
      <GlassCard className="crm-panel"><div className="crm-heading"><div><h2>Activity timeline</h2><p>Recorded follow-up and call events.</p></div><Activity size={17}/></div>{activities.length ? <div className="crm-list">{activities.slice(0, 12).map(item => <div key={`${item.label}-${item.id}`}><strong>{item.label} · {leadNames.get(item.leadId) || item.leadId}</strong><span>{new Date(item.when).toLocaleString()}</span><small>{item.detail}</small></div>)}</div> : <p className="crm-muted">No recorded activity is available.</p>}</GlassCard></div></div>
    </>}
  </>
}
