import { useCallback, useEffect, useState } from 'react'
import {
  Brain, KeyRound, Laptop, ScanEye, Server, ShieldCheck, Sparkles,
} from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { useAuth } from '../../store/auth'
import type { ActivityEvent, IntelligenceStatus, Share } from '../../lib/types'
import { eventLabel, formatDate, relativeTime } from '../../lib/format'
import {
  Badge, Button, ConfirmDialog, EmptyState, PageHeader, Spinner, StatCard, Toggle,
} from '../../components/ui'
import { useToast } from '../../store/toast'

interface SessionRow {
  session_ref: string
  created_at: string
  last_seen_at: string
  ip_hash: string
  current: boolean
}

export default function SecurityCenter() {
  const { user, refresh } = useAuth()
  const toast = useToast()
  const [sessions, setSessions] = useState<SessionRow[] | null>(null)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [shares, setShares] = useState<Share[]>([])
  const [ai, setAi] = useState<IntelligenceStatus | null>(null)
  const [confirmAiOff, setConfirmAiOff] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const [s, e, sh] = await Promise.allSettled([
      api<{ sessions: SessionRow[] }>('/auth/sessions'),
      api<{ events: ActivityEvent[] }>('/security/events'),
      api<{ shares: Share[] }>('/shares'),
    ])
    if (s.status === 'fulfilled') setSessions(s.value.sessions)
    if (e.status === 'fulfilled') setEvents(e.value.events)
    if (sh.status === 'fulfilled') setShares(sh.value.shares)
    if (user?.ai_enabled) {
      const st = await api<IntelligenceStatus>('/intelligence/status').catch(() => null)
      setAi(st)
    }
  }, [user?.ai_enabled])

  useEffect(() => {
    void load()
  }, [load])

  const revokeOthers = async () => {
    setBusy(true)
    try {
      const data = await api<{ revoked: number }>('/auth/logout-others', { method: 'POST' })
      toast.push('success', `${data.revoked} other session(s) revoked.`)
      void load()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not revoke sessions.')
    } finally {
      setBusy(false)
    }
  }

  const setAiConsent = async (value: boolean) => {
    setBusy(true)
    try {
      await api('/intelligence/consent', { method: 'POST', body: { consent: value } })
      await refresh()
      toast.push(
        'success',
        value ? 'Personal AI enabled.' : 'Personal AI disabled — all vectors deleted.',
      )
      void load()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not update consent.')
    } finally {
      setBusy(false)
      setConfirmAiOff(false)
    }
  }

  if (!user) return <Spinner />

  const activeShares = shares.filter((s) => s.status === 'active')
  const recentFailures = events.filter((e) =>
    ['login_failure', 'otp_failure', 'authorization_denied', 'rate_limit_triggered'].includes(e.event_type),
  )

  return (
    <div className="fade-up">
      <PageHeader
        title="Security center"
        subtitle="Understand your account's security posture — without exposing any secret material."
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Email MFA" value="On" icon={<KeyRound size={15} />} hint="required at sign-in" />
        <StatCard label="Active sessions" value={sessions?.length ?? '—'} icon={<Laptop size={15} />} hint="server-side, revocable" />
        <StatCard label="Active links" value={activeShares.length} icon={<ScanEye size={15} />} hint="expirable & revocable" />
        <StatCard
          label="Recent denials"
          value={recentFailures.length}
          icon={<ShieldCheck size={15} />}
          hint="last 24h events"
        />
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mt-4">
        {/* sessions */}
        <div className="panel-solid rounded-2xl p-5">
          <div className="flex items-center justify-between">
            <div className="eyebrow flex items-center gap-2"><Laptop size={12} /> Active sessions</div>
            <Button variant="soft" size="sm" loading={busy} onClick={revokeOthers}>
              Sign out others
            </Button>
          </div>
          {sessions === null ? (
            <Spinner label="Loading sessions…" />
          ) : (
            <div className="mt-3 space-y-2">
              {sessions.map((s) => (
                <div key={s.session_ref} className="rounded-xl border hairline bg-white/70 px-3.5 py-2.5 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-[13px] font-medium flex items-center gap-2">
                      Session {s.session_ref}
                      {s.current && <Badge tone="success">current</Badge>}
                    </div>
                    <div className="text-xs text-faint">
                      started {formatDate(s.created_at)} · IP {s.ip_hash || 'n/a'}
                    </div>
                  </div>
                  <span className="text-xs text-muted">{relativeTime(s.last_seen_at)}</span>
                </div>
              ))}
              {sessions.length === 1 && (
                <p className="text-xs text-faint">Only this device is signed in.</p>
              )}
            </div>
          )}
        </div>

        {/* encryption & AI */}
        <div className="space-y-4">
          <div className="panel-solid rounded-2xl p-5">
            <div className="eyebrow flex items-center gap-2"><Server size={12} /> Storage encryption</div>
            <div className="mt-3 space-y-2.5 text-[13px]">
              {[
                ['Algorithm', 'AES-256-GCM (authenticated)'],
                ['Key wrapping', 'AWS KMS envelope encryption'],
                ['Integrity', 'SHA-256 + GCM tag verification'],
                ['Storage', 'Private S3 bucket (SSE-KMS)'],
                ['Key exposure', 'Never returned to clients'],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-3">
                  <span className="text-muted">{k}</span>
                  <span className="font-medium text-right">{v}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel-solid rounded-2xl p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-2.5">
                <Sparkles size={15} className="text-cognac mt-0.5" />
                <div>
                  <div className="text-sm font-semibold flex items-center gap-2">
                    Personal AI
                    <Badge tone={user.ai_enabled ? 'success' : 'neutral'}>
                      {user.ai_enabled ? 'Enabled' : 'Off'}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted mt-1 max-w-sm">
                    {user.ai_enabled
                      ? `Isolated partition · ${ai?.chunk_count ?? 0} chunks indexed. Query-only: it cannot change anything.`
                      : 'No embeddings exist for your account and no AI interface is shown anywhere.'}
                  </p>
                </div>
              </div>
              <Toggle
                checked={!!user.ai_enabled}
                disabled={busy}
                onChange={(v) => (v ? setAiConsent(true) : setConfirmAiOff(true))}
                label=""
              />
            </div>
          </div>
        </div>
      </div>

      {/* security events */}
      <div className="panel-solid rounded-2xl p-5 mt-4">
        <div className="eyebrow flex items-center gap-2"><ShieldCheck size={12} /> Security events</div>
        {events.length === 0 ? (
          <EmptyState
            icon={<ShieldCheck size={20} />}
            title="No security events"
            description="Failed sign-ins, denied access attempts and rate-limit triggers will appear here."
          />
        ) : (
          <div className="mt-3 divide-y divide-[color:var(--color-beige)]">
            {events.slice(0, 20).map((e) => (
              <div key={e.event_id} className="py-2.5 flex items-center justify-between text-[13px]">
                <span className="text-graphite">{eventLabel(e.event_type)}</span>
                <span className="text-faint">{relativeTime(e.timestamp)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="panel-solid rounded-2xl p-5 mt-4">
        <div className="eyebrow flex items-center gap-2"><Brain size={12} /> Account protections</div>
        <ul className="mt-3 space-y-2.5 text-[13px] text-graphite">
          <li className="flex items-start gap-2"><ShieldCheck size={14} className="text-success mt-0.5" />Passwords hashed with Argon2id — never stored or logged in plaintext.</li>
          <li className="flex items-start gap-2"><ShieldCheck size={14} className="text-success mt-0.5" />One-time codes are single-use, expire in 5 minutes and are attempt-limited.</li>
          <li className="flex items-start gap-2"><ShieldCheck size={14} className="text-success mt-0.5" />Password changes revoke every existing session automatically.</li>
          <li className="flex items-start gap-2"><ShieldCheck size={14} className="text-success mt-0.5" />Sign-in, OTP and share endpoints are rate-limited per source.</li>
        </ul>
      </div>

      <ConfirmDialog
        open={confirmAiOff}
        danger
        title="Disable personal AI?"
        message="Your knowledge base partition is wiped: profile chunks, document chunks and embeddings are deleted. Documents stay in your vault. You can enable it again later."
        confirmLabel="Disable and delete vectors"
        loading={busy}
        onConfirm={() => setAiConsent(false)}
        onCancel={() => setConfirmAiOff(false)}
      />
    </div>
  )
}
