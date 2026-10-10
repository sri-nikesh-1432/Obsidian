import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth, homePathFor } from './store/auth'
import { Spinner } from './components/ui'
import AppShell from './components/AppShell'
import type { Role } from './lib/types'

import Landing from './pages/Landing'
import About from './pages/About'
import SecurityPage from './pages/SecurityPage'
import Login from './pages/auth/Login'
import Signup from './pages/auth/Signup'
import Verify from './pages/auth/Verify'
import Forgot from './pages/auth/Forgot'
import Reset from './pages/auth/Reset'
import GoogleComplete from './pages/auth/GoogleComplete'
import Onboarding from './pages/auth/Onboarding'

import Dashboard from './pages/student/Dashboard'
import Vault from './pages/student/Vault'
import DocumentDetail from './pages/student/DocumentDetail'
import Links from './pages/student/Links'
import ProfilePage from './pages/student/Profile'
import Activity from './pages/student/Activity'
import SecurityCenter from './pages/student/SecurityCenter'
import Intelligence from './pages/student/Intelligence'
import Billing from './pages/student/Billing'

import FindStudent from './pages/role/FindStudent'
import Admin from './pages/role/Admin'
import SharedLink from './pages/SharedLink'
import NotFound from './pages/NotFound'

function FullPageLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="text-[11px] font-semibold tracking-[0.34em] text-cognac mb-4">OBSIDIAN</div>
        <Spinner label="Opening your vault…" />
      </div>
    </div>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <FullPageLoader />
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />
  if (!user.onboarding_complete && location.pathname !== '/onboarding') {
    return <Navigate to="/onboarding" replace />
  }
  if (user.onboarding_complete && location.pathname === '/onboarding') {
    return <Navigate to={homePathFor(user.role)} replace />
  }
  return <>{children}</>
}

function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <FullPageLoader />
  if (!user) return <Navigate to="/login" replace />
  if (!roles.includes(user.role!)) {
    return (
      <div className="max-w-md mx-auto py-24 text-center">
        <h1 className="text-xl font-semibold">Access denied</h1>
        <p className="text-sm text-muted mt-2">
          Your account does not have permission to view this area.
        </p>
        <Navigate to={homePathFor(user.role)} replace />
      </div>
    )
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      {/* public */}
      <Route path="/" element={<Landing />} />
      <Route path="/about" element={<About />} />
      <Route path="/security" element={<SecurityPage />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/verify" element={<Verify />} />
      <Route path="/forgot" element={<Forgot />} />
      <Route path="/reset" element={<Reset />} />
      <Route path="/auth/complete" element={<GoogleComplete />} />
      <Route path="/s/:token" element={<SharedLink />} />

      {/* onboarding */}
      <Route
        path="/onboarding"
        element={
          <RequireAuth>
            <Onboarding />
          </RequireAuth>
        }
      />

      {/* application */}
      <Route
        path="/app"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/app/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="vault" element={<Vault />} />
        <Route path="vault/:id" element={<DocumentDetail />} />
        <Route path="links" element={<Links />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="activity" element={<Activity />} />
        <Route path="security" element={<SecurityCenter />} />
        <Route path="intelligence" element={<Intelligence />} />
        <Route path="storage" element={<Billing />} />
        <Route
          path="find-student"
          element={
            <RequireRole roles={['faculty', 'recruiter']}>
              <FindStudent />
            </RequireRole>
          }
        />
        <Route
          path="admin"
          element={
            <RequireRole roles={['admin']}>
              <Admin />
            </RequireRole>
          }
        />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
