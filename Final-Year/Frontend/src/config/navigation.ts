import { Activity, AudioLines, Compass, LayoutDashboard, ListFilter, Settings2, Users, type LucideIcon } from 'lucide-react'

export type NavigationItem = {
  label: string
  path: string
  Icon: LucideIcon
}

export const mainNavigation: NavigationItem[] = [
  { label: 'Overview', path: '/dashboard', Icon: LayoutDashboard },
  { label: 'Leads', path: '/leads', Icon: Users },
  { label: 'Discovery', path: '/discovery', Icon: Compass },
  { label: 'Outreach', path: '/outreach', Icon: AudioLines },
  { label: 'Calls', path: '/calls', Icon: Activity },
  { label: 'Analytics', path: '/analytics', Icon: ListFilter },
]

export const settingsNavigation: NavigationItem = {
  label: 'Settings',
  path: '/settings',
  Icon: Settings2,
}
