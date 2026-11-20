import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { ProtectedRoute } from './components/layout/ProtectedRoute'
import { AuthProvider } from './context/AuthContext'
import { ToastProvider } from './components/ui'
import { DashboardPage } from './pages/DashboardPage'
import { DiscoveryPage } from './pages/DiscoveryPage'
import { LeadsPage } from './pages/LeadsPage'
import { OutreachCenter } from './pages/OutreachCenter'
import { LoginPage } from './pages/LoginPage'
import { LoadingState } from './components/ui'
import { ProposalsPage } from './pages/ProposalsPage'
import { CrmPage } from './pages/CrmPage'
import { CampaignsPage } from './pages/CampaignsPage'
import { SignupPage } from './pages/SignupPage'
import { LandingPage } from './pages/LandingPage'

const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage').then(module => ({ default: module.AnalyticsPage })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then(module => ({ default: module.SettingsPage })))
const LeadDetailsPage = lazy(() => import('./pages/LeadDetailsPage').then(module => ({ default: module.LeadDetailsPage })))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then(module => ({ default: module.NotFoundPage })))

export default function App() {
  return <AuthProvider><ToastProvider><Suspense fallback={<div className="route-loading"><LoadingState label="Preparing your workspace" /></div>}><Routes>
    <Route path="/" element={<LandingPage/>}/>
    <Route path="/login" element={<LoginPage/>}/>
    <Route path="/signup" element={<SignupPage/>}/>
    <Route element={<ProtectedRoute/>}><Route element={<AppLayout/>}>
      <Route path="/dashboard" element={<DashboardPage/>}/>
      <Route path="/leads" element={<LeadsPage/>}/>
      <Route path="/leads/:leadId" element={<LeadDetailsPage/>}/>
      <Route path="/crm" element={<CrmPage/>}/>
      <Route path="/discovery" element={<DiscoveryPage/>}/>
      <Route path="/outreach" element={<OutreachCenter/>}/>
      <Route path="/campaigns" element={<CampaignsPage/>}/>
      <Route path="/proposals" element={<ProposalsPage/>}/>
      <Route path="/calls" element={<OutreachCenter/>}/>
      <Route path="/analytics" element={<AnalyticsPage/>}/>
      <Route path="/settings" element={<SettingsPage/>}/>
      <Route path="*" element={<NotFoundPage/>}/>
    </Route></Route>
  </Routes></Suspense></ToastProvider></AuthProvider>
}
