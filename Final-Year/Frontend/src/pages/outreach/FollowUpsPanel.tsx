import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { CalendarClock, Check, ChevronLeft, ChevronRight, Plus, X } from 'lucide-react'
import { Badge, Button, EmptyState, GlassCard, Input, LoadingState, Modal, Select, useToast } from '../../components/ui'
import { leadService, type LeadListItem } from '../../services/leads'
import { isApiConfigured } from '../../services/api'
import { outreachService, type FollowUpItem, type FollowUpStatus, type FollowUpPage } from '../../services/outreach'
import { classifyApiError, type ApiFailure } from '../../utils/apiErrors'

const PAGE_SIZE = 25
type ViewState = 'idle' | 'loading' | 'success' | 'empty' | 'error' | 'connection-required'
export function FollowUpsPanel() {
  const [items, setItems] = useState<FollowUpPage | null>(null)
  const [state, setState] = useState<ViewState>(isApiConfigured ? 'loading' : 'connection-required')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [leads, setLeads] = useState<LeadListItem[]>([])
  const [leadLoadError, setLeadLoadError] = useState('')
  const [filterStatus, setFilterStatus] = useState<FollowUpStatus | ''>('')
  const [query, setQuery] = useState<{ limit: number; offset: number; status?: FollowUpStatus }>({ limit: PAGE_SIZE, offset: 0 })
  const [createOpen, setCreateOpen] = useState(false)
  const [leadId, setLeadId] = useState('')
  const [scheduledAt, setScheduledAt] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID())
  const [pendingChange, setPendingChange] = useState<{ item: FollowUpItem; status: FollowUpStatus } | null>(null)
  const toast = useToast()

  const load = useCallback(async (params: { limit: number; offset: number; status?: FollowUpStatus }) => {
    if (!isApiConfigured) { setState('connection-required'); return }
    setState('loading'); setError(null)
    try {
      const result = await outreachService.followUps(params)
      setItems(result); setQuery(params); setState(result.follow_ups.length ? 'success' : 'empty')
    } catch (cause) { setError(classifyApiError(cause)); setState('error') }
  }, [])

  useEffect(() => {
    if (!isApiConfigured) return
    let active = true
    void leadService.list({ limit: 100, offset: 0 }).then(result => {
      if (!active) return
      setLeads(result.leads); setLeadId(result.leads[0]?.lead_id ?? '')
    }).catch(cause => { if (active) setLeadLoadError(classifyApiError(cause).message) })
    void load({ limit: PAGE_SIZE, offset: 0 })
    return () => { active = false }
  }, [load])

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setFormError('')
    if (!leadId) { setFormError('Choose a lead.'); return }
    if (!scheduledAt || Number.isNaN(new Date(scheduledAt).getTime())) { setFormError('Choose a valid date and time.'); return }
    setBusy(true)
    try {
      await outreachService.createFollowUp({ lead_id: leadId, scheduled_at: new Date(scheduledAt).toISOString(), notes: notes.trim() || undefined, idempotency_key: idempotencyKey })
      setCreateOpen(false); setScheduledAt(''); setNotes(''); setIdempotencyKey(crypto.randomUUID())
      toast.push({ title: 'Follow-up created', description: 'The backend saved your follow-up.', tone: 'success' })
      await load(query)
    } catch (cause) {
      setFormError(classifyApiError(cause).message)
      toast.push({ title: 'Follow-up not saved', description: classifyApiError(cause).message, tone: 'error' })
    } finally { setBusy(false) }
  }

  async function confirmStatusChange() {
    if (!pendingChange) return
    setBusy(true)
    try {
      await outreachService.updateFollowUp(pendingChange.item.follow_up_id, { status: pendingChange.status })
      toast.push({ title: `Follow-up ${pendingChange.status}`, description: 'The backend updated the follow-up status.', tone: 'success' })
      setPendingChange(null); await load(query)
    } catch (cause) {
      const message = classifyApiError(cause).message
      toast.push({ title: 'Status update failed', description: message, tone: 'error' })
      setError(classifyApiError(cause)); setState('error'); setPendingChange(null)
    } finally { setBusy(false) }
  }

  function applyFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void load({ limit: PAGE_SIZE, offset: 0, status: filterStatus || undefined })
  }

  const pageEnd = items ? Math.min(query.offset + items.follow_ups.length, items.total) : 0
  return <div className="followups-center">
    <div className="followups-summary"><div className="followups-summary-icon"><CalendarClock size={18}/></div><div><h2>Keep the conversation moving</h2><p>Follow-ups are saved to the reviewer follow-up ledger.</p></div><Button variant="primary" disabled={!isApiConfigured || leads.length === 0} title={!isApiConfigured ? 'Connect a trusted API/BFF to enable follow-ups.' : leads.length === 0 ? 'No leads are available for a follow-up.' : undefined} onClick={() => { setFormError(''); setCreateOpen(true) }}><Plus size={15}/> Create follow-up</Button></div>
    {leadLoadError && <div className="auth-feedback error followup-lead-error" role="alert">Lead selector unavailable: {leadLoadError}</div>}
    <div className="followups-section-heading"><div><span className="eyebrow">YOUR QUEUE</span><h2>Follow-ups</h2></div><form onSubmit={applyFilter} className="followup-filter"><Select aria-label="Filter follow-ups by status" value={filterStatus} onChange={event => setFilterStatus(event.target.value as FollowUpStatus | '')}><option value="">All statuses</option><option value="pending">Pending</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></Select><Button size="sm" variant="secondary" type="submit" loading={state === 'loading'} disabled={state === 'loading'}>Filter</Button></form></div>
    {state === 'loading' && <GlassCard className="followup-loading"><LoadingState label="Loading follow-ups"/><div>{Array.from({ length: 3 }, (_, i) => <div key={i} className="followup-skeleton"><span className="skeleton title-skeleton"/><span className="skeleton text-skeleton"/><span className="skeleton text-skeleton"/></div>)}</div></GlassCard>}
    {state === 'connection-required' && <GlassCard className="outreach-state-card"><EmptyState icon={CalendarClock} title="Secure follow-up connection required" description="Follow-ups require reviewer authorization through a trusted API/BFF."/></GlassCard>}
    {state === 'error' && <GlassCard className="outreach-state-card"><EmptyState title="Follow-ups unavailable" description={error?.message ?? 'Try again shortly.'} action={<Button variant="secondary" onClick={() => void load(query)}>Try again</Button>}/></GlassCard>}
    {state === 'empty' && <GlassCard className="outreach-state-card"><EmptyState icon={CalendarClock} title="Your follow-up queue is clear" description="Follow-ups created for leads in this workspace will appear here."/></GlassCard>}
    {state === 'success' && items && <><div className="followup-list">{items.follow_ups.map(item => <FollowUpCard key={item.follow_up_id} item={item} onChange={status => setPendingChange({ item, status })}/>)}</div><div className="lead-pagination"><span>Showing {query.offset + 1}–{pageEnd} of {items.total}</span><div><Button size="sm" variant="secondary" disabled={query.offset === 0} onClick={() => void load({ ...query, offset: Math.max(0, query.offset - PAGE_SIZE) })}><ChevronLeft size={15}/> Previous</Button><Button size="sm" variant="secondary" disabled={pageEnd >= items.total} onClick={() => void load({ ...query, offset: query.offset + PAGE_SIZE })}>Next <ChevronRight size={15}/></Button></div></div></>}

    <Modal open={createOpen} title="Create follow-up" onClose={() => { if (!busy) setCreateOpen(false) }}><form className="lead-action-form" onSubmit={create}><label>Lead<select className="input" value={leadId} onChange={e => setLeadId(e.target.value)} required><option value="">Choose a lead</option>{leads.map(lead => <option key={lead.lead_id} value={lead.lead_id}>{lead.business_name || lead.lead_id}</option>)}</select></label><label>Date and time<Input type="datetime-local" value={scheduledAt} onChange={e => setScheduledAt(e.target.value)} required/></label><label>Notes <small>(optional, up to 4,000 characters)</small><textarea className="input follow-up-notes" value={notes} onChange={e => setNotes(e.target.value)} maxLength={4000} placeholder="Add context for your teammate"/></label>{formError && <div className="auth-feedback error" role="alert">{formError}</div>}<div className="lead-modal-actions"><Button type="button" variant="ghost" disabled={busy} onClick={() => setCreateOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={busy} disabled={busy}>{busy ? 'Saving…' : 'Save follow-up'}</Button></div></form></Modal>
    <Modal open={Boolean(pendingChange)} title="Update follow-up status" onClose={() => { if (!busy) setPendingChange(null) }}><div className="followup-confirm"><p>Change this follow-up to <strong>{pendingChange?.status}</strong>? The update will be recorded by the backend.</p><div className="lead-modal-actions"><Button variant="ghost" disabled={busy} onClick={() => setPendingChange(null)}>Keep as is</Button><Button variant="primary" loading={busy} disabled={busy} onClick={() => void confirmStatusChange()}>{busy ? 'Updating…' : 'Confirm update'}</Button></div></div></Modal>
  </div>
}

