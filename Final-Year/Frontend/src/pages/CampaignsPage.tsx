import { Megaphone } from 'lucide-react'
import { EmptyState, GlassCard } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'

export function CampaignsPage() {
  return <>
    <PageHeader eyebrow="OUTREACH PLANNING" title="Campaigns" description="Campaign controls will appear when a campaign service is connected." />
    <GlassCard className="campaign-unavailable"><EmptyState icon={Megaphone} title="Campaign API unavailable" description="The connected backend does not expose campaign listing, creation, target selection, activation, execution progress, or activity endpoints. No campaigns or performance figures are being shown." /></GlassCard>
  </>
}
