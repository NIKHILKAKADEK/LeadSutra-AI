import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { ArrowDownUp, Search, Users } from 'lucide-react'
import { Badge, Button, EmptyState, GlassCard, Input, LoadingState, Select, useToast } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'
import { businessDiscoveryService, type BusinessLead, type StoredLeadFilters } from '../services/businessDiscovery'
import { classifyApiError, type ApiFailure } from '../utils/apiErrors'
import { BusinessLeadResults } from './BusinessLeadViews'

type PageState = 'idle' | 'loading' | 'success' | 'empty' | 'connection-required' | 'network-error' | 'server-error'
type SortOrder = 'newest' | 'score' | 'name' | 'rating'

export function LeadsPage() {
  const [state, setState] = useState<PageState>(businessDiscoveryService.isConfigured ? 'idle' : 'connection-required')
  const [records, setRecords] = useState<BusinessLead[]>([])
  const [error, setError] = useState<ApiFailure | null>(null)
  const [search, setSearch] = useState('')
  const [minScore, setMinScore] = useState('0')
  const [priority, setPriority] = useState('')
  const [limit, setLimit] = useState('50')
  const [sort, setSort] = useState<SortOrder>('newest')
  const [activeFilters, setActiveFilters] = useState<StoredLeadFilters>({ min_score: 0, limit: 50 })
  const toast = useToast()

  const load = useCallback(async (filters: StoredLeadFilters): Promise<boolean> => {
    if (!businessDiscoveryService.isConfigured) { setState('connection-required'); return false }
    setState('loading')
    setError(null)
    try {
      const result = await businessDiscoveryService.list(filters)
      setRecords(result)
      setActiveFilters(filters)
      setState(result.length ? 'success' : 'empty')
      return true
    } catch (cause) {
      const failure = classifyApiError(cause)
      setError(failure)
      setState(failure.kind)
      return false
    }
  }, [])

  useEffect(() => { if (businessDiscoveryService.isConfigured) void load({ min_score: 0, limit: 50 }) }, [load])

  const visibleRecords = useMemo(() => {
    const term = search.trim().toLocaleLowerCase()
    const filtered = records.filter(lead => !term || [lead.name, lead.category, lead.address, lead.source].some(value => value?.toLocaleLowerCase().includes(term)))
    if (sort === 'name') filtered.sort((a, b) => a.name.localeCompare(b.name))
    if (sort === 'score') filtered.sort((a, b) => (b.lead_score ?? -1) - (a.lead_score ?? -1))
    if (sort === 'rating') filtered.sort((a, b) => (b.rating ?? -1) - (a.rating ?? -1))
    return filtered
  }, [records, search, sort])


  async function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const score = Number(minScore)
    const requestedLimit = Number(limit)
    if (!Number.isInteger(score) || score < 0 || score > 100) { const message = 'Minimum score must be a whole number from 0 to 100.'; setError({ kind: 'server-error', message }); setState('server-error'); toast.push({ title: 'Check your filters', description: message, tone: 'error' }); return }
    if (!Number.isInteger(requestedLimit) || requestedLimit < 1 || requestedLimit > 100) { const message = 'The backend accepts a limit from 1 to 100.'; setError({ kind: 'server-error', message }); setState('server-error'); toast.push({ title: 'Check your filters', description: message, tone: 'error' }); return }
    const loaded = await load({ min_score: score, priority: priority ? priority as StoredLeadFilters['priority'] : undefined, limit: requestedLimit })
    if (loaded) toast.push({ title: 'Lead list updated', description: 'Showing the latest matching records.', tone: 'success' })
    else toast.push({ title: 'Could not update leads', description: 'The stored lead request failed. Check the error message and try again.', tone: 'error' })
  }

  return <div className="leads-page">
    <PageHeader eyebrow="LEADS" title="Your lead workspace." description="Review and organize your saved businesses." actions={<Badge>{state === 'success' || state === 'empty' ? `${records.length} LOADED` : 'LEADS'}</Badge>} />
    <GlassCard className="business-filter-card"><form className="business-filter-form" onSubmit={applyFilters}>
      <label>Search leads<span className="business-search-wrap"><Search size={15} /><Input value={search} onChange={event => setSearch(event.target.value)} placeholder="Name, category, or location" /></span></label>
      <label>Min. score<Input type="number" min={0} max={100} step={1} value={minScore} onChange={event => setMinScore(event.target.value)} /></label>
      <label>Priority<Select value={priority} onChange={event => setPriority(event.target.value)}><option value="">All priorities</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></Select></label>
      <label>Records<Select value={limit} onChange={event => setLimit(event.target.value)}><option value="25">25</option><option value="50">50</option><option value="100">100</option></Select></label>
      <Button type="submit" variant="secondary" loading={state === 'loading'} disabled={state === 'loading'}><ArrowDownUp size={14} /> Apply filters</Button>
    </form></GlassCard>

    {state === 'loading' && <GlassCard className="business-state-card"><LoadingState label="Loading stored leads" /></GlassCard>}
    {state === 'connection-required' && <GlassCard className="business-state-card"><EmptyState icon={Users} title="Connect the discovery API" description="Run the frontend in development or configure VITE_API_BASE_URL for a trusted API/BFF." /></GlassCard>}
    {(state === 'network-error' || state === 'server-error') && <GlassCard className="business-state-card"><EmptyState title="Lead records unavailable" description={error?.message ?? 'The lead service could not be reached.'} action={<Button variant="secondary" onClick={() => void load(activeFilters)}>Try again</Button>} /></GlassCard>}
    {state === 'empty' && <GlassCard className="business-state-card"><EmptyState icon={Users} title="No stored leads match these filters" description="Run a discovery search with Save results enabled, or lower the minimum score and change priority." /></GlassCard>}
    {state === 'success' && <section className="business-lead-list"><div className="business-list-heading"><div><h2>Lead records</h2><p>{visibleRecords.length} leads</p></div><label>Sort by<Select value={sort} onChange={event => setSort(event.target.value as SortOrder)}><option value="newest">Newest first</option><option value="score">Lead score</option><option value="name">Business name</option><option value="rating">Rating</option></Select></label></div>{visibleRecords.length ? <BusinessLeadResults leads={visibleRecords} /> : <GlassCard className="business-state-card"><EmptyState icon={Search} title="No matching leads" description="Change your search or filters." /></GlassCard>}</section>}
  </div>
}
