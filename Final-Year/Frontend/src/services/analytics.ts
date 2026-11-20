import { api } from './api'

export type AnalyticsActivity = {
  id: string
  label: string
  status: string
  created_at: string | null
}

export type AnalyticsOverview = {
  generated_at: string
  leads_total: number
  high_priority_leads: number
  qualified_leads: number
  websites_total: number
  emails_total: number
  emails_sent: number
  calls_total: number
  calls_dispatched: number
  recent_leads: {
    lead_id: string
    business_name: string
    category: string | null
    lead_score: number | null
    priority: string
    updated_at: string | null
  }[]
  recent_emails: AnalyticsActivity[]
  recent_calls: AnalyticsActivity[]
}

export const analyticsService = {
  async overview() {
    const { data } = await api.get<AnalyticsOverview>('/api/v1/analytics/overview')
    return data
  },
}
