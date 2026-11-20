import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Compass, Globe2, Target, Users } from 'lucide-react'
import { Badge, Button, EmptyState, GlassCard, LoadingState, Skeleton } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'
import { businessDiscoveryService, type BusinessLead } from '../services/businessDiscovery'
import { classifyApiError, type ApiFailure } from '../utils/apiErrors'
import { BusinessLeadResults } from './BusinessLeadViews'

type DashboardState = 'loading' | 'success' | 'empty' | 'connection-required' | 'network-error' | 'server-error'

export function DashboardPage() {
  const navigate = useNavigate()
  const [state, setState] = useState<DashboardState>(businessDiscoveryService.isConfigured ? 'loading' : 'connection-required')
  const [leads, setLeads] = useState<BusinessLead[]>([])
  const [error, setError] = useState<ApiFailure | null>(null)

  useEffect(() => {
    let active = true
    if (!businessDiscoveryService.isConfigured) { setState('connection-required'); return () => { active = false } }
    void businessDiscoveryService.list({ min_score: 0, limit: 100 }).then(result => {
      if (active) { setLeads(result); setState(result.length ? 'success' : 'empty') }
    }).catch(cause => {
      if (active) { const failure = classifyApiError(cause); setError(failure); setState(failure.kind) }
    })
    return () => { active = false }
  }, [])

  const highPriority = leads.filter(lead => lead.priority?.toLowerCase() === 'high').length
  const qualified = leads.filter(lead => lead.qualification_status?.toLowerCase() === 'qualified').length
  const websites = leads.filter(lead => Boolean(lead.website)).length
  const priorities = ['high', 'medium', 'low'].map(priority => ({ priority, count: leads.filter(lead => lead.priority?.toLowerCase() === priority).length }))

  return <>
    <PageHeader eyebrow="SALES INTELLIGENCE" title="A clear view of your leads." description="Signals from the stored records returned by your discovery backend." actions={<Button variant="primary" onClick={() => navigate('/discovery')}><Compass size={15} /> Discover businesses</Button>} />
    <div className="dashboard-contract-note"><span>Dashboard API unavailable</span><p>These figures are calculated from the backend’s first 100 returned lead records. The API does not expose dashboard totals, timestamps, or activity history.</p></div>
    {state === 'loading' && <><div className="module-dashboard-metrics">{Array.from({ length: 4 }, (_, index) => <GlassCard className="module-metric-card" key={index}><Skeleton className="metric-loading-line" /><Skeleton className="metric-loading-value" /></GlassCard>)}</div><GlassCard className="module-dashboard-state"><LoadingState label="Loading stored lead records" /></GlassCard></>}
    {state === 'connection-required' && <GlassCard className="module-dashboard-state"><EmptyState icon={Users} title="Connect your discovery backend" description="Dashboard summaries use real lead records. Configure a trusted discovery API/BFF to load them." action={<Button variant="secondary" onClick={() => navigate('/settings')}>Connection settings</Button>} /></GlassCard>}
    {(state === 'network-error' || state === 'server-error') && <GlassCard className="module-dashboard-state"><EmptyState title="Lead data could not be loaded" description={error?.message ?? 'The backend request failed.'} action={<Button variant="secondary" onClick={() => window.location.reload()}>Try again</Button>} /></GlassCard>}
    {(state === 'success' || state === 'empty') && <>
      <section className="module-dashboard-metrics" aria-label="Summary of returned lead records">
        <Metric icon={<Users size={17} />} label="Scored leads loaded" value={String(leads.length)} footnote="From the first 100 backend results" />
        <Metric icon={<Target size={17} />} label="High priority" value={String(highPriority)} footnote="Within the returned records" />
        <Metric icon={<Target size={17} />} label="Qualified" value={String(qualified)} footnote="Status returned by backend" />
        <Metric icon={<Globe2 size={17} />} label="Website available" value={String(websites)} footnote="Within the returned records" />
      </section>
      {state === 'empty' ? <GlassCard className="module-dashboard-state"><EmptyState icon={Users} title="No stored leads yet" description="Run a business search and save results to populate your workspace." action={<Button variant="primary" onClick={() => navigate('/discovery')}><Compass size={15} /> Start discovery</Button>} /></GlassCard> : <>
        <section className="module-dashboard-grid">
          <GlassCard className="module-dashboard-panel"><header><div><span className="eyebrow">LEAD PRIORITY</span><h2>Returned record mix</h2></div><Badge>UP TO 100 RECORDS</Badge></header><div className="priority-bars">{priorities.map(({ priority, count }) => <div className="priority-bar-row" key={priority}><span>{priority}</span><div className="priority-bar-track"><i className={`priority-bar-fill ${priority}`} style={{ width: `${leads.length ? Math.round(count / leads.length * 100) : 0}%` }} /></div><strong>{count}</strong></div>)}</div><p className="module-panel-footnote">Counts come from the priority field returned for each loaded lead.</p></GlassCard>
          <GlassCard className="module-dashboard-panel"><header><div><span className="eyebrow">RECENT ACTIVITY</span><h2>Activity feed</h2></div><Badge>NOT AVAILABLE</Badge></header><EmptyState title="No activity endpoint" description="The backend does not return discovery history or recent user activity." /></GlassCard>
        </section>
        <section className="module-dashboard-leads"><div className="module-section-heading"><div><span className="eyebrow">STORED RECORDS</span><h2>Lead records returned by the API</h2></div><Button variant="ghost" onClick={() => navigate('/leads')}>Open lead manager <ArrowRight size={14} /></Button></div><BusinessLeadResults leads={leads.slice(0, 5)} /></section>
      </>}
    </>}
  </>
}

function Metric({ icon, label, value, footnote }: { icon: React.ReactNode; label: string; value: string; footnote: string }) {
  return <GlassCard className="module-metric-card"><span className="module-metric-icon">{icon}</span><strong>{value}</strong><span className="module-metric-label">{label}</span><small>{footnote}</small></GlassCard>
}
