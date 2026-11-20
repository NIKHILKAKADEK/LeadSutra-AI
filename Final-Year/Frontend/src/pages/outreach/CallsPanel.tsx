import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Activity, AlertCircle, ChevronLeft, ChevronRight, Clock3, PhoneCall } from 'lucide-react'
import { Badge, Button, EmptyState, GlassCard, LoadingState, Select, Skeleton, useToast } from '../../components/ui'
import { leadService, type LeadListItem } from '../../services/leads'
import { isApiConfigured } from '../../services/api'
import { outreachService, type CallDispatchResult, type CallDispatchStatus, type CallHistoryItem, type CallHistoryPage } from '../../services/outreach'
import { classifyApiError, type ApiFailure } from '../../utils/apiErrors'

const PAGE_SIZE = 25
const dispatchStatuses: CallDispatchStatus[] = ['blocked', 'dry_run', 'dispatching', 'dispatched', 'duplicate', 'provider_error', 'uncertain']
type ViewState = 'idle' | 'loading' | 'success' | 'empty' | 'error' | 'connection-required'

export function CallsPanel() {
  const [searchParams] = useSearchParams()
  const requestedLeadId = searchParams.get('lead_id') || ''
  const [leads, setLeads] = useState<LeadListItem[]>([])
  const [leadState, setLeadState] = useState<ViewState>(isApiConfigured ? 'loading' : 'connection-required')
  const [leadError, setLeadError] = useState<ApiFailure | null>(null)
  const [leadId, setLeadId] = useState('')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [dispatching, setDispatching] = useState(false)
  const [dispatchResult, setDispatchResult] = useState<CallDispatchResult | null>(null)
  const [dispatchError, setDispatchError] = useState('')
  const toast = useToast()
  const [historyState, setHistoryState] = useState<ViewState>(isApiConfigured ? 'loading' : 'connection-required')
  const [history, setHistory] = useState<CallHistoryPage | null>(null)
  const [historyError, setHistoryError] = useState<ApiFailure | null>(null)
  const [filters, setFilters] = useState<{ lead_id: string; dispatch_status: CallDispatchStatus | '' }>({ lead_id: '', dispatch_status: '' })
  const [query, setQuery] = useState<{ limit: number; offset: number; lead_id?: string; dispatch_status?: CallDispatchStatus }>({ limit: PAGE_SIZE, offset: 0 })

  const loadHistory = useCallback(async (params: { limit: number; offset: number; lead_id?: string; dispatch_status?: CallDispatchStatus }) => {
    if (!isApiConfigured) { setHistoryState('connection-required'); return }
    setHistoryState('loading'); setHistoryError(null)
    try {
      const page = await outreachService.callHistory(params)
      setHistory(page); setQuery(params); setHistoryState(page.calls.length ? 'success' : 'empty')
    } catch (cause) { setHistoryError(classifyApiError(cause)); setHistoryState('error') }
  }, [])

  useEffect(() => {
    if (!isApiConfigured) return
    let active = true
    void leadService.list({ limit: 100, offset: 0 }).then(response => {
      if (!active) return
      setLeads(response.leads); setLeadState(response.leads.length ? 'success' : 'empty')
      const requested = response.leads.find(lead => lead.lead_id === requestedLeadId)
      const initial = requested ?? response.leads[0]
      if (initial) { setLeadId(initial.lead_id); setPhoneNumber(initial.phone_numbers[0] ?? '') }
    }).catch(cause => { if (active) { setLeadError(classifyApiError(cause)); setLeadState('error') } })
    void loadHistory({ limit: PAGE_SIZE, offset: 0 })
    return () => { active = false }
  }, [loadHistory, requestedLeadId])

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void loadHistory({ limit: PAGE_SIZE, offset: 0, lead_id: filters.lead_id || undefined, dispatch_status: filters.dispatch_status || undefined })
  }

  const selectedLead = leads.find(item => item.lead_id === leadId)
  const pageEnd = history ? Math.min(query.offset + history.calls.length, history.total) : 0
  return <div className="calls-center">
    <div className="calls-top-grid">
      <GlassCard className="call-check-card"><div className="outreach-card-title"><span className="outreach-icon"><PhoneCall size={16}/></span><div><h2>Outbound call</h2><p>Dispatch one call through OmniDimension</p></div></div>
        <div className="call-select-grid"><label>Lead<select className="input" value={leadId} disabled={leadState !== 'success'} onChange={event => { const nextLead = leads.find(item => item.lead_id === event.target.value); setLeadId(event.target.value); setPhoneNumber(nextLead?.phone_numbers[0] ?? '') }}><option value="">Select a lead</option>{leads.map(lead => <option key={lead.lead_id} value={lead.lead_id}>{lead.business_name || lead.lead_id}</option>)}</select></label><label>Phone number<select className="input" value={phoneNumber} disabled={!selectedLead?.phone_numbers.length} onChange={event => setPhoneNumber(event.target.value)}><option value="">Select a phone</option>{selectedLead?.phone_numbers.map(phone => <option key={phone} value={phone}>{phone}</option>)}</select></label></div>
        {leadState === 'loading' && <div className="call-lead-loading"><LoadingState label="Loading leads"/></div>}{leadState === 'error' && <p className="inline-error"><AlertCircle size={12}/>{leadError?.message}</p>}{leadState === 'empty' && <p className="eligibility-hint">No lead records were returned by the backend.</p>}{leadState === 'connection-required' && <p className="eligibility-hint">Sign in and connect to the backend to place an outbound call.</p>}
        <p className="call-safety-note">Calls use the configured OmniDimension agent and API key.</p>
        <Button className="call-disabled-action" variant="primary" loading={dispatching} disabled={!leadId || !phoneNumber || dispatching} onClick={() => void dispatchCall()}><PhoneCall size={14}/> {dispatching ? 'Starting call…' : 'Start AI call'}</Button>
        {dispatchError && <p className="inline-error" role="alert"><AlertCircle size={12}/>{dispatchError}</p>}
        {dispatchResult && <div className="dispatch-result" aria-live="polite"><Badge>{dispatchResult.status}</Badge><span>{dispatchResult.dispatched ? 'The backend accepted the call dispatch.' : 'The backend did not dispatch the call.'}</span><small>Lead: {dispatchResult.lead_id} · Phone: {dispatchResult.normalized_phone_number || phoneNumber}{dispatchResult.agent_id ? ` · Agent: ${dispatchResult.agent_id}` : ''}</small>{dispatchResult.provider_request_id && <small>Provider request: {dispatchResult.provider_request_id}</small>}{dispatchResult.reason_codes.length > 0 && <small>Reason: {dispatchResult.reason_codes.join(', ')}</small>}</div>}
      </GlassCard>
      <GlassCard className="call-history-summary"><div className="outreach-card-title"><span className="outreach-icon violet"><Activity size={16}/></span><div><h2>Call history</h2><p>Outbound dispatches, most recent first</p></div><Badge>{history ? `${history.total} RECORDS` : 'LIVE DATA'}</Badge></div><div className="call-summary-facts"><div><span>Selected lead</span><strong>{selectedLead?.business_name || (leadId ? leadId : 'All leads')}</strong></div><div><span>Selected phone</span><strong>{phoneNumber || 'Choose a phone number'}</strong></div></div><div className="call-duration-note"><Clock3 size={13}/> The call-history schema does not include duration.</div></GlassCard>
    </div>

    <section className="call-history-section"><div className="outreach-section-heading"><div><span className="eyebrow">CALL ACTIVITY</span><h2>Recent call history</h2></div></div>
      <GlassCard className="call-history-filter"><form onSubmit={applyFilters}><label>Lead<select className="input" value={filters.lead_id} onChange={e => setFilters(value => ({ ...value, lead_id: e.target.value }))}><option value="">All leads</option>{leads.map(lead => <option value={lead.lead_id} key={lead.lead_id}>{lead.business_name || lead.lead_id}</option>)}</select></label><label>Call status<Select value={filters.dispatch_status} onChange={e => setFilters(value => ({ ...value, dispatch_status: e.target.value as CallDispatchStatus | '' }))}><option value="">All statuses</option>{dispatchStatuses.map(status => <option value={status} key={status}>{status.replaceAll('_', ' ')}</option>)}</Select></label><Button variant="secondary" type="submit" loading={historyState === 'loading'} disabled={historyState === 'loading'}>Apply filters</Button></form></GlassCard>
      {historyState === 'loading' && <CallHistorySkeleton/>}
      {historyState === 'connection-required' && <GlassCard className="outreach-state-card"><EmptyState icon={Activity} title="Sign in to view call history" description="Outbound call records are available through your signed-in session."/></GlassCard>}
      {historyState === 'error' && <GlassCard className="outreach-state-card"><EmptyState title="Call history unavailable" description={historyError?.message ?? 'Try again in a moment.'} action={<Button variant="secondary" onClick={() => void loadHistory(query)}>Try again</Button>}/></GlassCard>}
      {historyState === 'empty' && <GlassCard className="outreach-state-card"><EmptyState icon={Activity} title="No call records found" description="Call history will appear here when the backend has records matching these filters."/></GlassCard>}
      {historyState === 'success' && history && <><CallHistoryTable calls={history.calls}/><div className="lead-pagination"><span>Showing {query.offset + 1}–{pageEnd} of {history.total}</span><div><Button size="sm" variant="secondary" disabled={query.offset === 0} onClick={() => void loadHistory({ ...query, offset: Math.max(0, query.offset - PAGE_SIZE) })}><ChevronLeft size={15}/> Previous</Button><Button size="sm" variant="secondary" disabled={pageEnd >= history.total} onClick={() => void loadHistory({ ...query, offset: query.offset + PAGE_SIZE })}>Next <ChevronRight size={15}/></Button></div></div></>}
    </section>
  </div>

  async function dispatchCall() {
    if (!leadId || !phoneNumber || dispatching) return
    setDispatching(true); setDispatchError(''); setDispatchResult(null)
    try {
      const result = await outreachService.dispatchCall({ lead_id: leadId, phone_number: phoneNumber, idempotency_key: crypto.randomUUID(), confirmed: true })
      setDispatchResult(result)
      toast.push({ title: `Call ${result.status}`, description: result.dispatched ? 'The backend accepted the dispatch request.' : 'The backend returned a non-dispatched result.', tone: result.dispatched ? 'success' : 'info' })
      void loadHistory(query)
    } catch (cause) {
      const message = classifyApiError(cause).message
      setDispatchError(message)
      toast.push({ title: 'Call not dispatched', description: message, tone: 'error' })
    }
    finally { setDispatching(false) }
  }
}