function FollowUpCard({ item, onChange }: { item: FollowUpItem; onChange: (status: FollowUpStatus) => void }) {
  const statusTone = item.status === 'completed' ? 'green' : item.status === 'cancelled' ? 'red' : 'neutral'
  return <GlassCard className="followup-card"><div className="followup-card-top"><div className="followup-card-icon"><CalendarClock size={16}/></div><div className="followup-card-main"><div className="followup-card-title"><strong>{formatDate(item.scheduled_at)}</strong><Badge tone={statusTone}>{item.status}</Badge></div><span>Lead {item.lead_id}</span></div><span className="followup-id">{item.follow_up_id}</span></div><div className="followup-detail-grid"><div><span>Notes</span><p>{item.notes || 'No notes'}</p></div><div><span>Related call</span><p>{item.related_call_id || 'None'}</p></div><div><span>Assigned reviewer</span><p>{item.assigned_reviewer || 'Unassigned'}</p></div><div><span>Created / updated</span><p>{formatDate(item.created_at)}<br/>{formatDate(item.updated_at)}</p></div></div>{item.status === 'pending' && <div className="followup-card-actions"><Button size="sm" variant="ghost" onClick={() => onChange('cancelled')}><X size={13}/> Cancel follow-up</Button><Button size="sm" variant="secondary" onClick={() => onChange('completed')}><Check size={13}/> Mark complete</Button></div>}</GlassCard>
}
function formatDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) }
