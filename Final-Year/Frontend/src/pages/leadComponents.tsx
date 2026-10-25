import { Badge } from '../components/ui'

export function ScoreBadge({ score }: { score: number | null }) {
  return score === null ? <span className="score-unavailable">Not scored</span> : <span className="score-badge" aria-label={`Lead score ${score}`}><strong>{Number.isInteger(score) ? score : score.toFixed(1)}</strong><small>score</small></span>
}

export function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="table-secondary">—</span>
  const normalized = status.trim().toLowerCase()
  const tone = normalized === 'unqualified' || normalized.includes('reject') ? 'red' : normalized.includes('review') ? 'neutral' : normalized === 'qualified' ? 'green' : 'neutral'
  return <Badge tone={tone}>{status}</Badge>
}
