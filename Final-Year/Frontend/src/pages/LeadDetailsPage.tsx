import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowUpRight, CalendarClock, Mail, MapPin, Phone, PhoneCall, Plus, Sparkles, Target, UserRound } from 'lucide-react'
import { Button, EmptyState, GlassCard, Input, Modal, useToast } from '../components/ui'
import { leadService, type LeadDetails } from '../services/leads'
import { classifyApiError, type ApiFailure } from '../utils/apiErrors'
import { ScoreBadge, StatusBadge } from './leadComponents'
import { StoredLeadDetailsPage } from './StoredLeadDetailsPage'

type PageState = 'loading' | 'success' | 'connection-required' | 'network-error' | 'server-error'
export function LeadDetailsPage() {
  const [searchParams] = useSearchParams()
  return searchParams.has('source') ? <StoredLeadDetailsPage /> : <ApiLeadDetailsPage />
}

function ApiLeadDetailsPage() {
  const { leadId = '' } = useParams()
  const [state, setState] = useState<PageState>(leadService.isConfigured ? 'loading' : 'connection-required')
  const [retry, setRetry] = useState(0)
  const [lead, setLead] = useState<LeadDetails | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [followUpOpen, setFollowUpOpen] = useState(false)
  const [followUpDate, setFollowUpDate] = useState('')
  const [followUpNotes, setFollowUpNotes] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState('')
  const toast = useToast()

  useEffect(() => {
    let active = true
    if (!leadService.isConfigured) { setState('connection-required'); return () => { active = false } }
    setState('loading'); setError(null)
    void leadService.details(leadId).then(data => { if (active) { setLead(data); setState('success') } }).catch(cause => {
      if (active) { const failure = classifyApiError(cause); setError(failure); setState(failure.kind) }
    })
    return () => { active = false }
  }, [leadId, retry])

  async function createFollowUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setActionError('')
    if (!followUpDate) { setActionError('Choose a date and time.'); return }
    const scheduled = new Date(followUpDate)
    if (Number.isNaN(scheduled.getTime())) { setActionError('Enter a valid date and time.'); return }
    setActionLoading(true)
    try {
      await leadService.createFollowUp({ lead_id: leadId, scheduled_at: scheduled.toISOString(), notes: followUpNotes.trim() || undefined, idempotency_key: crypto.randomUUID() })
      setFollowUpOpen(false); setFollowUpDate(''); setFollowUpNotes('')
      toast.push({ title: 'Follow-up created', description: 'Your scheduled follow-up was saved.', tone: 'success' })
    } catch (cause) { setActionError(classifyApiError(cause).message) }
    finally { setActionLoading(false) }
  }

  if (state === 'loading') return <LeadDetailSkeleton/>
  if (state !== 'success' || !lead) return <div className="lead-detail-page"><Link to="/leads" className="back-to-leads"><ArrowLeft size={15}/> Back to leads</Link><GlassCard className="lead-state-card"><EmptyState title={state === 'connection-required' ? 'Secure lead connection required' : state === 'network-error' ? 'Connection interrupted' : 'Lead details unavailable'} description={state === 'connection-required' ? 'Configure a trusted API/BFF session to read protected lead details.' : error?.message ?? 'This record may be unavailable.'} action={state !== 'connection-required' ? <Button variant="secondary" onClick={() => setRetry(value => value + 1)}>Try again</Button> : undefined}/></GlassCard></div>

  return <div className="lead-detail-page">
    <Link to="/leads" className="back-to-leads"><ArrowLeft size={15}/> Back to leads</Link>
    <div className="lead-detail-heading"><div className="detail-business-avatar"><UserRound size={22}/></div><div className="lead-detail-title"><span className="eyebrow">LEAD RECORD</span><h1>{lead.business_name || 'Unnamed business'}</h1><p>{lead.category || 'Category unavailable'} <span>·</span> {lead.lead_id}</p></div><div className="lead-detail-actions"><Link className="button button-secondary" to={`/leads/${encodeURIComponent(lead.lead_id)}?source=stored`}><Sparkles size={15}/> Business research</Link><Link className="button button-secondary" to={`/outreach?lead_id=${encodeURIComponent(lead.lead_id)}`}><Mail size={15}/> Email</Link><Link className="button button-secondary" to={`/calls?lead_id=${encodeURIComponent(lead.lead_id)}`}><PhoneCall size={15}/> Check and call</Link><Button variant="primary" disabled={!leadService.isConfigured} title={!leadService.isConfigured ? 'Connect a trusted API/BFF to enable protected actions.' : undefined} onClick={() => { setActionError(''); setFollowUpOpen(true) }}><Plus size={15}/> Create Follow-up</Button></div></div>

    <section className="lead-detail-grid">
      <div className="lead-detail-main">
        <GlassCard className="detail-section"><SectionTitle icon={<Target size={16}/>} title="Business Information"/><div className="detail-fields"><DetailField label="Business name" value={lead.business_name}/><DetailField label="Category" value={lead.category}/><div className="detail-field"><span>Website</span><Website value={lead.website}/></div><DetailField label="Address" value={lead.address} icon={<MapPin size={13}/>}/></div></GlassCard>
        <GlassCard className="detail-section"><SectionTitle icon={<UserRound size={16}/>} title="Contact Information"/><div className="detail-contact-block"><h3>Contact names</h3>{lead.contact_names.length ? lead.contact_names.map(name => <p key={name}>{name}</p>) : <p className="detail-muted">No contact names were returned by the backend.</p>}</div><div className="detail-contact-block"><h3>Phone numbers</h3>{lead.phone_numbers.length ? <div className="detail-phone-list">{lead.phone_numbers.map(phone => <a key={phone} href={`tel:${phone}`}><Phone size={14}/>{phone}</a>)}</div> : <p className="detail-muted">No phone numbers were returned.</p>}</div><div className="detail-contact-block"><h3>Email addresses</h3>{lead.email_addresses.length ? lead.email_addresses.map(email => <p key={email}><a href={`mailto:${email}`}>{email}</a></p>) : <p className="detail-muted">No email addresses were returned.</p>}</div></GlassCard>
      </div>
      <aside className="lead-detail-aside"><GlassCard className="detail-section qualification-card"><SectionTitle icon={<Sparkles size={16}/>} title="Qualification"/><div className="detail-qualification-status"><span>Backend status</span><StatusBadge status={lead.qualification_status}/></div><div className="detail-score-wrap"><div className="detail-score-heading"><span>Lead score</span><span>As returned by backend</span></div><ScoreBadge score={lead.lead_score}/></div></GlassCard><GlassCard className="detail-aside-note"><CalendarClock size={16}/><p>Follow-ups are stored with an ISO timestamp and generated idempotency key.</p></GlassCard></aside>
    </section>

    <Modal open={followUpOpen} title="Create follow-up" onClose={() => { if (!actionLoading) setFollowUpOpen(false) }}><form className="lead-action-form" onSubmit={createFollowUp}><p>Schedule a follow-up for <strong>{lead.business_name || 'this lead'}</strong>.</p><label>Date and time<Input type="datetime-local" required value={followUpDate} onChange={e => setFollowUpDate(e.target.value)}/></label><label>Notes <small>(optional, up to 4,000 characters)</small><textarea className="input follow-up-notes" maxLength={4000} value={followUpNotes} onChange={e => setFollowUpNotes(e.target.value)} placeholder="Add context for the follow-up"/></label>{actionError && <div className="auth-feedback error" role="alert">{actionError}</div>}<div className="lead-modal-actions"><Button variant="ghost" type="button" disabled={actionLoading} onClick={() => setFollowUpOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={actionLoading} disabled={actionLoading}>{actionLoading ? 'Saving…' : 'Save follow-up'}</Button></div></form></Modal>

  </div>
}

