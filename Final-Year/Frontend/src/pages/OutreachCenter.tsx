import { useLocation, useNavigate } from 'react-router-dom'
import { AudioLines, CalendarClock, Mail, ShieldCheck } from 'lucide-react'
import { PageHeader } from '../components/shared/PageHeader'
import { Badge } from '../components/ui'
import { EmailComposer } from './outreach/EmailComposer'
import { CallsPanel } from './outreach/CallsPanel'
import { FollowUpsPanel } from './outreach/FollowUpsPanel'

type Tab = 'email' | 'calls' | 'followups'
export function OutreachCenter() {
  const location = useLocation(); const navigate = useNavigate()
  const tab: Tab = location.pathname === '/calls' ? 'calls' : new URLSearchParams(location.search).get('tab') === 'followups' ? 'followups' : 'email'
  return <>
    <PageHeader eyebrow="OUTREACH" title="Build better conversations." description="Email, calls, and follow-ups in one place." actions={<Badge><ShieldCheck size={11}/> SECURE</Badge>}/>
    <nav className="outreach-tabs" aria-label="Outreach tools">
      <button className={tab === 'email' ? 'active' : ''} onClick={() => navigate('/outreach')}><Mail size={15}/> Email</button>
      <button className={tab === 'calls' ? 'active' : ''} onClick={() => navigate('/calls')}><AudioLines size={15}/> Calls</button>
      <button className={tab === 'followups' ? 'active' : ''} onClick={() => navigate('/outreach?tab=followups')}><CalendarClock size={15}/> Follow-ups</button>
    </nav>
    {tab === 'email' ? <EmailComposer/> : tab === 'calls' ? <CallsPanel/> : <FollowUpsPanel/>}
  </>
}
