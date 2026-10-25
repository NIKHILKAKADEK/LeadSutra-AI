import { api, isApiConfigured } from './api'

// These paths and DTOs mirror app/api/v1/leads.py and its Pydantic response
// models. Calls require a trusted BFF to forward reviewer authorization.
export type LeadListItem = {
  lead_id: string
  business_name: string | null
  category: string | null
  qualification_status: string | null
  lead_score: number | null
  phone_numbers: string[]
}
export type LeadListResponse = { total: number; limit: number; offset: number; leads: LeadListItem[] }
export type LeadDetails = {
  lead_id: string
  business_name: string | null
  website: string | null
  category: string | null
  address: string | null
  contact_names: string[]
  phone_numbers: string[]
  email_addresses: string[]
  lead_score: number | null
  qualification_status: string | null
}
export type LeadListParams = {
  limit: number
  offset: number
  search?: string
  qualification_status?: string
  category?: string
}
type CanonicalLead = {
  lead_id: string
  discovery: {
    business_name: string
    category: string | null
    website: string | null
    address: string | null
    phone: string | null
    email: string | null
  }
  enrichment: { contact_person: string | null; phone_numbers: string[]; emails: string[] }
  scoring: { qualification_status: string; lead_score: number | null }
}
type StoredLeadPage = { items: CanonicalLead[]; total: number; limit: number; offset: number }
export type FollowUpCreate = {
  lead_id: string
  scheduled_at: string
  notes?: string
  idempotency_key: string
}
export type FollowUpRecord = {
  follow_up_id: string
  lead_id: string
  related_call_id: string | null
  scheduled_at: string
  status: 'pending' | 'completed' | 'cancelled'
  assigned_reviewer: string | null
  notes: string | null
  idempotency_key: string
  created_at: string
  updated_at: string
}
export const leadService = {
  isConfigured: isApiConfigured,
  async list(params: LeadListParams) {
    const { data } = await api.get<StoredLeadPage | LeadListResponse>('/api/v1/leads', { params })
    if ('leads' in data) return data
    return {
      total: data.total,
      limit: data.limit,
      offset: data.offset,
      leads: data.items.map(lead => ({
        lead_id: lead.lead_id,
        business_name: lead.discovery.business_name,
        category: lead.discovery.category,
        qualification_status: lead.scoring.qualification_status,
        lead_score: lead.scoring.lead_score,
        phone_numbers: Array.from(new Set([lead.discovery.phone, ...lead.enrichment.phone_numbers].filter((value): value is string => Boolean(value)))),
      })),
    }
  },
  async details(leadId: string) {
    const { data } = await api.get<CanonicalLead>(`/api/v1/leads/${encodeURIComponent(leadId)}`)
    return {
      lead_id: data.lead_id,
      business_name: data.discovery.business_name,
      website: data.discovery.website,
      category: data.discovery.category,
      address: data.discovery.address,
      contact_names: data.enrichment.contact_person ? [data.enrichment.contact_person] : [],
      phone_numbers: Array.from(new Set([data.discovery.phone, ...data.enrichment.phone_numbers].filter((value): value is string => Boolean(value)))),
      email_addresses: Array.from(new Set([data.discovery.email, ...data.enrichment.emails].filter((value): value is string => Boolean(value)))),
      lead_score: data.scoring.lead_score,
      qualification_status: data.scoring.qualification_status,
    } satisfies LeadDetails
  },
  async createFollowUp(payload: FollowUpCreate) {
    const { data } = await api.post<FollowUpRecord>('/api/v1/follow-ups', payload)
    return data
  },
}
