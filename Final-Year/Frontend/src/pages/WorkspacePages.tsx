import { Activity, AudioLines, BarChart3, Compass, Plus, Sparkles, Target, Users, ArrowUpRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Badge, Button, EmptyState, GlassCard, SearchInput } from '../components/ui'
import { PageHeader } from '../components/shared/PageHeader'

const descriptions: Record<string, string> = {
  Leads: 'Build a focused pipeline around the people who matter.', Discovery: 'Find the right accounts and uncover useful context.', Outreach: 'Shape thoughtful conversations at every touchpoint.', Campaigns: 'Coordinate your team’s next focused sales motion.', Calls: 'Keep conversations and next steps in one place.', Analytics: 'Understand what is moving your pipeline forward.', Settings: 'Make this workspace feel like yours.',
}
const icons: Record<string, typeof Users> = { Leads: Users, Discovery: Compass, Outreach: AudioLines, Campaigns: Target, Calls: Activity, Analytics: BarChart3, Settings: Sparkles }
export function OverviewPage() {
  const navigate = useNavigate()
  return <>
    <PageHeader eyebrow="TUESDAY, OCTOBER 6" title="A clearer path to your next win." description="Your sales development workspace is ready when you are." actions={<Button variant="primary" onClick={() => navigate('/leads')}><Plus size={16} /> Add your first lead</Button>} />
    <section className="welcome-card glass-card"><div className="welcome-copy"><div className="welcome-kicker"><Sparkles size={14} /> A FRESH START</div><h2>Good morning, Jordan<span>.</span></h2><p>Great sales starts with a little curiosity. Bring your first prospect into the workspace and see where the conversation leads.</p><Button variant="secondary" onClick={() => navigate('/discovery')}>Explore discovery <ArrowUpRight size={15} /></Button></div><div className="welcome-visual" aria-hidden="true"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="orbit-core"><Sparkles size={23}/></div><span className="orbit-node node-one"/><span className="orbit-node node-two"/><span className="orbit-node node-three"/></div></section>
    <div className="section-heading"><div><h2>Your workspace</h2><p>Everything you need to move from signal to conversation.</p></div><Badge>JUST GETTING STARTED</Badge></div>
    <div className="overview-grid"><GlassCard className="overview-panel"><div className="panel-title"><div className="panel-icon"><Users size={17}/></div><div><h3>Lead pipeline</h3><p>Find and organize your prospects</p></div><span className="panel-arrow"><ArrowUpRight size={15}/></span></div><div className="panel-empty"><span className="soft-rule"/><span className="soft-rule short"/><span className="soft-rule"/><div className="empty-overlay"><span>—</span><small>Ready for your first lead</small></div></div><button className="panel-link" onClick={() => navigate('/leads')}>Open leads <ArrowUpRight size={14}/></button></GlassCard>
      <GlassCard className="overview-panel"><div className="panel-title"><div className="panel-icon violet"><AudioLines size={17}/></div><div><h3>Outreach activity</h3><p>Thoughtful touchpoints, in one place</p></div><span className="panel-arrow"><ArrowUpRight size={15}/></span></div><div className="activity-placeholder"><div className="activity-line"><i/><span/><b/></div><div className="activity-line"><i/><span/><b/></div><div className="activity-line"><i/><span/><b/></div><div className="activity-line"><i/><span/><b/></div><div className="activity-caption">Your activity will appear here</div></div><button className="panel-link" onClick={() => navigate('/outreach')}>Explore outreach <ArrowUpRight size={14}/></button></GlassCard></div>
    <GlassCard className="next-step"><div className="next-icon"><Compass size={19}/></div><div className="next-copy"><h3>Start with a little discovery</h3><p>Bring a company or role into focus before your first introduction.</p></div><Button variant="ghost" onClick={() => navigate('/discovery')}>Go to discovery <ArrowUpRight size={15}/></Button></GlassCard>
  </>
}
export function SectionPage({ title }: { title: string }) {
  const Icon = icons[title] ?? Sparkles
  return <><PageHeader eyebrow="WORKSPACE" title={title} description={descriptions[title] ?? 'Your workspace, ready for what’s next.'} actions={title === 'Leads' ? <Button variant="primary"><Plus size={16}/> Add lead</Button> : undefined}/>
    {title === 'Leads' && <div className="toolbar"><SearchInput placeholder="Search leads..."/><Button variant="secondary">Filters</Button></div>}
    <GlassCard className="section-empty-card"><EmptyState icon={Icon} title={title === 'Settings' ? 'Your preferences live here' : `Your ${title.toLowerCase()} space is ready`} description={title === 'Settings' ? 'Workspace preferences and account controls will appear here as they become available.' : `There’s nothing here yet. When ${title.toLowerCase()} are connected to your workspace, you’ll find them here.`}/></GlassCard>
    <div className="section-footnote"><span className="connection-dot"/> This workspace is ready to connect to your sales workflow.</div>
  </>
}
