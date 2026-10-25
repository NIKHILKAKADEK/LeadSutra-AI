import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowUpRight, BriefcaseBusiness, Clock3, Globe2, Mail, MapPin, Phone, PhoneCall, RefreshCw, Search, Sparkles, Star, Target, UserRound } from 'lucide-react'
import { Badge, Button, EmptyState, GlassCard, LoadingState, useToast } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'
import { businessDiscoveryService, type BusinessLead, type BusinessProfile, type BusinessResearch, type CompetitorAnalysis } from '../services/businessDiscovery'
import { classifyApiError, type ApiFailure } from '../utils/apiErrors'
import { Priority, Score, WebsiteLink } from './BusinessLeadViews'

type DetailsState = 'loading' | 'success' | 'connection-required' | 'network-error' | 'server-error'
type DetailsTab = 'overview' | 'research' | 'competitors' | 'score' | 'activity'

const tabs: { id: DetailsTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'research', label: 'Research' },
  { id: 'competitors', label: 'Competitors' },
  { id: 'score', label: 'Lead Score' },
  { id: 'activity', label: 'Activity' },
]

export function StoredLeadDetailsPage() {
  const { leadId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const source = searchParams.get('source') || 'google'
  const [state, setState] = useState<DetailsState>(businessDiscoveryService.isConfigured ? 'loading' : 'connection-required')
  const [retry, setRetry] = useState(0)
  const [lead, setLead] = useState<BusinessLead | null>(null)
  const [profile, setProfile] = useState<BusinessProfile | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [tab, setTab] = useState<DetailsTab>('overview')
  const [researchResult, setResearchResult] = useState<BusinessResearch | null>(null)
  const [researchError, setResearchError] = useState('')
  const [researching, setResearching] = useState(false)
  const [competitors, setCompetitors] = useState<CompetitorAnalysis | null>(null)
  const [competitorsLoading, setCompetitorsLoading] = useState(false)
  const [competitorsError, setCompetitorsError] = useState('')
  const toast = useToast()

  useEffect(() => {
    let active = true
    if (!businessDiscoveryService.isConfigured) { setState('connection-required'); return () => { active = false } }
    setState('loading')
    setError(null)
    void businessDiscoveryService.details(leadId, source).then(result => {
      if (active) { setLead(result.lead); setProfile(result.profile); setState('success') }
    }).catch(cause => {
      if (active) { const failure = classifyApiError(cause); setError(failure); setState(failure.kind) }
    })
    return () => { active = false }
  }, [leadId, source, retry])

  async function runResearch() {
    if (!leadId || researching) return
    setTab('research')
    setResearching(true)
    setResearchError('')
    try {
      const result = await businessDiscoveryService.research(leadId)
      setResearchResult(result)
      toast.push({ title: 'Business research complete', description: `Research for ${lead?.name ?? 'this lead'} is ready.`, tone: 'success' })
    } catch (cause) {
      setResearchError(classifyApiError(cause).message)
      toast.push({ title: 'Business research failed', description: classifyApiError(cause).message, tone: 'error' })
    } finally { setResearching(false) }
  }

  async function loadCompetitors(refresh = false) {
    if (!leadId || competitorsLoading) return
    setCompetitorsLoading(true)
    setCompetitorsError('')
    try {
      setCompetitors(await businessDiscoveryService.competitors(leadId, refresh))
    } catch (cause) {
      setCompetitorsError(classifyApiError(cause).message)
    } finally { setCompetitorsLoading(false) }
  }

  useEffect(() => {
    if (tab === 'competitors' && !competitors && !competitorsLoading && !competitorsError) {
      void loadCompetitors()
    }
  }, [tab, competitors, competitorsLoading, competitorsError])

  if (state === 'loading') return <StoredLeadSkeleton />
  if (state !== 'success' || !lead) return <div className="stored-detail-page"><Link to="/leads" className="back-to-leads"><ArrowLeft size={15} /> Back to leads</Link><GlassCard className="business-state-card"><EmptyState icon={state === 'connection-required' ? Globe2 : Search} title={state === 'connection-required' ? 'Connect the discovery API' : 'Lead details unavailable'} description={state === 'connection-required' ? 'Set a trusted discovery API/BFF before loading stored business details.' : error?.message ?? 'This business could not be loaded.'} action={state !== 'connection-required' ? <Button variant="secondary" onClick={() => setRetry(value => value + 1)}>Try again</Button> : undefined} /></GlassCard></div>

  return <div className="stored-detail-page">
    <Link to="/leads" className="back-to-leads"><ArrowLeft size={15} /> Back to leads</Link>
    <PageHeader eyebrow={`${lead.source || 'SOURCE UNKNOWN'} · BUSINESS RECORD`} title={lead.name} description={lead.category || 'Category not returned by backend.'} actions={<div className="stored-detail-header-badges"><Priority value={lead.priority} />{lead.qualification_status && <Badge>{lead.qualification_status}</Badge>}<Button variant="secondary" loading={researching} disabled={researching} onClick={() => void runResearch()}><Sparkles size={14}/>{researching ? 'Researching…' : 'Run research'}</Button><Link className="button button-secondary" to={`/outreach?lead_id=${encodeURIComponent(lead.external_place_id || leadId)}`}><Mail size={14}/>Email</Link><Link className="button button-primary" to={`/calls?lead_id=${encodeURIComponent(lead.external_place_id || leadId)}`}><PhoneCall size={14}/>Call</Link></div>} />
    <nav className="stored-detail-tabs" role="tablist" aria-label="Lead details sections">{tabs.map(item => <button key={item.id} role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav>
    {tab === 'overview' && <Overview lead={lead} profile={profile} />}
    {tab === 'research' && <Research lead={lead} profile={profile} result={researchResult} error={researchError} researching={researching} onRun={() => void runResearch()} />}
    {tab === 'competitors' && <Competitors result={competitors} error={competitorsError} loading={competitorsLoading} onRefresh={() => void loadCompetitors(true)} />}
    {tab === 'score' && <ScoreDetails lead={lead} />}
    {tab === 'activity' && <FutureSection title="Lead activity is not available" description="The backend does not expose a lead activity timeline or created/updated timestamps." />}
  </div>
}

function Overview({ lead, profile }: { lead: BusinessLead; profile: BusinessProfile | null }) {
  const emails = Array.from(new Set([lead.email, ...lead.contact_emails, profile?.email].filter((value): value is string => Boolean(value))))
  const phones = Array.from(new Set([lead.phone, profile?.phone].filter((value): value is string => Boolean(value))))
  const socialLinks = Object.entries(profile?.social_links ?? lead.social_links).filter(([, value]) => isWebUrl(value))
  return <div className="stored-detail-grid">
    <div className="stored-detail-main">
      <GlassCard className="stored-info-card"><CardHeading icon={<BriefcaseBusiness size={17} />} title="Business identity" /><div className="stored-info-grid"><Info label="Business name" value={lead.name} /><Info label="Category" value={lead.category} /><Info label="Address" value={lead.address} icon={<MapPin size={13} />} /><div className="stored-info-item"><span>Website</span><WebsiteLink value={lead.website} /></div><Info label="Website status" value={lead.website_status} /><Info label="Discovery source" value={lead.source} /></div>
        {lead.description && <div className="stored-description"><h3>Business description</h3><p>{lead.description}</p></div>}
      </GlassCard>
      <GlassCard className="stored-info-card"><CardHeading icon={<UserRound size={17} />} title="Available contact details" />
        {phones.length ? <div className="stored-contact-list">{phones.map(phone => <a key={phone} href={`tel:${phone}`}><Phone size={14} />{phone}</a>)}</div> : <p className="stored-muted">No phone number was returned.</p>}
        {emails.length ? <div className="stored-contact-list">{emails.map(email => <a key={email} href={`mailto:${email}`}><span>@</span>{email}</a>)}</div> : <p className="stored-muted">No email address was returned.</p>}
        {lead.contact_person && <Info label="Contact person" value={lead.contact_person} />}
      </GlassCard>
      <GlassCard className="stored-info-card"><CardHeading icon={<Globe2 size={17} />} title="Online presence" />{socialLinks.length ? <div className="stored-social-links">{socialLinks.map(([network, url]) => <a key={network} href={url} target="_blank" rel="noreferrer">{network}<ArrowUpRight size={13} /></a>)}</div> : <p className="stored-muted">No social links were returned.</p>}</GlassCard>
    </div>
    <aside className="stored-detail-aside"><GlassCard className="stored-score-card"><CardHeading icon={<Target size={17} />} title="Lead quality" /><div className="stored-quality-row"><span>Lead score</span><Score value={lead.lead_score} /></div><div className="stored-quality-row"><span>Priority</span><Priority value={lead.priority} /></div><div className="stored-quality-row"><span>Qualification</span><strong>{lead.qualification_status || 'Not returned'}</strong></div><div className="stored-quality-row"><span>Rating</span><strong>{lead.rating === null ? 'Not returned' : <><Star size={13} fill="currentColor" /> {lead.rating.toFixed(1)}</>}</strong></div></GlassCard>
      <GlassCard className="stored-score-card"><CardHeading icon={<Sparkles size={17} />} title="Processing status" /><div className="stored-quality-row"><span>Website research</span><strong>{lead.scrape_status || 'Not returned'}</strong></div><div className="stored-quality-row"><span>Contact extraction</span><strong>{lead.contact_extraction_status || 'Not returned'}</strong></div><div className="stored-quality-row"><span>Profile research</span><strong>{profile?.profile_extraction_status || 'No profile returned'}</strong></div></GlassCard>
    </aside>
  </div>
}

function Research({ lead, profile, result, error, researching, onRun }: { lead: BusinessLead; profile: BusinessProfile | null; result: BusinessResearch | null; error: string; researching: boolean; onRun: () => void }) {
  const services = Array.from(new Set([...(lead.services ?? []), ...(profile?.services ?? [])]))
  const products = profile?.products ?? []
  const targets = profile?.target_customers ?? []
  const researchStatus = profile?.profile_extraction_status || lead.scrape_status || lead.contact_extraction_status || 'not researched'
  const researchedAt = typeof lead.extraction_metadata?.researched_at === 'string' ? lead.extraction_metadata.researched_at : null
  return <div className="stored-research-grid">
    <GlassCard className="stored-info-card"><div className="stored-card-heading"><span><Search size={17}/></span><h2>Research summary</h2><Button variant="secondary" size="sm" disabled={researching} onClick={onRun}><Sparkles size={13}/>{researching ? 'Researching…' : 'Run business research'}</Button></div>{researching && <LoadingState label="Researching this business"/>}{error && <p className="inline-error" role="alert">{error}</p>}<p className="stored-research-copy">{result?.business_summary || profile?.about_info || profile?.description || lead.description || 'No business summary was returned.'}</p><div className="stored-research-meta"><Info label="Research status" value={researching ? 'running' : result ? 'complete' : researchStatus} /><Info label="Last researched" value={result?.researched_at ? new Date(result.researched_at).toLocaleString() : researchedAt} /><Info label="Extraction source" value={profile?.extraction_source} /><Info label="Profile status" value={profile?.profile_extraction_status} /><Info label="Contact page" value={lead.contact_page_url} /><Info label="About page" value={lead.about_page_url} /></div>{result && <div className="stored-research-output"><Info label="Target audience" value={result.target_audience}/><Info label="Ideal customer profile" value={result.ideal_customer_profile}/><Info label="Decision maker" value={result.decision_maker_identification}/><ListCard title="Sales opportunities" values={result.sales_opportunities}/><ListCard title="Pain points" values={result.pain_points}/><ListCard title="Products and services" values={result.products_services}/><ListCard title="Strengths" values={result.swot.strengths}/><ListCard title="Weaknesses" values={result.swot.weaknesses}/><ListCard title="Opportunities" values={result.swot.opportunities}/><ListCard title="Threats" values={result.swot.threats}/><ListCard title="Verified facts" values={result.provided_facts}/><ListCard title="Reasonable inferences" values={result.reasonable_inferences}/><ListCard title="Information still needed" values={result.missing_information}/></div>}</GlassCard>
    {result?.web_findings.length ? <ListCard title="Public web findings" values={result.web_findings} /> : null}
    {result?.research_sources.length ? <div className="stored-info-card"><CardHeading icon={<Search size={17} />} title="Research sources" /><ul className="research-source-list">{result.research_sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.title || source.url}</a></li>)}</ul></div> : null}
    <ListCard title="Services" values={services} />
    <ListCard title="Products" values={products} />
    <ListCard title="Target customers" values={targets} />
    <GlassCard className="stored-info-card"><CardHeading icon={<Clock3 size={17} />} title="Operating hours" /><p className="stored-muted">{displayObject(result?.operating_hours ?? lead.operating_hours ?? profile?.operating_hours) || 'Not returned by the backend.'}</p></GlassCard>
  </div>
}

function Competitors({ result, error, loading, onRefresh }: { result: CompetitorAnalysis | null; error: string; loading: boolean; onRefresh: () => void }) {
  return <div className="stored-research-grid">
    <GlassCard className="stored-info-card">
      <div className="stored-card-heading"><span><Search size={17}/></span><h2>Nearby competitors</h2><Button variant="secondary" size="sm" loading={loading} disabled={loading} onClick={onRefresh}><RefreshCw size={13}/>{loading ? 'Searching…' : 'Refresh search'}</Button></div>
      <p className="stored-research-copy">{result?.comparison_summary || 'Search Google Places for businesses in the same category and location.'}</p>
      {loading && <LoadingState label="Finding nearby competitors"/>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      {result && <div className="stored-research-meta"><Info label="Search category" value={result.category}/><Info label="Search location" value={result.location}/><Info label="Maximum distance" value={result.radius_meters ? `${result.radius_meters / 1000} km` : null}/><Info label="Data source" value={result.source}/><Info label="Last searched" value={result.researched_at ? new Date(result.researched_at).toLocaleString() : null}/></div>}
      {result?.message && <p className="stored-muted">{result.message}</p>}
      {result?.competitors.map(item => <article className="stored-info-card" key={`${item.name}-${item.address ?? ''}`}>
        <div className="stored-card-heading"><span><Target size={16}/></span><h2>{item.name}</h2>{item.rating !== null && <Badge><Star size={12} fill="currentColor"/> {item.rating.toFixed(1)}{item.review_count !== null ? ` · ${item.review_count} reviews` : ''}</Badge>}</div>
        {item.category && <Info label="Category" value={item.category}/>}
        {item.distance_meters !== null && <Info label="Distance" value={`${(item.distance_meters / 1000).toFixed(1)} km`}/>}
        {item.address && <Info label="Address" value={item.address} icon={<MapPin size={13}/>}/>}
        {item.website && <Info label="Website" value={item.website}/>}
        {item.source_url && <a className="stored-social-links" href={item.source_url} target="_blank" rel="noreferrer">View source <ArrowUpRight size={13}/></a>}
      </article>)}
      {result?.status === 'no_results' && <p className="stored-muted">No competitor listings were returned. You can refresh to search again.</p>}
    </GlassCard>
  </div>
}

function ScoreDetails({ lead }: { lead: BusinessLead }) {
  const breakdown = lead.score_breakdown ?? {}
  const dimensions = Object.entries(breakdown.dimensions ?? {})
  const missing = [
    !lead.category && 'Business category',
    !lead.website && 'Website availability',
    lead.rating === null && 'Google rating',
    !Object.keys(lead.social_links ?? {}).length && 'Online presence',
    !lead.phone && !lead.email && !lead.contact_emails.length && 'Contact availability',
  ].filter((value): value is string => Boolean(value))
  return <div className="stored-score-stack"><GlassCard className="stored-info-card"><CardHeading icon={<Target size={17} />} title="Backend lead score" /><div className="stored-score-summary"><Score value={lead.lead_score} /><Priority value={lead.priority} />{lead.qualification_status && <Badge>{lead.qualification_status}</Badge>}</div>{dimensions.length ? <><p className="stored-muted score-source-note">Score uses {breakdown.assessable_points ?? 0} of {breakdown.maximum_points ?? 100} assessable points ({breakdown.evidence_coverage_percent ?? 0}% evidence coverage).</p><div className="score-breakdown">{dimensions.map(([name, dimension]) => <section className="score-dimension" key={name}><div className="score-dimension-heading"><strong>{formatScoreLabel(name)}</strong><span>{dimension.earned_points}/{dimension.assessable_points} assessed · {dimension.maximum_points} max</span></div>{Object.entries(dimension.factors).map(([factorName, factor]) => <div className="score-factor" key={factorName}><span>{formatScoreLabel(factorName)}</span><strong>{factor.earned_points}/{factor.assessable_points || factor.maximum_points}</strong><small>{factor.status === 'unavailable' ? factor.missing_or_unavailable.join(', ') : factor.evidence_used.map(item => item.value).join('; ') || 'Assessed; no separate evidence detail provided'}</small></div>)}</section>)}</div></> : <p className="stored-muted">This saved lead predates score-breakdown storage. Run lead discovery again to save a detailed evidence breakdown for it.</p>}<p className="stored-muted score-source-note">The score, priority, qualification, and component points are returned by the backend; this page does not recalculate them.</p></GlassCard>{missing.length > 0 && <GlassCard className="stored-info-card"><CardHeading icon={<Search size={17} />} title="Missing listing signals" /><p className="stored-muted">These public listing inputs are unavailable:</p><ul className="stored-value-list">{missing.map(item => <li key={item}>{item}</li>)}</ul></GlassCard>}</div>
}

function formatScoreLabel(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
}

function ListCard({ title, values }: { title: string; values: string[] }) {
  return <GlassCard className="stored-info-card"><CardHeading icon={<Sparkles size={17} />} title={title} />{values.length ? <ul className="stored-value-list">{values.map(value => <li key={value}>{value}</li>)}</ul> : <p className="stored-muted">No {title.toLowerCase()} were returned.</p>}</GlassCard>
}

function FutureSection({ title, description }: { title: string; description: string }) {
  return <GlassCard className="stored-future-state"><EmptyState icon={Sparkles} title={title} description={description} /></GlassCard>
}

function CardHeading({ icon, title }: { icon: React.ReactNode; title: string }) {
  return <header className="stored-card-heading"><span>{icon}</span><h2>{title}</h2></header>
}

function Info({ label, value, icon }: { label: string; value: string | null | undefined; icon?: React.ReactNode }) {
  return <div className="stored-info-item"><span>{icon}{label}</span><strong>{value || 'Not returned'}</strong></div>
}

function isWebUrl(value: string) {
  try { const url = new URL(value); return url.protocol === 'https:' || url.protocol === 'http:' } catch { return false }
}

function displayObject(value: string | Record<string, unknown> | null | undefined) {
  if (!value) return ''
  if (typeof value === 'string') return value
  return Object.entries(value).map(([key, item]) => `${key}: ${String(item)}`).join(' · ')
}

function StoredLeadSkeleton() {
  return <div className="stored-detail-page"><Link to="/leads" className="back-to-leads"><ArrowLeft size={15} /> Back to leads</Link><GlassCard className="stored-loading-card"><LoadingState label="Loading business record" /><div className="stored-skeleton-grid">{Array.from({ length: 5 }, (_, index) => <span key={index} className="skeleton" />)}</div></GlassCard></div>
}
