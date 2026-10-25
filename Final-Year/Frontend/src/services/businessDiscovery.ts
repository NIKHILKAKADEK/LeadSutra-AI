import { discoveryApi, isDiscoveryApiConfigured } from './api'

export type BusinessLead = {
  external_place_id: string | null
  source: string
  name: string
  category: string | null
  rating: number | null
  phone: string | null
  phone_numbers: string[]
  email: string | null
  website: string | null
  address: string | null
  latitude: number | null
  longitude: number | null
  description: string | null
  raw_data: Record<string, unknown>
  social_links: Record<string, string>
  services: string[]
  website_status: string | null
  scrape_status: string | null
  contact_person: string | null
  contact_emails: string[]
  contact_page_url: string | null
  about_page_url: string | null
  operating_hours: string | Record<string, unknown> | null
  extraction_metadata: Record<string, unknown>
  contact_extraction_status: string
  lead_score: number | null
  priority: string | null
  qualification_status: string | null
  score_breakdown: ScoreBreakdown
}

export type ScoreFactor = {
  earned_points: number
  assessable_points: number
  maximum_points: number
  status: 'assessed' | 'unavailable'
  evidence_used: { value: string; source_urls: string[] }[]
  missing_or_unavailable: string[]
}

export type ScoreDimension = {
  earned_points: number
  assessable_points: number
  maximum_points: number
  status: 'assessed' | 'partial' | 'unavailable'
  factors: Record<string, ScoreFactor>
}

export type ScoreBreakdown = {
  earned_points?: number
  assessable_points?: number
  maximum_points?: number
  evidence_coverage_percent?: number
  dimensions?: Record<string, ScoreDimension>
}

export type BusinessProfile = {
  lead_id: string | null
  external_place_id: string | null
  source: string
  business_name: string
  category: string | null
  sub_category: string | null
  description: string | null
  services: string[]
  products: string[]
  target_customers: string[]
  about_info: string | null
  address: string | null
  phone: string | null
  email: string | null
  website: string | null
  social_links: Record<string, string>
  operating_hours: string | Record<string, unknown> | null
  online_presence: Record<string, unknown>
  profile_extraction_status: string
  extraction_source: string
}

export type SearchBusinessesRequest = {
  query: string
  location: string
  limit: number
}

type BackendLead = {
  lead_id: string
  discovery: {
    business_name: string
    category: string | null
    description: string | null
    address: string | null
    phone: string | null
    email: string | null
    website: string | null
    latitude: number | null
    longitude: number | null
    rating: number | null
    source_url: string | null
  }
  enrichment: {
    contact_person: string | null
    emails: string[]
    phone_numbers: string[]
    website_status: string
    about: string
    business_description: string | null
    services: string[]
    products: string[]
    target_customers: string[]
    social_links: Record<string, string | null>
    contact_page_url: string | null
  }
  scoring: {
    lead_score: number | null
    priority: string
    qualification_status: string
    score_breakdown?: ScoreBreakdown
  }
}

type BackendDiscoveryResponse = {
  query: string
  location: string
  count: number
  source: string
  leads: BackendLead[]
}

type BackendStoredLeadPage = {
  items: BackendLead[]
}

export type SearchBusinessesResponse = {
  query: string
  location: string
  total_results: number
  source: string
  leads: BusinessLead[]
}

export type StoredLeadFilters = {
  min_score: number
  priority?: 'high' | 'medium' | 'low'
  limit: number
}

export type StoredLeadDetails = {
  lead: BusinessLead
  profile: BusinessProfile | null
}

export type BusinessResearch = {
  business_summary: string
  products_services: string[]
  target_audience: string
  pain_points: string[]
  swot: {
    strengths: string[]
    weaknesses: string[]
    opportunities: string[]
    threats: string[]
  }
  ideal_customer_profile: string
  decision_maker_identification: string
  sales_opportunities: string[]
  provided_facts: string[]
  reasonable_inferences: string[]
  missing_information: string[]
  web_findings: string[]
  research_sources: { title: string; url: string }[]
  contact_page_url: string | null
  about_page_url: string | null
  operating_hours: { day: string; opens?: string | null; closes?: string | null; closed?: boolean }[]
  researched_at?: string | null
}

