import { useCallback, useEffect, useState } from 'react'
import {
  Activity, BarChart3, Database, FileStack, Link2, MessageSquare, Server, ShieldAlert, Users,
} from 'lucide-react'
import { api } from '../../lib/api'
import type { AdminAnalytics } from '../../lib/types'
import { eventLabel, formatBytes, relativeTime } from '../../lib/format'
import {
  Badge, Button, EmptyState, PageHeader, Spinner, StatCard,
} from '../../components/ui'

type Tab = 'overview' | 'users' | 'security' | 'activity' | 'shares' | 'rag'

const TABS: { id: Tab; label: string; icon: typeof Users }[] = [
  { id: 'overview', label: 'Overview', icon: BarChart3 },
  { id: 'users', label: 'Users', icon: Users },
  { id: 'security', label: 'Security', icon: ShieldAlert },
  { id: 'activity', label: 'System activity', icon: Activity },
  { id: 'shares', label: 'Share links', icon: Link2 },
  { id: 'rag', label: 'Storage & RAG', icon: Database },
]

interface AdminUser {
  user_id: string
  email: string
  role: string
  status: string
  mfa_enabled: boolean
  ai_enabled: boolean
  created_at: string
  last_login_at: string
}

interface AdminEvent {
  event_id: string
  event_type: string
  timestamp: string
  actor_id: string
  actor_role: string
  result: string
  request_id: string
  metadata: Record<string, unknown>
}

interface AdminShare {
  share_id: string
  mode: string
  permission: string
  status: string
  created_at: string
  expires_at: string
  access_count: number
  document_id: string
}

interface RagStats {
  total_instances: number
  enabled: number
  disabled: number
  total_chunks: number
  isolation_model: string
}

