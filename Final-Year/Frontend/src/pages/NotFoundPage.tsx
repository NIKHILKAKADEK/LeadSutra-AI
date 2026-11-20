import { ArrowLeft, Compass } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button, EmptyState, GlassCard } from '../components/ui'

export function NotFoundPage() {
  const navigate = useNavigate()
  return <div className="not-found-page"><GlassCard className="not-found-card"><div className="not-found-code" aria-hidden="true">404</div><EmptyState icon={Compass} title="This page isn’t on the map" description="The link may be outdated, or the page may have moved." action={<Button variant="secondary" onClick={() => navigate('/dashboard')}><ArrowLeft size={15}/> Back to overview</Button>}/></GlassCard></div>
}