function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) { return <div className="detail-section-title"><span>{icon}</span><h2>{title}</h2></div> }
function DetailField({ label, value, icon }: { label: string; value: string | null; icon?: React.ReactNode }) { return <div className="detail-field"><span>{icon}{label}</span><strong>{value || '—'}</strong></div> }
function Website({ value }: { value: string | null }) { if (!value) return <strong>—</strong>; try { const url = new URL(value); if (url.protocol !== 'http:' && url.protocol !== 'https:') return <strong>{value}</strong>; return <a className="website-link" href={url.href} target="_blank" rel="noreferrer">{value}<ArrowUpRight size={13}/></a> } catch { return <strong>{value}</strong> } }
function LeadDetailSkeleton() { return <div className="lead-detail-page"><Link to="/leads" className="back-to-leads"><ArrowLeft size={15}/> Back to leads</Link><GlassCard className="detail-skeleton-head"><span className="skeleton avatar-skeleton"/><div><span className="skeleton title-skeleton"/><span className="skeleton text-skeleton"/></div></GlassCard><div className="lead-detail-grid"><div className="lead-detail-main"><GlassCard className="detail-skeleton-card"><span className="skeleton title-skeleton"/><span className="skeleton text-skeleton"/><span className="skeleton text-skeleton"/><span className="skeleton text-skeleton"/></GlassCard><GlassCard className="detail-skeleton-card"><span className="skeleton title-skeleton"/><span className="skeleton text-skeleton"/><span className="skeleton text-skeleton"/></GlassCard></div><GlassCard className="detail-skeleton-card"><span className="skeleton title-skeleton"/><span className="skeleton text-skeleton"/><span className="skeleton score-skeleton"/></GlassCard></div></div> }