export type CompetitorAnalysis = {
  business_name: string
  category: string
  location: string
  status: 'complete' | 'no_results' | 'unavailable'
  source: string | null
  radius_meters: number | null
  competitors: {
    name: string
    category: string | null
    address: string | null
    rating: number | null
    review_count: number | null
    website: string | null
    phone: string | null
    source_url: string | null
    distance_meters: number | null
  }[]
  comparison_summary: string
  message: string | null
  researched_at: string
}

function mapLead(lead: BackendLead, source: string): BusinessLead {
  const { discovery, enrichment, scoring } = lead
  const socialLinks = Object.fromEntries(
    Object.entries(enrichment.social_links).filter((entry): entry is [string, string] => Boolean(entry[1])),
  )
  return {
    external_place_id: lead.lead_id,
    source,
    name: discovery.business_name,
    category: discovery.category,
    rating: discovery.rating,
    phone: discovery.phone ?? enrichment.phone_numbers[0] ?? null,
    phone_numbers: Array.from(new Set([discovery.phone, ...enrichment.phone_numbers].filter((value): value is string => Boolean(value)))),
    email: discovery.email ?? enrichment.emails[0] ?? null,
    website: discovery.website,
    address: discovery.address,
    latitude: discovery.latitude,
    longitude: discovery.longitude,
    description: enrichment.business_description || enrichment.about || discovery.description,
    raw_data: {},
    social_links: socialLinks,
    services: enrichment.services,
    website_status: enrichment.website_status,
    scrape_status: enrichment.website_status,
    contact_person: enrichment.contact_person,
    contact_emails: enrichment.emails,
    contact_page_url: enrichment.contact_page_url,
    about_page_url: null,
    operating_hours: null,
    extraction_metadata: {},
    contact_extraction_status: 'not_reported_by_backend',
    lead_score: scoring.lead_score,
    priority: scoring.priority,
    qualification_status: scoring.qualification_status,
    score_breakdown: scoring.score_breakdown ?? {},
  }
}

export const businessDiscoveryService = {
  isConfigured: isDiscoveryApiConfigured,
  async search(request: SearchBusinessesRequest) {
    const { data } = await discoveryApi.post<BackendDiscoveryResponse>('/api/v1/leads/discover', request)
    return {
      query: data.query,
      location: data.location,
      total_results: data.count,
      source: data.source,
      leads: data.leads.map(lead => mapLead(lead, data.source)),
    }
  },
  async list(filters: StoredLeadFilters) {
    const priority = filters.priority
      ? ({ high: 'High', medium: 'Medium', low: 'Low' } as const)[filters.priority]
      : undefined
    const { data } = await discoveryApi.get<BackendStoredLeadPage>('/api/v1/leads', {
      params: { limit: filters.limit, offset: 0, priority },
    })
    return data.items
      .map(lead => mapLead(lead, 'stored'))
      .filter(lead => (lead.lead_score ?? -1) >= filters.min_score)
  },
  async details(leadId: string, _source: string) {
    const { data } = await discoveryApi.get<BackendLead>(`/api/v1/leads/${encodeURIComponent(leadId)}`)
    return { lead: mapLead(data, 'stored'), profile: null } satisfies StoredLeadDetails
  },
  async research(leadId: string) {
    const { data } = await discoveryApi.post<BusinessResearch>('/api/v1/research/analyze', { lead_id: leadId })
    return data
  },
  async competitors(leadId: string, refresh = false) {
    const { data } = await discoveryApi.post<CompetitorAnalysis>(
      `/api/v1/research/competitors/${encodeURIComponent(leadId)}`,
      null,
      { params: { refresh } },
    )
    return data
  },
}
