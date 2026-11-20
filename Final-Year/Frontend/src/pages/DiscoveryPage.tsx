import { useMemo, useRef, useState, type FormEvent } from 'react'
import { ArrowRight, Compass, Download, MapPin, Search, Sparkles } from 'lucide-react'
import { Badge, Button, EmptyState, GlassCard, Input, LoadingState, Select, useToast } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'
import { businessDiscoveryService, type SearchBusinessesRequest, type SearchBusinessesResponse } from '../services/businessDiscovery'
import { classifyApiError, type ApiFailure } from '../utils/apiErrors'
import { BusinessLeadResults, downloadLeadsJson } from './BusinessLeadViews'

type DiscoveryState = 'idle' | 'loading' | 'success' | 'empty' | 'validation-error' | 'network-error' | 'server-error' | 'connection-required'
type SortOrder = 'backend' | 'name' | 'score' | 'rating'

export function DiscoveryPage() {
  const [query, setQuery] = useState('')
  const [location, setLocation] = useState('')
  const [limit, setLimit] = useState('10')
  const [sort, setSort] = useState<SortOrder>('backend')
  const [state, setState] = useState<DiscoveryState>('idle')
  const [validation, setValidation] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [response, setResponse] = useState<SearchBusinessesResponse | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const formRef = useRef<HTMLFormElement>(null)
  const toast = useToast()

  const sortedLeads = useMemo(() => {
    const leads = [...(response?.leads ?? [])]
    if (sort === 'name') leads.sort((a, b) => a.name.localeCompare(b.name))
    if (sort === 'score') leads.sort((a, b) => (b.lead_score ?? -1) - (a.lead_score ?? -1))
    if (sort === 'rating') leads.sort((a, b) => (b.rating ?? -1) - (a.rating ?? -1))
    return leads
  }, [response, sort])

  async function searchBusinesses(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setValidation('')
    setError(null)
    const cleanQuery = query.trim()
    const cleanLocation = location.trim()
    const resultLimit = Number(limit)
    if (!cleanQuery) { setValidation('Enter a business category or search phrase.'); setState('validation-error'); return }
    if (!cleanLocation) { setValidation('Enter a city, region, or location.'); setState('validation-error'); return }
    if (!Number.isInteger(resultLimit) || resultLimit < 1 || resultLimit > 60) { setValidation('Result limit must be a whole number from 1 to 60.'); setState('validation-error'); return }
    if (!businessDiscoveryService.isConfigured) { setState('connection-required'); return }

    setState('loading')
    const request: SearchBusinessesRequest = { query: cleanQuery, location: cleanLocation, limit: resultLimit }
    toast.push({ title: 'Search started', description: 'Finding and scoring businesses.', tone: 'info' })
    try {
      const result = await businessDiscoveryService.search(request)
      setResponse(result)
      setSelectedIds([])
      setState(result.leads.length ? 'success' : 'empty')
      toast.push({
        title: result.leads.length ? 'Discovery complete' : 'Search completed',
        description: result.leads.length
          ? `${result.total_results} result${result.total_results === 1 ? '' : 's'} returned and saved to the lead store.`
          : 'The backend returned no businesses for this search.',
        tone: 'success',
      })
    } catch (cause) {
      const failure = classifyApiError(cause)
      setError(failure)
      setState(failure.kind)
      toast.push({ title: 'Search failed', description: failure.message, tone: 'error' })
    }
  }

  function toggleLead(lead: SearchBusinessesResponse['leads'][number]) {
    const id = `${lead.source}:${lead.external_place_id ?? lead.name}`
    setSelectedIds(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id])
  }

  return <>
    <PageHeader eyebrow="DISCOVERY" title="Find your next customers." description="Search businesses by category and location." actions={<Badge>LIVE</Badge>} />
    <GlassCard className="discovery-hero">
      <div className="discovery-kicker"><Sparkles size={14} /> BUSINESS SEARCH</div>
      <form ref={formRef} className="discovery-form discovery-form-live" onSubmit={searchBusinesses} noValidate>
        <label>Business type<Input value={query} onChange={event => setQuery(event.target.value)} placeholder="e.g. Enter the buisness category" autoComplete="off" aria-invalid={state === 'validation-error' && !query.trim()} /></label>
        <label>Location<span className="discovery-input-wrap"><MapPin size={15} /><Input value={location} onChange={event => setLocation(event.target.value)} placeholder="City or region" autoComplete="address-level2" /></span></label>
        <label>Results<Input type="number" min={1} max={60} step={1} value={limit} onChange={event => setLimit(event.target.value)} /></label>
        <Button type="submit" variant="primary" loading={state === 'loading'} disabled={state === 'loading'}><Search size={15} />{state === 'loading' ? 'Searching…' : 'Search businesses'}<ArrowRight size={15} /></Button>
      </form>
      {state === 'validation-error' && <div className="auth-feedback error discovery-message" role="alert">{validation}</div>}
      {state === 'connection-required' && <div className="auth-feedback discovery-message" role="status">Configure the API base URL or run the frontend in development with the backend on port 8000.</div>}
      {(state === 'network-error' || state === 'server-error') && <div className="discovery-error" role="alert"><p>{error?.message}</p><Button variant="secondary" size="sm" onClick={() => formRef.current?.requestSubmit()}>Retry search</Button></div>}
    </GlassCard>

    {state === 'loading' && <section className="discovery-results"><div className="discovery-results-heading"><div><h2>Searching businesses</h2></div><LoadingState label="Searching" /></div><DiscoverySkeleton /></section>}
    {response && (state === 'success' || state === 'empty') && <section className="discovery-results">
      <div className="discovery-results-heading"><div><h2>{state === 'empty' ? 'No businesses returned' : 'Search results'}</h2><span>{response.query} · {response.location} · {response.total_results} returned</span></div><label className="discovery-sort-label">Sort returned results<Select value={sort} onChange={event => setSort(event.target.value as SortOrder)}><option value="backend">Backend order</option><option value="name">Business name</option><option value="score">Lead score</option><option value="rating">Rating</option></Select></label></div>
      <div className="discovery-result-meta"><Badge>SAVED</Badge><span>Source: {response.source}</span></div>
      {state === 'success' ? <><div className="results-actions"><span>{selectedIds.length ? `${selectedIds.length} selected` : `${sortedLeads.length} results`}</span><Button variant="secondary" size="sm" disabled={!selectedIds.length} onClick={() => downloadLeadsJson(sortedLeads.filter(lead => selectedIds.includes(`${lead.source}:${lead.external_place_id ?? lead.name}`)), 'leads-selection.json')}><Download size={14} /> Export selected</Button><Button variant="ghost" size="sm" disabled={!sortedLeads.length} onClick={() => downloadLeadsJson(sortedLeads, 'discovery-results.json')}><Download size={14} /> Export all</Button></div><BusinessLeadResults leads={sortedLeads} selectable selectedIds={selectedIds} onToggle={toggleLead} /></> : <GlassCard className="discovery-empty"><EmptyState icon={Compass} title="No results found" description="Try a different category or a wider area." /></GlassCard>}
    </section>}
  </>
}

function DiscoverySkeleton() {
  return <GlassCard className="discovery-loading-card" aria-label="Loading discovery results"><span className="discovery-spinner" aria-hidden="true" /><strong>Finding businesses</strong><span>Enriching and scoring your results…</span></GlassCard>
}
