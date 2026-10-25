import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertCircle, Send, Sparkles } from 'lucide-react'
import { Badge, Button, GlassCard, Input, LoadingState } from '../../components/ui'
import { leadService, type LeadListItem } from '../../services/leads'
import { outreachService, type EmailDraft, type EmailResult } from '../../services/outreach'
import { classifyApiError } from '../../utils/apiErrors'
import { useToast } from '../../components/ui'

const EMAIL_TEMPLATE_KEY = 'leadsutra.email-template.v1'
function savedEmailTemplate() {
  try { return window.localStorage.getItem(EMAIL_TEMPLATE_KEY) }
  catch { return null }
}
const DEFAULT_EMAIL_TEMPLATE = `Dear {{business_name}} Team,

I hope you’re doing well.

My name is {{sender_name}}, and I’m reaching out on behalf of {{company_name}}. I came across {{business_name}} and wanted to introduce our services and explore whether we could help your business improve customer acquisition, lead management, and operational efficiency.

At {{company_name}}, we focus on AI-powered solutions, intelligent automation, and streamlined workflows to reduce repetitive tasks, improve customer engagement, and identify opportunities for growth.

Based on your business type and goals, we could explore:
- Lead Generation: Attract potential customers who may be interested in your products or services.
- Automated Follow-Ups: Help ensure enquiries receive timely follow-ups.
- Customer Engagement: Streamline communication with prospects and existing customers.
- Workflow Automation: Reduce repetitive manual tasks and improve day-to-day efficiency.
- Business-Specific AI Solutions: Identify possible uses of AI and automation for your business challenges.

Explain that we first want to understand their processes, challenges, and growth objectives before recommending an approach. Invite a brief {{intro_call_minutes}}-{{intro_call_minutes_plus_five}} minute conversation. Ask to be directed to the right contact if needed and thank them for their time.

Best regards,
{{sender_name}}
Email: {{sender_email}}
Website: {{website_url}}

Include a polite opt-out sentence. Use this as a structure guide, personalize it with verified business facts and research, and omit optional contact or website lines if no value is configured. Never leave placeholders in the finished email.`

