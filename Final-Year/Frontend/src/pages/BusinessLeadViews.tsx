import { ArrowUpRight, Check, Globe2, MapPin, Phone, Star } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, GlassCard } from '../components/ui'
import type { BusinessLead } from '../services/businessDiscovery'

export function businessLeadPath(lead: BusinessLead) {
  if (!lead.external_place_id) return null
  const params = new URLSearchParams({ source: lead.source })
  return `/leads/${encodeURIComponent(lead.external_place_id)}?${params.toString()}`
}

/** Export only records already returned by the API; no additional backend contract is assumed. */
export function downloadLeadsJson(leads: BusinessLead[], filename = 'leads.json') {
  const blob = new Blob([JSON.stringify(leads, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export function BusinessLeadResults({ leads, selectable = false, selectedIds = [], onToggle }: { leads: BusinessLead[]; selectable?: boolean; selectedIds?: string[]; onToggle?: (lead: BusinessLead) => void }) {
  const keyFor = (lead: BusinessLead) => `${lead.source}:${lead.external_place_id ?? lead.name}`
  return <GlassCard className="business-results-card">
    <div className="business-results-scroll"><table className="business-results-table"><thead><tr>{selectable && <th><span className="sr-only">Select</span></th>}<th>Business</th><th>Location</th><th>Source</th><th>Website</th><th>Rating</th><th>Score</th><th>Priority</th><th>Status</th><th>Contacts</th><th><span className="sr-only">Open details</span></th></tr></thead><tbody>
      {leads.map((lead, index) => <BusinessLeadRow key={`${keyFor(lead)}:${index}`} lead={lead} selectable={selectable} selected={selectedIds.includes(keyFor(lead))} onToggle={onToggle} />)}
    </tbody></table></div>
    <div className="business-results-mobile">{leads.map((lead, index) => <BusinessLeadCard key={`${keyFor(lead)}:${index}`} lead={lead} selectable={selectable} selected={selectedIds.includes(keyFor(lead))} onToggle={onToggle} />)}</div>
  </GlassCard>
}

function BusinessLeadRow({ lead, selectable, selected, onToggle }: { lead: BusinessLead; selectable?: boolean; selected?: boolean; onToggle?: (lead: BusinessLead) => void }) {
  const path = businessLeadPath(lead)
  return <tr>{selectable && <td><button type="button" className={`lead-select-button${selected ? ' selected' : ''}`} aria-label={`${selected ? 'Deselect' : 'Select'} ${lead.name}`} aria-pressed={selected} onClick={() => onToggle?.(lead)}>{selected && <Check size={14} />}</button></td>}
    <td><BusinessName lead={lead} path={path} /></td>
    <td><span className="business-address-full">{lead.address || 'Address not returned'}</span></td>
    <td><Badge>{lead.source || 'Source unavailable'}</Badge></td>
    <td>{lead.website ? <Badge tone="green">Available</Badge> : <span className="business-secondary">Not returned</span>}</td>
    <td><Rating lead={lead} /></td>
    <td><Score value={lead.lead_score} /></td>
    <td><Priority value={lead.priority} /></td>
    <td>{lead.qualification_status ? <Badge>{lead.qualification_status}</Badge> : <span className="business-secondary">Not returned</span>}</td>
    <td><ContactDetails lead={lead} /></td>
    <td>{path ? <Link className="business-open-link" to={path} aria-label={`Open ${lead.name} details`}><ArrowUpRight size={16} /></Link> : <span className="business-no-id" title="The backend did not return a lead ID">—</span>}</td>
  </tr>
}

function BusinessLeadCard({ lead, selectable, selected, onToggle }: { lead: BusinessLead; selectable?: boolean; selected?: boolean; onToggle?: (lead: BusinessLead) => void }) {
  const path = businessLeadPath(lead)
  return <article className="business-mobile-card">
    <div className="business-mobile-heading"><div><strong>{lead.name}</strong><span>{lead.category || 'Category unavailable'}</span></div><div className="business-mobile-actions">{selectable && <button type="button" className={`lead-select-button${selected ? ' selected' : ''}`} aria-label={`${selected ? 'Deselect' : 'Select'} ${lead.name}`} aria-pressed={selected} onClick={() => onToggle?.(lead)}>{selected && <Check size={14} />}</button>}<Priority value={lead.priority} /></div></div>
    <p className="business-mobile-address"><MapPin size={14} />{lead.address || 'Address not returned'}</p>
    <div className="business-mobile-meta"><Rating lead={lead} /><Score value={lead.lead_score} /><Badge>{lead.source || 'Source unavailable'}</Badge>{lead.qualification_status && <Badge>{lead.qualification_status}</Badge>}</div>
    <span className="business-mobile-website">{lead.website ? 'Website returned' : 'No website returned'}</span>
    <ContactDetails lead={lead} />
    {path && <Link className="business-mobile-action" to={path}>View lead details <ArrowUpRight size={15} /></Link>}
  </article>
}

function BusinessName({ lead, path }: { lead: BusinessLead; path: string | null }) {
  return <div className="business-name-cell"><span className="business-name-mark">{lead.name.trim().slice(0, 1).toUpperCase() || 'B'}</span><span><strong>{path ? <Link to={path}>{lead.name}</Link> : lead.name}</strong><small>{lead.category || 'Category unavailable'}</small></span></div>
}

export function Score({ value }: { value: number | null }) {
  return value === null ? <span className="business-secondary">Not scored</span> : <span className="business-score">{value}<small>/100</small></span>
}

export function Priority({ value }: { value: string | null }) {
  if (!value) return <span className="business-secondary">No priority</span>
  const tone = value.toLowerCase() === 'high' ? 'business-priority high' : value.toLowerCase() === 'medium' ? 'business-priority medium' : value.toLowerCase() === 'low' ? 'business-priority low' : 'business-priority'
  return <span className={tone}>{value}</span>
}

export function Rating({ lead }: { lead: BusinessLead }) {
  return lead.rating === null ? <span className="business-secondary">No rating</span> : <span className="business-rating"><Star size={13} fill="currentColor" />{lead.rating.toFixed(1)}</span>
}

export function ContactAvailability({ lead }: { lead: BusinessLead }) {
  return <ContactDetails lead={lead} />
}

function ContactDetails({ lead }: { lead: BusinessLead }) {
  const phones = Array.from(new Set([lead.phone, ...lead.phone_numbers].filter((value): value is string => Boolean(value))))
  const emails = Array.from(new Set([lead.email, ...lead.contact_emails].filter((value): value is string => Boolean(value))))
  return <span className="business-contact-state">
    {phones.length ? phones.map(phone => <a key={phone} href={`tel:${phone}`}><Phone size={12} />{phone}</a>) : <span><Phone size={12} />No phone</span>}
    {emails.length ? emails.map(email => <a key={email} href={`mailto:${email}`}><Globe2 size={12} />{email}</a>) : <span><Globe2 size={12} />No email</span>}
  </span>
}

export function WebsiteLink({ value }: { value: string | null }) {
  if (!value) return <span className="business-secondary">No website returned</span>
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return <span className="business-secondary">{value}</span>
    return <a className="business-website-link" href={url.href} target="_blank" rel="noreferrer">{value}<ArrowUpRight size={13} /></a>
  } catch {
    return <span className="business-secondary">{value}</span>
  }
}
