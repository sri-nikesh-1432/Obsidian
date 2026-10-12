import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, BarChart3, Brain, Database, FileStack, Link2,
  Send, Server, ShieldAlert, ShieldCheck, TrendingUp, Users, Wallet,
} from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import type {
  AdminInsights, AdminIntelligenceAnswer,
} from '../../lib/types'
import { eventLabel, formatBytes, relativeTime } from '../../lib/format'
import {
  Badge, Button, EmptyState, PageHeader, Spinner, StatCard, Input,
} from '../../components/ui'
import {
  BarChart, CHART_COLORS, ChartCard, ChartLegend, DonutChart, seriesFrom,
} from '../../components/Charts'

type Tab =
  | 'overview' | 'charts' | 'intelligence' | 'payments'
  | 'users' | 'security' | 'activity' | 'shares' | 'rag'

const TABS: { id: Tab; label: string; icon: typeof Users }[] = [
  { id: 'overview', label: 'Overview', icon: BarChart3 },
  { id: 'charts', label: 'Analytics', icon: TrendingUp },
  { id: 'intelligence', label: 'Intelligence', icon: Brain },
  { id: 'payments', label: 'Payments', icon: Wallet },
  { id: 'users', label: 'Users', icon: Users },
  { id: 'security', label: 'Security', icon: ShieldAlert },
  { id: 'activity', label: 'System activity', icon: Activity },
  { id: 'shares', label: 'Share links', icon: Link2 },
  { id: 'rag', label: 'Storage & AI', icon: Database },
]