export default function Admin() {
  const [tab, setTab] = useState<Tab>('overview')
  const [analytics, setAnalytics] = useState<AdminAnalytics | null>(null)
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [events, setEvents] = useState<AdminEvent[] | null>(null)
  const [activity, setActivity] = useState<AdminEvent[] | null>(null)
  const [shares, setShares] = useState<{ summary: Record<string, number>; shares: AdminShare[] } | null>(null)
  const [rag, setRag] = useState<RagStats | null>(null)
  const [loading, setLoading] = useState(true)

  const loadAll = useCallback(async () => {
    setLoading(true)
    const [a, u, se, ac, sh, rg] = await Promise.allSettled([
      api<AdminAnalytics>('/admin/analytics'),
      api<{ users: AdminUser[] }>('/admin/users?limit=200'),
      api<{ events: AdminEvent[] }>('/admin/security-events?limit=60'),
      api<{ events: AdminEvent[] }>('/admin/activity'),
      api<{ summary: Record<string, number>; shares: AdminShare[] }>('/admin/shares'),
      api<RagStats>('/admin/rag'),
    ])
    if (a.status === 'fulfilled') setAnalytics(a.value)
    if (u.status === 'fulfilled') setUsers(u.value.users)
    if (se.status === 'fulfilled') setEvents(se.value.events)
    if (ac.status === 'fulfilled') setActivity(ac.value.events)
    if (sh.status === 'fulfilled') setShares(sh.value)
    if (rg.status === 'fulfilled') setRag(rg.value)
    setLoading(false)
  }, [])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  if (loading && !analytics) return <Spinner label="Loading analytics…" />

  return (
    <div className="fade-up">
      <PageHeader
        title="Administration"
        subtitle="Aggregate operational visibility. Private document contents are never exposed here — by policy."
        actions={
          <Button variant="soft" onClick={() => void loadAll()}>
            Refresh
          </Button>
        }
      />

      {/* tabs */}
      <div className="flex gap-1.5 flex-wrap mb-5">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-[13px] transition-all focus-ring ${
              tab === t.id
                ? 'border-cognac/70 bg-cognac/8 text-cognac-deep'
                : 'border-beige bg-white/70 text-graphite hover:border-faint/60'
            }`}
          >
            <t.icon size={13} /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && analytics && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="Total users" value={analytics.users.total} icon={<Users size={15} />}
              hint={`${analytics.users.by_role.student ?? 0} students · ${analytics.users.by_role.faculty ?? 0} faculty`} />
            <StatCard label="Documents" value={analytics.documents.total} icon={<FileStack size={15} />}
              hint={`${analytics.documents.private} private · ${analytics.documents.public} public`} />
            <StatCard label="Storage" value={formatBytes(analytics.documents.storage_bytes)} icon={<Database size={15} />}
              hint="ciphertext at rest" />
            <StatCard label="Share links" value={analytics.shares.total} icon={<Link2 size={15} />}
              hint={`${analytics.shares.active} active · ${analytics.shares.expired} expired · ${analytics.shares.revoked} revoked`} />
            <StatCard label="Groups" value={analytics.groups?.total ?? 0} icon={<MessageSquare size={15} />}
              hint={`${analytics.groups?.memberships ?? 0} members · ${analytics.groups?.messages ?? 0} messages`} />
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <div className="panel-solid rounded-2xl p-5">
              <div className="eyebrow">Security counters</div>
              <div className="mt-3 space-y-2 text-[13px]">
                {Object.entries(analytics.security).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between">
                    <span className="text-muted">{eventLabel(k)}</span>
                    <span className={`font-semibold tabular-nums ${v > 0 ? 'text-warning' : 'text-success'}`}>{v}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="panel-solid rounded-2xl p-5">
              <div className="eyebrow flex items-center gap-2"><Server size={12} /> System health</div>
              <div className="mt-3 space-y-2 text-[13px]">
                {Object.entries(analytics.health).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between gap-3">
                    <span className="text-muted">{k.replace(/_/g, ' ')}</span>
                    <span className="font-medium text-right">{v}</span>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Badge tone="success">MFA: {analytics.users.mfa_enabled}/{analytics.users.total}</Badge>
                <Badge tone="accent">AI enabled: {analytics.users.ai_enabled}</Badge>
                <Badge tone="info">Profile-visible docs: {analytics.documents.profile_visible}</Badge>
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'users' && (
        <div className="panel-solid rounded-2xl overflow-hidden">
          {users === null ? (
            <Spinner label="Loading users…" />
          ) : (
            <div className="overflow-x-auto scrollbar-thin">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left border-b hairline bg-ivory-deep/50">
                    <th className="px-4 py-2.5 font-medium text-muted">Email</th>
                    <th className="px-4 py-2.5 font-medium text-muted">Role</th>
                    <th className="px-4 py-2.5 font-medium text-muted">Status</th>
                    <th className="px-4 py-2.5 font-medium text-muted">MFA</th>
                    <th className="px-4 py-2.5 font-medium text-muted">AI</th>
                    <th className="px-4 py-2.5 font-medium text-muted">Created</th>
                    <th className="px-4 py-2.5 font-medium text-muted">Last sign-in</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.user_id} className="border-b border-[color:var(--color-beige)] last:border-0">
                      <td className="px-4 py-2.5 font-medium">{u.email}</td>
                      <td className="px-4 py-2.5"><Badge tone="accent">{u.role}</Badge></td>
                      <td className="px-4 py-2.5">
                        <Badge tone={u.status === 'active' ? 'success' : 'danger'}>{u.status}</Badge>
                      </td>
                      <td className="px-4 py-2.5">{u.mfa_enabled ? 'On' : 'Off'}</td>
                      <td className="px-4 py-2.5">{u.ai_enabled ? 'Enabled' : '—'}</td>
                      <td className="px-4 py-2.5 text-muted">{relativeTime(u.created_at)}</td>
                      <td className="px-4 py-2.5 text-muted">{u.last_login_at ? relativeTime(u.last_login_at) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'security' && (
        <div className="panel-solid rounded-2xl p-5">
          <div className="eyebrow flex items-center gap-2"><ShieldAlert size={12} /> Security events</div>
          {events === null ? (
            <Spinner label="Loading events…" />
          ) : events.length === 0 ? (
            <EmptyState title="No security events" description="Failed logins, denied access and rate-limit triggers will surface here." />
          ) : (
            <div className="mt-3 divide-y divide-[color:var(--color-beige)]">
              {events.map((e) => (
                <div key={e.event_id} className="py-2.5 flex flex-wrap items-center justify-between gap-2 text-[13px]">
                  <div className="flex items-center gap-2.5">
                    <Badge tone={e.result === 'denied' || e.result === 'failure' ? 'danger' : 'neutral'}>
                      {e.result}
                    </Badge>
                    <span className="font-medium">{eventLabel(e.event_type)}</span>
                    <span className="text-faint">{e.actor_role || 'anonymous'}</span>
                  </div>
                  <div className="flex items-center gap-3 text-faint">
                    <code className="text-[11px]">{e.request_id}</code>
                    {relativeTime(e.timestamp)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'activity' && (
        <div className="panel-solid rounded-2xl p-5">
          <div className="eyebrow flex items-center gap-2"><Activity size={12} /> Recent system activity</div>
          {activity === null ? (
            <Spinner label="Loading activity…" />
          ) : (
            <div className="mt-3 divide-y divide-[color:var(--color-beige)]">
              {activity.map((e) => (
                <div key={e.event_id} className="py-2.5 flex flex-wrap items-center justify-between gap-2 text-[13px]">
                  <div className="flex items-center gap-2.5">
                    <span className="font-medium">{eventLabel(e.event_type)}</span>
                    <span className="text-faint">{e.actor_role || 'system'}</span>
                    {Object.entries(e.metadata).slice(0, 2).map(([k, v]) => (
                      <span key={k} className="text-faint text-[12px]">{k}: {String(v)}</span>
                    ))}
                  </div>
                  <span className="text-faint">{relativeTime(e.timestamp)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'shares' && shares && (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-4 max-w-lg">
            {(['active', 'expired', 'revoked'] as const).map((k) => (
              <div key={k} className="panel-solid rounded-2xl p-4">
                <div className="eyebrow">{k}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums">{shares.summary[k] ?? 0}</div>
              </div>
            ))}
          </div>
          <div className="panel-solid rounded-2xl overflow-hidden">
            <div className="overflow-x-auto scrollbar-thin">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left border-b hairline bg-ivory-deep/50">
                    <th className="px-4 py-2.5 font-medium text-muted">Share</th>
                    <th className="px-4 py-2.5 font-medium text-muted">Mode</th>
                    <th className="px-4 py-2.5 font-medium text-muted">Permission</th>
                    <th className="px-4 py-2.5 font-medium text-muted">Status</th>
                    <th className="px-4 py-2.5 font-medium text-muted">Accesses</th>
                    <th className="px-4 py-2.5 font-medium text-muted">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {shares.shares.map((s) => (
                    <tr key={s.share_id} className="border-b border-[color:var(--color-beige)] last:border-0">
                      <td className="px-4 py-2.5 font-mono text-[12px]">{s.share_id.slice(0, 12)}…</td>
                      <td className="px-4 py-2.5">{s.mode}</td>
                      <td className="px-4 py-2.5">{s.permission}</td>
                      <td className="px-4 py-2.5">
                        <Badge tone={s.status === 'active' ? 'success' : s.status === 'expired' ? 'warning' : 'danger'}>
                          {s.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 tabular-nums">{s.access_count}</td>
                      <td className="px-4 py-2.5 text-muted">{relativeTime(s.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {tab === 'rag' && rag && (
        <div className="grid lg:grid-cols-2 gap-4">
          <div className="panel-solid rounded-2xl p-5">
            <div className="eyebrow flex items-center gap-2"><Database size={12} /> Personal RAG statistics</div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <StatCard label="Instances" value={rag.total_instances} />
              <StatCard label="Enabled" value={rag.enabled} />
              <StatCard label="Disabled" value={rag.disabled} />
              <StatCard label="Chunks" value={rag.total_chunks} />
            </div>
            <p className="text-xs text-muted mt-4">
              Isolation model: <code>{rag.isolation_model}</code> — no global index exists, so
              cross-user retrieval is structurally impossible.
            </p>
          </div>
          {analytics && (
            <div className="panel-solid rounded-2xl p-5">
              <div className="eyebrow flex items-center gap-2"><FileStack size={12} /> Storage breakdown</div>
              <div className="mt-3 space-y-2 text-[13px]">
                {[
                  ['Total documents', String(analytics.documents.total)],
                  ['Private', String(analytics.documents.private)],
                  ['Public', String(analytics.documents.public)],
                  ['Profile visible', String(analytics.documents.profile_visible)],
                  ['Ciphertext size', formatBytes(analytics.documents.storage_bytes)],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between">
                    <span className="text-muted">{k}</span>
                    <span className="font-semibold tabular-nums">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