function CallHistoryTable({ calls }: { calls: CallHistoryItem[] }) {
  return <GlassCard className="call-history-table-card"><div className="call-history-table-scroll"><table className="call-history-table"><thead><tr><th>Call status</th><th>Timestamp</th><th>Lead</th><th>Phone</th><th>Result</th></tr></thead><tbody>{calls.map(call => <tr key={call.call_id}><td><CallStatus status={call.dispatch_status}/></td><td>{formatDate(call.created_at)}</td><td className="call-lead-id">{call.lead_id}</td><td>{call.phone_number}</td><td>{call.call_outcome}</td></tr>)}</tbody></table></div><div className="call-history-mobile">{calls.map(call => <article className="call-mobile-card" key={call.call_id}><div><CallStatus status={call.dispatch_status}/><time>{formatDate(call.created_at)}</time></div><p>{call.phone_number}</p><small>Lead {call.lead_id}</small><span>Result: {call.call_outcome}</span></article>)}</div></GlassCard>
}
function CallStatus({ status }: { status: string }) { const tone = status === 'dispatched' ? 'green' : status === 'blocked' || status === 'provider_error' ? 'red' : status === 'dry_run' || status === 'dispatching' ? 'neutral' : 'neutral'; return <Badge tone={tone}>{status.replaceAll('_', ' ')}</Badge> }
function CallHistorySkeleton() { return <GlassCard className="call-history-skeleton">{Array.from({ length: 5 }, (_, index) => <div key={index}><Skeleton className="status-skeleton"/><Skeleton className="time-skeleton"/><Skeleton className="lead-skeleton"/><Skeleton className="phone-skeleton"/></div>)}</GlassCard> }
function formatDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) }
