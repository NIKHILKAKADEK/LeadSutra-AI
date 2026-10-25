import { api } from './api'

// Call dispatch uses the signed-in app session. The OmniDimension API key stays
// on the backend and is never sent from this service.
export type CallDispatchStatus = 'blocked' | 'dry_run' | 'dispatching' | 'dispatched' | 'duplicate' | 'provider_error' | 'uncertain'
export type CallHistoryItem = {
  call_id: string
  lead_id: string
  phone_number: string
  dispatch_status: CallDispatchStatus | string
  provider_request_id: string | null
  dispatch_requested: boolean
  provider_accepted: boolean
  call_outcome: string
  created_at: string
  updated_at: string
}
export type CallHistoryPage = { total: number; limit: number; offset: number; calls: CallHistoryItem[] }
export type CallDispatchResult = {
  status: CallDispatchStatus | string
  dispatched: boolean
  lead_id: string
  normalized_phone_number: string | null
  agent_id: number | null
  reason_codes: string[]
  provider_request_id: string | null
}
export type FollowUpStatus = 'pending' | 'completed' | 'cancelled'
export type FollowUpItem = {
  follow_up_id: string
  lead_id: string
  related_call_id: string | null
  scheduled_at: string
  status: FollowUpStatus
  assigned_reviewer: string | null
  notes: string | null
  idempotency_key: string
  created_at: string
  updated_at: string
}
export type FollowUpPage = { total: number; limit: number; offset: number; follow_ups: FollowUpItem[] }
export type FollowUpUpdate = { scheduled_at?: string; status?: FollowUpStatus; notes?: string | null }
export type EmailDraft = {
  lead_id: string
  business_name: string
  recipient: string
  sender: string
  proposal_file: string
  subject: string
  body: string
  review_id: string
  draft_key: string
  template: string
  approved: boolean
}
export type EmailResult = {
  email_id: string
  lead_id: string
  business_name: string | null
  recipient: string | null
  status: 'pending' | 'sending' | 'sent' | 'failed' | 'uncertain'
  error: string | null
}
export type ProposalGenerationResult = {
  success: boolean
  lead_id: string
  business_name: string
  proposal: {
    business_summary: string
    identified_needs: string[]
    proposed_solution: string
    deliverables: string[]
    implementation_timeline: string[]
    expected_benefits: string[]
    pricing_suggestion: string
    next_steps: string[]
    email_subject_options: string[]
    personalized_email: string
  }
}

export const outreachService = {
  async callHistory(params: { limit: number; offset: number; lead_id?: string; dispatch_status?: CallDispatchStatus }) {
    const { data } = await api.get<CallHistoryPage>('/api/v1/calls', { params })
    return data
  },
  async dispatchCall(payload: { lead_id: string; phone_number: string; idempotency_key: string; confirmed: true }) {
    const { data } = await api.post<CallDispatchResult>('/api/v1/calls/dispatch', payload)
    return data
  },
  async followUps(params: { limit: number; offset: number; status?: FollowUpStatus }) {
    const { data } = await api.get<FollowUpPage>('/api/v1/follow-ups', { params })
    return data
  },
  async createFollowUp(payload: { lead_id: string; scheduled_at: string; notes?: string; idempotency_key: string }) {
    const { data } = await api.post<FollowUpItem>('/api/v1/follow-ups', payload)
    return data
  },
  async updateFollowUp(id: string, payload: FollowUpUpdate) {
    const { data } = await api.patch<FollowUpItem>(`/api/v1/follow-ups/${encodeURIComponent(id)}`, payload)
    return data
  },
  async emailPreview(leadId: string, template?: string, regenerate = false, researchIfMissing = false) {
    const { data } = await api.post<EmailDraft>('/api/v1/emails/preview', { lead_id: leadId, template, regenerate, research_if_missing: researchIfMissing })
    return data
  },
  async generateProposal(leadId: string) {
    const { data } = await api.post<ProposalGenerationResult>('/api/v1/proposals/generate', { lead_id: leadId })
    return data
  },
  async approveEmail(payload: { lead_id: string; review_id: string; approved: boolean; template?: string; subject?: string; body?: string }) {
    const { data } = await api.put<EmailDraft>('/api/v1/emails/approval', payload)
    return data
  },
  async sendEmail(leadId: string, draftKey: string) {
    const { data } = await api.post<EmailResult>('/api/v1/emails/send', { lead_id: leadId, draft_key: draftKey })
    return data
  },
}
