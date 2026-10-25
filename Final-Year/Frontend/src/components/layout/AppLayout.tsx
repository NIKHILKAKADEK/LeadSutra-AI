import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, LogOut, Menu, Sparkles, X } from 'lucide-react'
import { Avatar, Dropdown, useToast } from '../ui'
import { useAuth } from '../../context/AuthContext'
import { mainNavigation, settingsNavigation } from '../../config/navigation'

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const { user, signOut } = useAuth()
  const { push } = useToast()
  const navigate = useNavigate()
  const current = [...mainNavigation, settingsNavigation].find(item => location.pathname === item.path)?.label ?? 'Workspace'
  const initials = user?.name.split(/\s+/).map(part => part[0]).join('').slice(0, 2).toUpperCase() ?? 'LS'

  async function handleSignOut() {
    try {
      await signOut()
      navigate('/login', { replace: true })
    } catch (error) {
      push({
        tone: 'error',
        title: 'Could not sign out',
        description: error instanceof Error ? error.message : 'Please retry.',
      })
    }
  }

  return <div className={`app-shell ${collapsed ? 'is-collapsed' : ''}`}>
    <div className={`sidebar-scrim ${mobileOpen ? 'visible' : ''}`} onClick={() => setMobileOpen(false)} />
    <aside className={`sidebar glass-panel ${mobileOpen ? 'mobile-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Sparkles size={17} strokeWidth={1.8} /></div><div className="brand-name">leadsutra<span>AI</span></div><button className="mobile-close icon-button" aria-label="Close menu" onClick={() => setMobileOpen(false)}><X size={18} /></button></div>
      <div className="workspace-switch"><div className="workspace-avatar">LS</div><div className="workspace-copy"><strong>LeadSutra AI</strong><small>Private workspace</small></div><ChevronRight size={15} /></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{mainNavigation.map(({ label, path, Icon }) => <NavLink key={path} to={path} onClick={() => setMobileOpen(false)} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><Icon size={18} strokeWidth={1.8} /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-tip"><span><Sparkles size={14} /> AI workspace</span><p>Your sales motion, brought into focus.</p></div><NavLink to={settingsNavigation.path} onClick={() => setMobileOpen(false)} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><settingsNavigation.Icon size={18} /><span>{settingsNavigation.label}</span></NavLink></div>
      <button className="collapse-button" onClick={() => setCollapsed(value => !value)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>{collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}</button>
    </aside>
    <div className="main-column">
      <header className="topbar glass-panel">
        <div className="topbar-left"><button className="mobile-menu icon-button" aria-label="Open menu" onClick={() => setMobileOpen(true)}><Menu size={19} /></button><div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><strong>{current}</strong></div></div>
        <div className="topbar-actions"><Dropdown label={<><Avatar initials={initials} /><span className="user-name">{user?.name ?? 'LeadSutra User'}</span><ChevronRight className="user-chevron" size={14} /></>}><div className="user-menu"><strong>{user?.name ?? 'LeadSutra User'}</strong><small>{user?.email}</small><small>Signed-in account</small><NavLink to="/settings">Account settings</NavLink><button className="user-menu-action" onClick={() => void handleSignOut()}><LogOut size={14} /> Sign out</button></div></Dropdown></div>
      </header>
      <main className="page-content" key={location.pathname}><Outlet /></main>
      <footer className="page-footer"><span>LeadSutra AI <span className="footer-dot">·</span> Built for intentional growth</span><span>Secure workspace</span></footer>
    </div>
  </div>
}
