import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity, BookOpenCheck, ChevronDown, FileStack, FolderLock, HardDrive,
  LayoutDashboard, Link2, LogOut, Menu, ScanSearch, ShieldCheck, Sparkles,
  UserRound, Users, X,
} from 'lucide-react'
import { useAuth, homePathFor } from '../store/auth'
import { initials } from '../lib/format'
import type { Role } from '../lib/types'
import StorageMeter from './StorageMeter'

interface NavItem {
  to: string
  label: string
  icon: typeof LayoutDashboard
  end?: boolean
}

function primaryNavFor(role?: Role, aiEnabled?: boolean): NavItem[] {
  if (role === 'faculty') {
    return [
      { to: '/app/home', label: 'Home', icon: LayoutDashboard, end: true },
      { to: '/app/groups', label: 'Groups', icon: Users },
      { to: '/app/find-student', label: 'Find a student', icon: ScanSearch },
    ]
  }
  if (role === 'recruiter') {
    return [
      { to: '/app/home', label: 'Home', icon: LayoutDashboard, end: true },
      { to: '/app/find-student', label: 'Find a student', icon: ScanSearch },
    ]
  }
  if (role === 'admin') {
    return [
      { to: '/app/admin', label: 'Administration', icon: ShieldCheck, end: true },
    ]
  }
  const items: NavItem[] = [
    { to: '/app/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/app/vault', label: 'Documents', icon: FolderLock },
    { to: '/app/groups', label: 'Groups', icon: Users },
    { to: '/app/links', label: 'Shared links', icon: Link2 },
    { to: '/app/activity', label: 'Activity', icon: Activity },
  ]
  if (aiEnabled) {
    items.push({ to: '/app/intelligence', label: 'Intelligence', icon: Sparkles })
  }
  items.push({ to: '/app/storage', label: 'Storage', icon: HardDrive })
  return items
}

// The same two account destinations for every role, so switching identities
// never changes the shape of the interface — only what the role may do.
const ACCOUNT_NAV: NavItem[] = [
  { to: '/app/profile', label: 'Profile', icon: UserRound },
  { to: '/app/security', label: 'Security', icon: ShieldCheck },
]

const ROLE_LABEL: Record<Role, string> = {
  student: 'Student',
  faculty: 'Faculty',
  recruiter: 'Recruiter',
  admin: 'Administrator',
}

