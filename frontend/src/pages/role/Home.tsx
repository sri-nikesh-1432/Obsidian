import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity, ArrowRight, BadgeCheck, Briefcase, GraduationCap, KeyRound, Laptop,
  ScanSearch, ShieldCheck, UserRoundCheck,
} from 'lucide-react'
import { api } from '../../lib/api'
import { useAuth } from '../../store/auth'
import type { ActivityEvent } from '../../lib/types'
import type { Role } from '../../lib/roleProfile'
import { roleForm } from '../../lib/roleProfile'
import { eventLabel, relativeTime } from '../../lib/format'
import { Badge, Button, PageHeader, Spinner, StatCard } from '../../components/ui'

interface SessionRow {
  session_ref: string
  created_at: string
  last_seen_at: string
  current: boolean
}

export default function RoleHome() {
  const { user } = useAuth()
  const role = (user?.role as Role) ?? 'faculty'
  const form = roleForm(role)
  const isRecruiter = role === 'recruiter'

  const [profile, setProfile] = useState<Record<string, unknown> | null>(null)
  const [events, setEvents] = useState<ActivityEvent[] | null>(null)
  const [sessions, setSessions] = useState<SessionRow[] | null>(null)

  const load = useCallback(async () => {
    const [p, e, s] = await Promise.allSettled([
      api<{ profile: Record<string, unknown> }>('/profile'),
      api<{ events: ActivityEvent[] }>('/activity?limit=6'),
      api<{ sessions: SessionRow[] }>('/auth/sessions'),
    ])
    if (p.status === 'fulfilled') setProfile(p.value.profile)
    if (e.status === 'fulfilled') setEvents(e.value.events)
    if (s.status === 'fulfilled') setSessions(s.value.sessions)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (!user) return <Spinner />

  const name = String(profile?.full_name || user.email || 'there')
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'

  const headline = isRecruiter
    ? 'Review the profiles students have opened to you.'
    : 'Look up a student by their exact ID to verify what they have shared.'

  const identityKeys = form.fields
    .filter((f) => f.kind !== 'list' && f.kind !== 'textarea' && f.name !== 'full_name' && f.name !== 'phone')
    .map((f) => ({ label: f.label.replace(/ \(.*\)$/, ''), value: String((profile?.[f.name] as string) ?? '') }))
    .filter((f) => f.value)

  const listKeys = form.fields
    .filter((f) => f.kind === 'list')
    .map((f) => ({ label: f.label, values: ((profile?.[f.name] as string[] | undefined) ?? []) }))
    .filter((f) => f.values.length > 0)

  return (
    <div className="fade-up">
      <PageHeader
        title={`${greeting}, ${name.split(' ')[0]}`}
        subtitle={headline}
        actions={
          <Link to="/app/find-student" className="btn btn-accent focus-ring">
            <ScanSearch size={15} /> Find a student
          </Link>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Access model" value="ID-only" icon={isRecruiter ? <Briefcase size={15} /> : <GraduationCap size={15} />}
          hint="no directory, no browsing" />
        <StatCard label="MFA" value="On" icon={<KeyRound size={15} />} hint="email code at sign-in" />
        <StatCard label="Active sessions" value={sessions?.length ?? '—'} icon={<Laptop size={15} />} hint="server-side, revocable" />
        <StatCard label="Recent activity" value={events?.length ?? '—'} icon={<Activity size={15} />} hint="last 6 events" />
      </div>

      <div className="grid lg:grid-cols-3 gap-4 mt-4">
        {/* identity + quick action */}
        <div className="lg:col-span-2 space-y-4">
          <div className="glass rounded-2xl p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="w-14 h-14 rounded-2xl bg-cognac/12 text-cognac-deep ring-1 ring-cognac/20 flex items-center justify-center text-lg font-semibold">
                  {(name || '?').slice(0, 1).toUpperCase()}
                </div>
                <div>
                  <h2 className="text-xl font-semibold text-editorial">{String(profile?.full_name || user.email)}</h2>
                  <div className="text-sm text-muted mt-0.5">{user.email}</div>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge tone="accent" icon={isRecruiter ? <Briefcase size={11} /> : <GraduationCap size={11} />}>
                  {isRecruiter ? 'Recruiter' : 'Faculty'}
                </Badge>
                <Badge tone="success" icon={<BadgeCheck size={11} />}>Verified</Badge>
              </div>
            </div>

            {identityKeys.length > 0 && (
              <div className="mt-5 pt-4 border-t hairline grid sm:grid-cols-3 gap-4">
                {identityKeys.map((f) => (
                  <div key={f.label}>
                    <div className="text-faint text-[11px] uppercase tracking-wider">{f.label}</div>
                    <div className="mt-0.5 text-[13.5px] font-medium">{f.value}</div>
                  </div>
                ))}
              </div>
            )}

            {listKeys.map((l) => (
              <div key={l.label} className="mt-4">
                <div className="eyebrow">{l.label}</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {l.values.map((v) => (
                    <span key={v} className="rounded-full bg-white/80 border hairline px-2.5 py-1 text-[12.5px]">{v}</span>
                  ))}
                </div>
              </div>
            ))}

            <div className="mt-5 flex flex-wrap gap-3">
              <Link to="/app/profile" className="btn btn-soft btn-sm focus-ring">Edit profile</Link>
              <Link to="/app/security" className="btn btn-ghost btn-sm focus-ring">Security center</Link>
            </div>
          </div>

          {/* quick lookup prompt */}
          <Link
            to="/app/find-student"
            className="glass-hover block glass rounded-2xl p-6"
          >
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-start gap-4">
                <div className="w-11 h-11 rounded-2xl bg-cognac/10 text-cognac flex items-center justify-center shrink-0">
                  <ScanSearch size={18} />
                </div>
                <div>
                  <h3 className="text-[15px] font-semibold">
                    {isRecruiter ? 'Review a candidate profile' : 'Verify a student record'}
                  </h3>
                  <p className="text-sm text-muted mt-1 max-w-lg leading-relaxed">
                    Enter the student’s exact issued ID. OBSIDIAN returns only the fields they
                    have deliberately exposed — failed lookups are generic and audited.
                  </p>
                </div>
              </div>
              <ArrowRight size={17} className="text-faint shrink-0" />
            </div>
          </Link>
        </div>

        {/* side column */}
        <div className="space-y-4">
          <div className="panel-solid rounded-2xl p-5">
            <div className="flex items-center gap-2.5">
              <ShieldCheck size={16} className="text-success" />
              <h3 className="text-[15px] font-semibold">Your access</h3>
            </div>
            <ul className="mt-3 space-y-2 text-[13px] text-graphite">
              <li className="flex items-center justify-between">
                Profile lookup <Badge tone="success">Enabled</Badge>
              </li>
              <li className="flex items-center justify-between">
                Document directory <Badge tone="neutral">None</Badge>
              </li>
              <li className="flex items-center justify-between">
                Private vault <Badge tone="danger">No access</Badge>
              </li>
              <li className="flex items-center justify-between">
                Every access <Badge tone="info">Audited</Badge>
              </li>
            </ul>
            <p className="text-xs text-muted mt-3 flex items-start gap-1.5">
              <UserRoundCheck size={12} className="mt-0.5 shrink-0 text-success" />
              A student controls exactly which fields and documents you can see.
            </p>
          </div>

          <div className="panel-solid rounded-2xl p-5">
            <div className="flex items-center justify-between">
              <h3 className="text-[15px] font-semibold flex items-center gap-2">
                <Activity size={15} className="text-cognac" /> Recent activity
              </h3>
              <Link to="/app/security" className="text-[13px] text-cognac-deep hover:underline">
                View all
              </Link>
            </div>
            {events === null ? (
              <Spinner label="Loading…" />
            ) : (
              <div className="mt-3 space-y-2">
                {events.slice(0, 6).map((e) => (
                  <div key={e.event_id} className="flex items-center justify-between text-[13px]">
                    <span className="text-graphite">{eventLabel(e.event_type)}</span>
                    <span className="text-faint">{relativeTime(e.timestamp)}</span>
                  </div>
                ))}
                {events.length === 0 && <p className="text-sm text-muted">No activity recorded yet.</p>}
              </div>
            )}
          </div>

          <div className="rounded-2xl border hairline bg-white/60 p-5">
            <Button variant="soft" size="sm" className="w-full" onClick={() => void load()}>
              Refresh
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