interface AdminUser {
  user_id: string
  email: string
  role: string
  status: string
  mfa_enabled: boolean
  ai_enabled: boolean
  verification_status: string
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

const inr = (n: number) => `₹${Number(n || 0).toLocaleString('en-IN')}`
const shortDay = (iso: string) => iso.slice(5)

function paymentSeries(p: AdminInsights['payments']) {
  return [
    { label: 'paid', value: p.paid, color: CHART_COLORS[1] },
    { label: 'pending', value: p.pending, color: CHART_COLORS[3] },
    { label: 'failed', value: p.failed, color: CHART_COLORS[6] },
  ]
}

function shareSeries(s: AdminInsights['shares']) {
  return [
    { label: 'active', value: s.active, color: CHART_COLORS[1] },
    { label: 'expired', value: s.expired, color: CHART_COLORS[3] },
    { label: 'revoked', value: s.revoked, color: CHART_COLORS[6] },
  ]
}

export default function Admin() {
  const [tab, setTab] = useState<Tab>('overview')
  const [insights, setInsights] = useState<AdminInsights | null>(null)
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [events, setEvents] = useState<AdminEvent[] | null>(null)
  const [activity, setActivity] = useState<AdminEvent[] | null>(null)
  const [shares, setShares] = useState<{ summary: Record<string, number>; shares: AdminShare[] } | null>(null)
  const [rag, setRag] = useState<RagStats | null>(null)
  const [loading, setLoading] = useState(true)

  const loadAll = useCallback(async () => {
    setLoading(true)
    const [ins, u, se, ac, sh, rg] = await Promise.allSettled([
      api<AdminInsights>('/admin/insights'),
      api<{ users: AdminUser[] }>('/admin/users?limit=200'),
      api<{ events: AdminEvent[] }>('/admin/security-events?limit=60'),
      api<{ events: AdminEvent[] }>('/admin/activity'),
      api<{ summary: Record<string, number>; shares: AdminShare[] }>('/admin/shares'),
      api<RagStats>('/admin/rag'),
    ])
    if (ins.status === 'fulfilled') setInsights(ins.value)
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

  if (loading && !insights) return <Spinner label="Loading analytics…" />

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

      {tab === 'overview' && insights && <Overview insights={insights} />}
      {tab === 'charts' && insights && <ChartsTab insights={insights} />}
      {tab === 'intelligence' && <IntelligencePanel />}
      {tab === 'payments' && insights && <PaymentsTab insights={insights} />}
      {tab === 'users' && (
        <UsersTab users={users} onChanged={(id, status) =>
          setUsers((prev) => prev?.map((u) =>
            u.user_id === id ? { ...u, verification_status: status } : u) ?? prev)} />
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

      {tab === 'rag' && insights && (
        <div className="grid lg:grid-cols-2 gap-4">
          <div className="panel-solid rounded-2xl p-5">
            <div className="eyebrow flex items-center gap-2"><Database size={12} /> Personal AI statistics</div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <StatCard label="Instances" value={rag?.total_instances ?? insights.rag.instances} />
              <StatCard label="Enabled" value={rag?.enabled ?? insights.rag.enabled} />
              <StatCard label="Disabled" value={rag?.disabled ?? Math.max(0, insights.rag.instances - insights.rag.enabled)} />
              <StatCard label="Chunks" value={rag?.total_chunks ?? insights.rag.chunks} />
            </div>
            <p className="text-xs text-muted mt-4">
              Isolation model: <code>{rag?.isolation_model ?? 'per-user partition (RAG#<user_id>)'}</code> — no global
              index exists, so cross-user retrieval is structurally impossible.
            </p>
          </div>
          <div className="panel-solid rounded-2xl p-5">
            <div className="eyebrow flex items-center gap-2"><FileStack size={12} /> Storage breakdown</div>
            <div className="mt-3 space-y-2 text-[13px]">
              {[
                ['Total documents', String(insights.documents.total)],
                ['Private', String(insights.documents.private)],
                ['Public', String(insights.documents.public)],
                ['Profile visible', String(insights.documents.profile_visible)],
                ['AI eligible', String(insights.documents.raggable)],
                ['Ciphertext size', formatBytes(insights.documents.storage_bytes)],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="text-muted">{k}</span>
                  <span className="font-semibold tabular-nums">{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------- overview */

function Overview({ insights }: { insights: AdminInsights }) {
  const roleSeries = seriesFrom(insights.users.by_role)
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatCard label="Total users" value={insights.users.total} icon={<Users size={15} />}
          hint={`${insights.users.new_last_7d} new · 7d`} />
        <StatCard label="Signed in" value={insights.users.logged_in} icon={<Activity size={15} />}
          hint={`${insights.sessions.active} active sessions`} />
        <StatCard label="Documents" value={insights.documents.total} icon={<FileStack size={15} />}
          hint={`${insights.documents.private} private · ${insights.documents.public} public`} />
        <StatCard label="Storage" value={formatBytes(insights.documents.storage_bytes)} icon={<Database size={15} />}
          hint="ciphertext at rest" />
        <StatCard label="Revenue" value={inr(insights.payments.revenue_inr)} icon={<Wallet size={15} />}
          hint={`${insights.payments.paid} paid orders`} />
        <StatCard label="Share links" value={insights.shares.total} icon={<Link2 size={15} />}
          hint={`${insights.shares.active} active`} />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="panel-solid rounded-2xl p-5">
          <div className="eyebrow">Security counters</div>
          <div className="mt-3 space-y-2 text-[13px]">
            {Object.entries(insights.security).map(([k, v]) => (
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
            {Object.entries(insights.health).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-3">
                <span className="text-muted">{k.replace(/_/g, ' ')}</span>
                <span className="font-medium text-right">{v}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge tone="success">MFA: {insights.users.mfa_enabled}/{insights.users.total}</Badge>
            <Badge tone="accent">Personal AI: {insights.users.ai_enabled}</Badge>
            <Badge tone="info">Groups: {insights.groups.total}</Badge>
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <ChartCard title="Users by role">
          <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-center">
            <DonutChart data={roleSeries} centerValue={insights.users.total} centerLabel="ACCOUNTS" />
            <div className="w-full sm:w-40"><ChartLegend data={roleSeries} /></div>
          </div>
        </ChartCard>
        <ChartCard title="Documents by type">
          <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-center">
            <DonutChart data={seriesFrom(insights.documents.by_type)}
              centerValue={insights.documents.total} centerLabel="FILES" />
            <div className="w-full sm:w-40"><ChartLegend data={seriesFrom(insights.documents.by_type)} /></div>
          </div>
        </ChartCard>
        <ChartCard title="Payments">
          <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-center">
            <DonutChart data={paymentSeries(insights.payments)}
              centerValue={inr(insights.payments.revenue_inr)} centerLabel="COLLECTED" />
            <div className="w-full sm:w-40"><ChartLegend data={paymentSeries(insights.payments)} showZero /></div>
          </div>
        </ChartCard>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <TrendCard title="New sign-ups" unit="accounts" color={CHART_COLORS[0]}
          data={insights.series.map((r) => ({ label: shortDay(r.date), value: r.signups }))} />
        <TrendCard title="Uploads" unit="documents" color={CHART_COLORS[1]}
          data={insights.series.map((r) => ({ label: shortDay(r.date), value: r.uploads }))} />
        <TrendCard title="Sign-ins" unit="logins" color={CHART_COLORS[2]}
          data={insights.series.map((r) => ({ label: shortDay(r.date), value: r.logins }))} />
      </div>
    </div>
  )
}

function TrendCard({
  title, data, color, unit,
}: {
  title: string
  data: { label: string; value: number }[]
  color: string
  unit: string
}) {
  const total = data.reduce((s, d) => s + d.value, 0)
  return (
    <ChartCard title={title} action={<span className="text-xs text-muted">last 14 days</span>}>
      <BarChart data={data} color={color} />
      <div className="mt-3 text-xs text-muted">
        <span className="font-semibold text-charcoal tabular-nums">{total}</span> {unit} in the last 14 days
      </div>
    </ChartCard>
  )
}

/* --------------------------------------------------------- analytics tab */

function ChartsTab({ insights }: { insights: AdminInsights }) {
  const roleSeries = seriesFrom(insights.users.by_role)
  const typeSeries = seriesFrom(insights.documents.by_type, 10)
  const shareS = shareSeries(insights.shares)
  const payS = paymentSeries(insights.payments)
  return (
    <div className="space-y-4">
      <div className="grid lg:grid-cols-2 xl:grid-cols-4 gap-4">
        <DonutPanel title="Users by role" data={roleSeries} center={insights.users.total} label="ACCOUNTS" />
        <DonutPanel title="Documents by type" data={typeSeries} center={insights.documents.total} label="FILES" />
        <DonutPanel title="Payments by status" data={payS} center={`${insights.payments.orders_total}`} label="ORDERS" showZero />
        <DonutPanel title="Share links" data={shareS} center={insights.shares.total} label="LINKS" showZero />
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="panel-solid rounded-2xl p-5">
          <div className="eyebrow">Vault overview</div>
          <div className="mt-3">
            <DonutChart size={200}
              data={[
                { label: 'private', value: insights.documents.private, color: CHART_COLORS[0] },
                { label: 'public', value: insights.documents.public, color: CHART_COLORS[1] },
              ]}
              centerValue={formatBytes(insights.documents.storage_bytes)} centerLabel="STORED" />
          </div>
          <div className="mt-4">
            <ChartLegend data={[
              { label: 'Private', value: insights.documents.private, color: CHART_COLORS[0] },
              { label: 'Public', value: insights.documents.public, color: CHART_COLORS[1] },
              { label: 'Profile visible', value: insights.documents.profile_visible, color: CHART_COLORS[3] },
            ]} showZero />
          </div>
        </div>

        <div className="panel-solid rounded-2xl p-5 lg:col-span-2">
          <div className="eyebrow">14-day activity</div>
          <div className="mt-5 space-y-6">
            <div>
              <div className="flex items-center justify-between text-[13px] mb-2">
                <span className="text-graphite font-medium">New sign-ups</span>
                <span className="text-muted tabular-nums">
                  {insights.series.reduce((s, r) => s + r.signups, 0)}
                </span>
              </div>
              <BarChart data={insights.series.map((r) => ({ label: shortDay(r.date), value: r.signups }))}
                color={CHART_COLORS[0]} height={70} />
            </div>
            <div>
              <div className="flex items-center justify-between text-[13px] mb-2">
                <span className="text-graphite font-medium">Uploads</span>
                <span className="text-muted tabular-nums">
                  {insights.series.reduce((s, r) => s + r.uploads, 0)}
                </span>
              </div>
              <BarChart data={insights.series.map((r) => ({ label: shortDay(r.date), value: r.uploads }))}
                color={CHART_COLORS[1]} height={70} />
            </div>
            <div>
              <div className="flex items-center justify-between text-[13px] mb-2">
                <span className="text-graphite font-medium">Sign-ins</span>
                <span className="text-muted tabular-nums">
                  {insights.series.reduce((s, r) => s + r.logins, 0)}
                </span>
              </div>
              <BarChart data={insights.series.map((r) => ({ label: shortDay(r.date), value: r.logins }))}
                color={CHART_COLORS[2]} height={70} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function DonutPanel({
  title, data, center, label, showZero = false,
}: {
  title: string
  data: { label: string; value: number; color: string }[]
  center: string | number
  label: string
  showZero?: boolean
}) {
  const filtered = showZero ? data : data.filter((d) => d.value > 0)
  return (
    <ChartCard title={title}>
      <div className="flex flex-col items-center gap-4">
        <DonutChart data={filtered} centerValue={center} centerLabel={label} size={150} thickness={20} />
        <div className="w-full"><ChartLegend data={data} showZero={showZero} /></div>
      </div>
    </ChartCard>
  )
}

/* --------------------------------------------------------------- payments */

function PaymentsTab({ insights }: { insights: AdminInsights }) {
  const p = insights.payments
  const tierSeries = seriesFrom(p.by_tier).map((s, i) => ({ ...s, label: `Tier ${s.label}`, color: CHART_COLORS[i] }))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatCard label="Orders" value={p.orders_total} icon={<Wallet size={15} />} />
        <StatCard label="Paid" value={p.paid} hint={inr(p.revenue_inr)} />
        <StatCard label="Pending" value={p.pending} hint={inr(p.pending_inr)} />
        <StatCard label="Failed" value={p.failed} />
        <StatCard label="Revenue" value={inr(p.revenue_inr)} />
        <StatCard label="Avg order" value={inr(p.avg_order_inr)} />
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <DonutPanel title="Orders by tier" data={tierSeries} center={p.paid} label="PAID" />
        <div className="panel-solid rounded-2xl p-5 lg:col-span-2">
          <div className="eyebrow">Recent paid orders</div>
          {p.recent.length === 0 ? (
            <EmptyState title="No paid orders yet" description="Completed storage purchases will appear here." />
          ) : (
            <div className="mt-3 overflow-x-auto scrollbar-thin">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left border-b hairline">
                    <th className="py-2 font-medium text-muted">Order</th>
                    <th className="py-2 font-medium text-muted">Customer</th>
                    <th className="py-2 font-medium text-muted">Plan</th>
                    <th className="py-2 font-medium text-muted text-right">Amount</th>
                    <th className="py-2 font-medium text-muted">Paid</th>
                  </tr>
                </thead>
                <tbody>
                  {p.recent.map((o) => (
                    <tr key={o.order_id} className="border-b border-[color:var(--color-beige)] last:border-0">
                      <td className="py-2 font-mono text-[11px]">{o.order_id.slice(0, 14)}…</td>
                      <td className="py-2">{o.email || '—'}</td>
                      <td className="py-2">{o.plan}</td>
                      <td className="py-2 text-right tabular-nums font-medium">{inr(o.amount_inr)}</td>
                      <td className="py-2 text-muted">{o.paid_at ? relativeTime(o.paid_at) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ users */

function UsersTab({
  users, onChanged,
}: {
  users: AdminUser[] | null
  onChanged: (id: string, status: string) => void
}) {
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')

  const setVerification = async (u: AdminUser, status: 'verified' | 'pending') => {
    setBusyId(u.user_id)
    setError('')
    try {
      await api(`/admin/users/${u.user_id}/verification`, { method: 'POST', body: { status } })
      onChanged(u.user_id, status)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not update verification.')
    } finally {
      setBusyId('')
    }
  }

  if (users === null) return <Spinner label="Loading users…" />
  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">{error}</div>
      )}
      <div className="panel-solid rounded-2xl overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left border-b hairline bg-ivory-deep/50">
                <th className="px-4 py-2.5 font-medium text-muted">Email</th>
                <th className="px-4 py-2.5 font-medium text-muted">Role</th>
                <th className="px-4 py-2.5 font-medium text-muted">Status</th>
                <th className="px-4 py-2.5 font-medium text-muted">Verification</th>
                <th className="px-4 py-2.5 font-medium text-muted">MFA</th>
                <th className="px-4 py-2.5 font-medium text-muted">AI</th>
                <th className="px-4 py-2.5 font-medium text-muted">Created</th>
                <th className="px-4 py-2.5 font-medium text-muted">Last sign-in</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const needsApproval = u.role === 'faculty' || u.role === 'recruiter'
                const verified = u.verification_status === 'verified'
                return (
                  <tr key={u.user_id} className="border-b border-[color:var(--color-beige)] last:border-0">
                    <td className="px-4 py-2.5 font-medium">{u.email}</td>
                    <td className="px-4 py-2.5"><Badge tone="accent">{u.role}</Badge></td>
                    <td className="px-4 py-2.5">
                      <Badge tone={u.status === 'active' ? 'success' : 'danger'}>{u.status}</Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      {needsApproval ? (
                        <div className="flex items-center gap-2">
                          <Badge tone={verified ? 'success' : 'warning'} icon={<ShieldCheck size={11} />}>
                            {u.verification_status}
                          </Badge>
                          <Button size="sm" variant={verified ? 'soft' : 'accent'}
                            loading={busyId === u.user_id}
                            onClick={() => void setVerification(u, verified ? 'pending' : 'verified')}>
                            {verified ? 'Withdraw' : 'Approve'}
                          </Button>
                        </div>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">{u.mfa_enabled ? 'On' : 'Off'}</td>
                    <td className="px-4 py-2.5">{u.ai_enabled ? 'Enabled' : '—'}</td>
                    <td className="px-4 py-2.5 text-muted">{relativeTime(u.created_at)}</td>
                    <td className="px-4 py-2.5 text-muted">{u.last_login_at ? relativeTime(u.last_login_at) : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

/* ----------------------------------------------------------- intelligence */

interface ChatTurn {
  role: 'user' | 'assistant'
  text: string
  facts?: string[]
  suggestions?: string[]
}

function IntelligencePanel() {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  const suggestions = useMemo(() => {
    const last = [...turns].reverse().find((t) => t.role === 'assistant')
    return last?.suggestions?.length
      ? last.suggestions
      : [
          'Give me a platform overview',
          'How many users signed in today?',
          'What are the payments and revenue?',
          'How much storage is used?',
        ]
  }, [turns])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, busy])

  const ask = async (question: string) => {
    const q = question.trim()
    if (!q || busy) return
    setError('')
    setTurns((t) => [...t, { role: 'user', text: q }])
    setInput('')
    setBusy(true)
    try {
      const history = turns.slice(-8).map((t) => ({ role: t.role, content: t.text }))
      const ans = await api<AdminIntelligenceAnswer>('/admin/intelligence', {
        method: 'POST',
        body: { question: q, history },
      })
      setTurns((t) => [...t, {
        role: 'assistant', text: ans.answer, facts: ans.facts, suggestions: ans.suggestions,
      }])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The assistant is unavailable right now.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid lg:grid-cols-[1fr_280px] gap-4">
      <div className="panel-solid rounded-2xl flex flex-col h-[62vh] min-h-[420px]">
        <div className="flex items-center gap-2.5 border-b hairline px-5 py-3.5">
          <span className="w-8 h-8 rounded-xl bg-cognac/10 text-cognac-deep flex items-center justify-center">
            <Brain size={16} />
          </span>
          <div>
            <div className="text-sm font-semibold">OBSIDIAN Intelligence — Administration</div>
            <div className="text-[11px] text-muted">Grounded in live platform metrics · read-only</div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-4 space-y-4">
          {turns.length === 0 && (
            <div className="text-sm text-muted leading-relaxed">
              Ask about users, sign-ins, uploads, storage, shares, groups, security or payments.
              I answer only from the platform's aggregate analytics — I can never read document
              contents or change anything.
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={t.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-[13.5px] whitespace-pre-wrap leading-relaxed ${
                t.role === 'user'
                  ? 'bg-charcoal text-ivory'
                  : 'glass border border-white/70 text-graphite'
              }`}>
                {t.text}
                {t.facts && t.facts.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {t.facts.map((f, j) => (
                      <span key={j} className="rounded-full border border-cognac/25 bg-cognac/8 px-2.5 py-0.5 text-[11px] text-cognac-deep">
                        {f}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex justify-start">
              <div className="glass rounded-2xl px-4 py-3"><span className="spinner" /></div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {error && (
          <div className="mx-5 mb-2 rounded-xl border border-danger/25 bg-danger/6 px-4 py-2.5 text-sm text-danger">
            {error}
          </div>
        )}

        <form
          onSubmit={(e) => { e.preventDefault(); void ask(input) }}
          className="border-t hairline px-4 py-3 flex items-center gap-2"
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about the platform…"
            aria-label="Question"
          />
          <Button type="submit" variant="accent" loading={busy} disabled={!input.trim()}>
            <Send size={14} />
          </Button>
        </form>
      </div>

      <div className="space-y-3">
        <div className="panel-solid rounded-2xl p-4">
          <div className="eyebrow">Suggested</div>
          <div className="mt-3 space-y-1.5">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => void ask(s)}
                disabled={busy}
                className="w-full text-left rounded-xl border border-beige bg-white/70 px-3 py-2 text-[13px] text-graphite hover:border-cognac/50 hover:bg-cognac/5 transition-colors focus-ring disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div className="panel-solid rounded-2xl p-4 text-[12px] text-muted leading-relaxed">
          <div className="eyebrow mb-2 flex items-center gap-1.5"><ShieldCheck size={12} /> Privacy</div>
          This assistant reads only counts and totals. It has no access to document plaintext,
          encryption keys or any user's private information.
        </div>
      </div>
    </div>
  )
}
