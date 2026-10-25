import { FileText, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState, GlassCard } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'

export function ProposalsPage() {
  return <>
    <PageHeader eyebrow="PROPOSALS" title="Turn lead context into a proposal." description="Generate a proposal email for a selected lead from the protected outreach workflow." />
    <GlassCard className="proposal-unavailable-card">
      <EmptyState icon={FileText} title="Create a proposal from a lead" description="Open the email workspace, select a lead, and generate a proposal email. Review and approve it before any send is queued." action={<Link className="button button-primary" to="/outreach"><Sparkles size={14}/> Open email workspace</Link>} />
      <div className="proposal-contract-list" aria-label="Proposal API requirements">
        <span><Sparkles size={14} /> Proposal generation and lead association are available</span>
        <span><FileText size={14} /> Email send requires a verified contact and an approved draft</span>
        <span><FileText size={14} /> Proposal browsing, editing, and PDF export are not available here</span>
      </div>
    </GlassCard>
  </>
}
