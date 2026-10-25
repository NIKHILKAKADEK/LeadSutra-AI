import { useCallback, useEffect, useState } from 'react'
import { Activity, AudioLines, Globe2, Phone, RefreshCw, TrendingUp, Users } from 'lucide-react'
import { Badge, Button, EmptyState, GlassCard, LoadingState, useToast } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'
import { analyticsService, type AnalyticsOverview } from '../services/analytics'
import { classifyApiError } from '../utils/apiErrors'

export function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastUpdated, setLastUpdated] = useState('')
  const toast = useToast()

  const refresh = useCallback(async (notify = false) => {
    setLoading(true)
    setError('')
    try {
      const result = await analyticsService.overview()
      setData(result)
      setLastUpdated(result.generated_at)
      if (notify) toast.push({ title: 'Analytics refreshed', description: 'Showing the latest saved backend activity.', tone: 'success' })
    } catch (cause) {
      const message = classifyApiError(cause).message
      setError(message)
      if (notify) toast.push({ title: 'Analytics unavailable', description: message, tone: 'error' })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 30_000)
    return () => window.clearInterval(timer)
  }, [refresh])

  return <>
    <PageHeader eyebrow="PERFORMANCE" title="Analytics" description="Live totals from your saved leads and outreach." actions={<Button variant="secondary" disabled={loading} onClick={() => void refresh(true)}><RefreshCw size={14} className={loading ? 'spin' : ''}/> Refresh</Button>} />
    {error && <GlassCard className="analytics-error"><EmptyState icon={Activity} title="Could not load analytics" description={error} action={<Button variant="secondary" onClick={() => void refresh(true)}>Try again</Button>} /></GlassCard>}
    {loading && !data ? <GlassCard className="analytics-loading"><LoadingState label="Loading live analytics" /></GlassCard> : data && <>
      <div className="analytics-live-meta"><Badge>LIVE</Badge><span>Updated {lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : 'just now'} · refreshes every 30 seconds</span></div>
      <section className="analytics-live-metrics" aria-label="Live analytics summary">
        <Metric icon={Users} label="Saved leads" value={data.leads_total} />
        <Metric icon={TrendingUp} label="High priority" value={data.high_priority_leads} />
        <Metric icon={Activity} label="Qualified" value={data.qualified_leads} />
        <Metric icon={Globe2} label="With website" value={data.websites_total} />
        <Metric icon={AudioLines} label="Emails sent" value={`${data.emails_sent} / ${data.emails_total}`} />
        <Metric icon={Phone} label="Calls dispatched" value={`${data.calls_dispatched} / ${data.calls_total}`} />
      </section>
      <section className="analytics-live-grid">
        <GlassCard className="analytics-live-card"><header><div><h2>Recently updated leads</h2><p>Newest records first</p></div><Users size={18}/></header>
          {data.recent_leads.length ? <div className="analytics-table-wrap"><table><thead><tr><th>Business</th><th>Category</th><th>Score</th><th>Priority</th></tr></thead><tbody>{data.recent_leads.map(lead => <tr key={lead.lead_id}><td>{lead.business_name}</td><td>{lead.category || '—'}</td><td>{lead.lead_score ?? '—'}</td><td><span className={`analytics-priority ${lead.priority.toLowerCase().replaceAll(' ', '-')}`}>{lead.priority}</span></td></tr>)}</tbody></table></div> : <p className="analytics-empty-message">No saved leads yet.</p>}
        </GlassCard>
        <ActivityList title="Recent emails" icon={AudioLines} items={data.recent_emails} empty="No email activity yet." />
        <ActivityList title="Recent calls" icon={Phone} items={data.recent_calls} empty="No call activity yet." />
      </section>
    </>}
  </>
}

function Metric({ icon: Icon, label, value }: { icon: typeof Users; label: string; value: string | number }) {
  return <GlassCard className="analytics-live-metric"><span><Icon size={19}/></span><strong>{value}</strong><small>{label}</small></GlassCard>
}

function ActivityList({ title, icon: Icon, items, empty }: { title: string; icon: typeof AudioLines; items: AnalyticsOverview['recent_emails']; empty: string }) {
  return <GlassCard className="analytics-live-card"><header><div><h2>{title}</h2><p>Latest backend records</p></div><Icon size={18}/></header>
    {items.length ? <ul className="analytics-activity-list">{items.map(item => <li key={item.id}><span><strong>{item.label}</strong><small>{item.created_at ? new Date(item.created_at).toLocaleString() : 'Time unavailable'}</small></span><Badge>{item.status.replaceAll('_', ' ')}</Badge></li>)}</ul> : <p className="analytics-empty-message">{empty}</p>}
  </GlassCard>
}