export function EmailComposer() {
  const [searchParams] = useSearchParams()
  const toast = useToast()
  const requestedLeadId = searchParams.get('lead_id') || ''
  const [leads, setLeads] = useState<LeadListItem[]>([])
  const [selectedLead, setSelectedLead] = useState('')
  const [leadState, setLeadState] = useState<'idle' | 'loading' | 'ready' | 'error' | 'unavailable'>(leadService.isConfigured ? 'loading' : 'unavailable')
  const [leadError, setLeadError] = useState('')
  const [draft, setDraft] = useState<EmailDraft | null>(null)
  const [template, setTemplate] = useState(() => savedEmailTemplate() || DEFAULT_EMAIL_TEMPLATE)
  const [templateIsCustomized, setTemplateIsCustomized] = useState(() => Boolean(savedEmailTemplate()))
  const [result, setResult] = useState<EmailResult | null>(null)
  const [actionError, setActionError] = useState('')
  const [busyAction, setBusyAction] = useState<'preview' | 'regenerate' | 'proposal' | 'approve' | 'send' | null>(null)
  const busy = busyAction !== null

  useEffect(() => {
    if (!leadService.isConfigured) return
    let active = true
    setLeadState('loading')
    void leadService.list({ limit: 100, offset: 0 }).then(result => {
      if (!active) return
      setLeads(result.leads)
      setSelectedLead(result.leads.some(lead => lead.lead_id === requestedLeadId) ? requestedLeadId : result.leads[0]?.lead_id ?? '')
      setLeadState('ready')
    }).catch(error => {
      if (!active) return
      setLeadError(classifyApiError(error).message); setLeadState('error')
    })
    return () => { active = false }
  }, [requestedLeadId])

  async function previewEmail(regenerate = false) {
    if (!selectedLead || busy) return
    setBusyAction(regenerate ? 'regenerate' : 'preview'); setActionError(''); setResult(null)
    try {
      const nextDraft = await outreachService.emailPreview(selectedLead, templateIsCustomized ? template : undefined, regenerate, true)
      setDraft(nextDraft)
      if (!templateIsCustomized) setTemplate(nextDraft.template || DEFAULT_EMAIL_TEMPLATE)
    } catch (cause) {
      setDraft(null); setActionError(classifyApiError(cause).message)
    } finally { setBusyAction(null) }
  }

  async function generateProposalAndPreview() {
    if (!selectedLead || busy) return
    setBusyAction('proposal'); setActionError(''); setDraft(null); setResult(null)
    try {
      await outreachService.generateProposal(selectedLead)
      const nextDraft = await outreachService.emailPreview(selectedLead, templateIsCustomized ? template : undefined, false, true)
      setDraft(nextDraft)
      if (!templateIsCustomized) setTemplate(nextDraft.template || DEFAULT_EMAIL_TEMPLATE)
      toast.push({ title: 'Proposal email ready', description: 'Review and approve the generated proposal email before sending.', tone: 'success' })
    } catch (cause) { setActionError(classifyApiError(cause).message) }
    finally { setBusyAction(null) }
  }

  async function approveEmail() {
    if (!draft || busy) return
    setBusyAction('approve'); setActionError('')
    try {
      setDraft(await outreachService.approveEmail({ lead_id: draft.lead_id, review_id: draft.review_id, approved: true, template: templateIsCustomized ? template : undefined, subject: draft.subject, body: draft.body }))
      toast.push({ title: 'Email approved', description: 'The proposal email is approved for this draft.', tone: 'success' })
    } catch (cause) { setActionError(classifyApiError(cause).message) }
    finally { setBusyAction(null) }
  }

  async function sendEmail() {
    if (!draft?.approved || busy) return
    setBusyAction('send'); setActionError('')
    try {
      const sent = await outreachService.sendEmail(draft.lead_id, draft.draft_key)
      setResult(sent)
      toast.push({ title: `Email ${sent.status}`, description: 'The backend recorded the email request.', tone: sent.status === 'sent' ? 'success' : 'info' })
    } catch (cause) { setActionError(classifyApiError(cause).message) }
    finally { setBusyAction(null) }
  }

  return <div className="email-workspace">
    <section className="email-intro"><div className="email-intro-mark"><Sparkles size={18}/></div><div><h2>Outreach email</h2><p>Review, approve, and send.</p></div><Badge>EMAIL</Badge></section>
    <div className="email-layout">
      <GlassCard className="email-composer-card"><div className="email-card-heading"><div><h3>Compose your email</h3><p>Review the personalized message before approving.</p></div><div className="email-status"><span className={`status-dot ${draft?.approved ? 'active' : 'idle'}`}/>{draft?.approved ? 'Approved' : 'Review required'}</div></div>
        <div className="email-fields"><label>Lead<select className="input" value={selectedLead} onChange={e => { setSelectedLead(e.target.value); setDraft(null); setResult(null); setActionError('') }} disabled={leadState !== 'ready'}><option value="">Choose a lead</option>{leads.map(lead => <option value={lead.lead_id} key={lead.lead_id}>{lead.business_name || lead.lead_id}</option>)}</select>{leadState === 'loading' && <small className="email-field-note"><LoadingState label="Loading leads"/></small>}{leadState === 'error' && <small className="inline-error"><AlertCircle size={12}/>{leadError}</small>}{leadState === 'unavailable' && <small className="email-field-note">Connect a trusted API/BFF to load leads.</small>}</label>
          <label>Reusable email template<textarea className="input email-message-editor email-template-editor" value={template} onChange={event => { setTemplate(event.target.value); setTemplateIsCustomized(true); try { window.localStorage.setItem(EMAIL_TEMPLATE_KEY, event.target.value) } catch { /* browser storage may be disabled */ } }}/><small className="email-field-note">Edit the template and it will be saved in this browser. Regenerate to have the LLM personalize it using available business research.</small></label>
          {draft && <><label>Recipient<Input type="email" readOnly value={draft.recipient}/></label><label>Subject<Input readOnly={draft.approved} value={draft.subject} onChange={event => setDraft({ ...draft, subject: event.target.value })}/></label><label>Message<textarea className="input email-message-editor" readOnly={draft.approved} value={draft.body} onChange={event => setDraft({ ...draft, body: event.target.value })}/></label><small className="email-field-note">Edit the generated subject or message before approval. The approved version is the one that will be sent.</small></>}
        </div>
        {actionError && <p className="inline-error" role="alert"><AlertCircle size={12}/>{actionError}</p>}
        {result && <p className="email-field-note" role="status">Email status: {result.status}{result.error ? ` (${result.error})` : ''}</p>}
        <div className="email-actions"><div className="email-ai-actions"><Button variant="secondary" disabled={!selectedLead || busy || leadState !== 'ready'} loading={busyAction === 'preview'} onClick={() => void previewEmail()}>Generate preview</Button><Button variant="ghost" disabled={!selectedLead || busy || leadState !== 'ready'} loading={busyAction === 'regenerate'} onClick={() => void previewEmail(true)}><Sparkles size={14}/>{busy ? 'Working…' : 'Regenerate with AI'}</Button><Button variant="ghost" disabled={!selectedLead || busy || leadState !== 'ready'} loading={busyAction === 'proposal'} onClick={() => void generateProposalAndPreview()}>Generate proposal + email</Button></div>{draft && !draft.approved && <Button variant="secondary" disabled={busy} loading={busyAction === 'approve'} onClick={() => void approveEmail()}>Approve edited draft</Button>}{draft?.approved && <Button variant="primary" disabled={busy || Boolean(result)} loading={busyAction === 'send'} onClick={() => void sendEmail()}><Send size={14}/>{busy ? 'Sending…' : 'Send approved email'}</Button>}</div>
      </GlassCard>
    </div>
  </div>
}