function NavItemLink({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all focus-ring ${
          isActive
            ? 'bg-charcoal text-[#f5f0e6] shadow-[0_10px_24px_-16px_rgba(27,24,21,0.9)]'
            : 'text-graphite hover:bg-white/70'
        }`
      }
    >
      <item.icon size={16} strokeWidth={1.9} />
      <span className="font-medium">{item.label}</span>
    </NavLink>
  )
}

export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const primary = primaryNavFor(user?.role, user?.ai_enabled)

  useEffect(() => {
    setMobileOpen(false)
    setMenuOpen(false)
  }, [location.pathname])

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const displayName = user?.profile?.full_name || user?.email || 'Account'
  const sidebar = (
    <div className="flex flex-col h-full">
      <div className="px-5 pt-6 pb-5">
        <NavLink to={homePathFor(user?.role)} className="block group">
          <div className="text-[11px] font-semibold tracking-[0.34em] text-cognac">OBSIDIAN</div>
          <div className="text-[11px] text-faint mt-1 group-hover:text-muted transition-colors">
            Your documents. Your keys.
          </div>
        </NavLink>
      </div>

      <nav className="flex-1 px-3 overflow-y-auto scrollbar-thin" aria-label="Primary">
        <div className="space-y-1">
          {primary.map((item) => (
            <NavItemLink key={item.to} item={item} />
          ))}
        </div>
        <div className="pt-5 pb-1.5 px-3">
          <span className="text-[10px] font-semibold tracking-[0.22em] uppercase text-faint">Account</span>
        </div>
        <div className="space-y-1 pb-2">
          {ACCOUNT_NAV.map((item) => (
            <NavItemLink key={item.to} item={item} />
          ))}
        </div>
      </nav>

      <div className="p-3 mt-auto space-y-3">
        {user?.role === 'student' && user.storage && (
          <NavLink to="/app/storage" className="block rounded-xl focus-ring">
            <StorageMeter storage={user.storage} compact />
          </NavLink>
        )}
        <div className="rounded-xl border hairline bg-white/70 p-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-cognac/12 text-cognac-deep flex items-center justify-center text-xs font-semibold ring-1 ring-cognac/20">
              {initials(user?.profile?.full_name || user?.email || '')}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium truncate">{displayName}</div>
              <div className="text-[11px] text-faint uppercase tracking-wider">
                {user?.role ? ROLE_LABEL[user.role] : ''}
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="text-faint hover:text-danger transition-colors focus-ring rounded-md p-1.5"
              title="Sign out"
              aria-label="Sign out"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen flex">
      {/* desktop sidebar */}
      <aside className="hidden lg:block w-64 shrink-0 sticky top-0 h-screen glass border-r border-white/60">
        {sidebar}
      </aside>

      {/* mobile drawer */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-charcoal/30 backdrop-blur-[2px]" onClick={() => setMobileOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-72 glass border-r border-white/60">
            <button
              className="absolute top-4 right-4 text-faint focus-ring rounded p-1"
              onClick={() => setMobileOpen(false)}
              aria-label="Close navigation"
            >
              <X size={18} />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-40 glass border-b border-white/60">
          <div className="flex items-center justify-between px-4 sm:px-6 h-14">
            <div className="flex items-center gap-3">
              <button
                className="lg:hidden text-graphite focus-ring rounded-md p-1.5"
                onClick={() => setMobileOpen(true)}
                aria-label="Open navigation"
              >
                <Menu size={18} />
              </button>
              <div className="hidden sm:flex items-center gap-2 text-[13px] text-muted">
                <BookOpenCheck size={15} className="text-cognac" />
                <span>Secure document vault</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className="hidden sm:inline-flex items-center gap-1.5 rounded-full border hairline bg-white/70 px-3 py-1 text-[11.5px] text-graphite">
                <FileStack size={12} className="text-success" />
                AES-256-GCM encrypted
              </span>
              <div className="relative">
                <button
                  onClick={() => setMenuOpen((v) => !v)}
                  className="flex items-center gap-2 rounded-full border hairline bg-white/70 pl-1.5 pr-2.5 py-1.5 hover:bg-white transition-colors focus-ring"
                  aria-expanded={menuOpen}
                  aria-label="Account menu"
                >
                  <span className="w-6 h-6 rounded-full bg-charcoal text-[#f5f0e6] text-[10px] font-semibold flex items-center justify-center">
                    {initials(user?.profile?.full_name || user?.email || '')}
                  </span>
                  <ChevronDown size={13} className="text-faint" />
                </button>
                {menuOpen && (
                  <div className="absolute right-0 mt-2 w-56 glass rounded-xl p-2 fade-up">
                    <div className="px-3 py-2">
                      <div className="text-sm font-medium truncate">{displayName}</div>
                      <div className="text-xs text-muted truncate">{user?.email}</div>
                    </div>
                    <div className="h-px bg-beige/70 my-1" />
                    <button
                      onClick={() => navigate('/app/profile')}
                      className="w-full text-left px-3 py-2 text-sm rounded-lg hover:bg-white/80 transition-colors focus-ring"
                    >
                      Profile settings
                    </button>
                    <button
                      onClick={() => navigate('/app/security')}
                      className="w-full text-left px-3 py-2 text-sm rounded-lg hover:bg-white/80 transition-colors focus-ring"
                    >
                      Security center
                    </button>
                    <div className="h-px bg-beige/70 my-1" />
                    <button
                      onClick={handleLogout}
                      className="w-full text-left px-3 py-2 text-sm rounded-lg text-danger hover:bg-danger/5 transition-colors focus-ring"
                    >
                      Sign out
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </header>

        <main className="flex-1 px-4 sm:px-6 lg:px-8 py-6 lg:py-8 max-w-6xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
