import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity as ActivityIcon, FileText, KeyRound, Link2, LogIn, Settings2, ShieldAlert,
} from 'lucide-react'
import { api } from '../../lib/api'
import type { ActivityEvent } from '../../lib/types'
import { eventLabel, relativeTime } from '../../lib/format'
import { Badge, EmptyState, PageHeader, Spinner } from '../../components/ui'

function iconFor(type: string) {
  if (type.startsWith('login') || type === 'logout') return LogIn
  if (type.startsWith('document')) return FileText
  if (type.startsWith('share')) return Link2
  if (type.startsWith('otp') || type === 'password_reset') return KeyRound
  if (type.startsWith('ai') || type.startsWith('rag')) return Settings2
  if (type.includes('denied') || type.includes('suspicious') || type.includes('rate')) return ShieldAlert
  return ActivityIcon
}

const CATEGORIES = [
  { value: 'all', label: 'All activity' },
  { value: 'document', label: 'Documents' },
  { value: 'share', label: 'Sharing' },
  { value: 'auth', label: 'Sign-ins' },
  { value: 'security', label: 'Security' },
]

export default function Activity() {
  const [events, setEvents] = useState<ActivityEvent[] | null>(null)
  const [cat, setCat] = useState('all')

  const load = useCallback(async () => {
    try {
      const data = await api<{ events: ActivityEvent[] }>('/activity?limit=120')
      setEvents(data.events)
    } catch {
      setEvents([])
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const filtered = useMemo(() => {
    const list = events ?? []
    if (cat === 'all') return list
    if (cat === 'security')
      return list.filter((e) =>
        ['authorization_denied', 'rate_limit_triggered', 'suspicious_activity', 'login_failure', 'otp_failure'].includes(e.event_type),
      )
    if (cat === 'auth')
      return list.filter((e) =>
        ['login_success', 'login_failure', 'logout', 'otp_success', 'otp_failure', 'otp_requested', 'password_reset', 'registration_completed'].includes(e.event_type),
      )
    if (cat === 'document') return list.filter((e) => e.event_type.startsWith('document'))
    return list.filter((e) => e.event_type.startsWith('share'))
  }, [events, cat])

  if (events === null) return <Spinner label="Loading activity…" />

  return (
    <div className="fade-up">
      <PageHeader
        title="Activity"
        subtitle="Your recorded events — the same records that power the security audit trail."
      />

      <div className="flex gap-1.5 flex-wrap mb-4">
        {CATEGORIES.map((c) => (
          <button
            key={c.value}
            onClick={() => setCat(c.value)}
            className={`rounded-full border px-3.5 py-1.5 text-[13px] transition-all focus-ring ${
              cat === c.value
                ? 'border-cognac/70 bg-cognac/8 text-cognac-deep'
                : 'border-beige bg-white/70 text-graphite hover:border-faint/60'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<ActivityIcon size={22} />}
          title="Nothing recorded yet"
          description="Sign-ins, uploads, shares and security events will appear here as you use OBSIDIAN."
        />
      ) : (
        <div className="panel-solid rounded-2xl p-5">
          <ol className="relative border-l border-[color:var(--color-beige-dark)] ml-2 space-y-5 pt-1">
            {filtered.map((e) => {
              const Icon = iconFor(e.event_type)
              const failed = e.result === 'failure' || e.result === 'denied'
              return (
                <li key={e.event_id} className="ml-5 relative">
                  <span
                    className={`absolute -left-[27px] top-0.5 w-5 h-5 rounded-full border flex items-center justify-center ${
                      failed ? 'bg-danger/10 border-danger/30 text-danger' : 'bg-ivory-deep border-beige-dark text-cognac'
                    }`}
                  >
                    <Icon size={11} />
                  </span>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-medium">{eventLabel(e.event_type)}</div>
                    <div className="flex items-center gap-2">
                      {failed && <Badge tone="danger">{e.result}</Badge>}
                      <span className="text-xs text-faint">{relativeTime(e.timestamp)}</span>
                    </div>
                  </div>
                  {Object.keys(e.metadata ?? {}).length > 0 && (
                    <div className="text-xs text-muted mt-0.5">
                      {Object.entries(e.metadata)
                        .slice(0, 3)
                        .map(([k, v]) => `${k}: ${String(v)}`)
                        .join(' · ')}
                    </div>
                  )}
                </li>
              )
            })}
          </ol>
        </div>
      )}
    </div>
  )
}
