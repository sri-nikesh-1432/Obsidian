import { useCallback, useEffect, useState } from 'react'
import { Link2, Mail, Timer, Trash2 } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import type { Share } from '../../lib/types'
import { expiryLabel, formatDate } from '../../lib/format'
import { Badge, Button, EmptyState, PageHeader, Spinner } from '../../components/ui'
import { useToast } from '../../store/toast'

type Tab = 'active' | 'expired' | 'revoked' | 'all'

export default function Links() {
  const toast = useToast()
  const [shares, setShares] = useState<Share[] | null>(null)
  const [summary, setSummary] = useState<Record<string, number>>({})
  const [tab, setTab] = useState<Tab>('active')
  const [busyId, setBusyId] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await api<{ shares: Share[]; summary: Record<string, number> }>('/shares')
      setShares(data.shares)
      setSummary(data.summary)
    } catch {
      setShares([])
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const revoke = async (shareId: string) => {
    setBusyId(shareId)
    try {
      await api(`/shares/${shareId}`, { method: 'DELETE' })
      toast.push('success', 'Link revoked — access ends immediately.')
      void load()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Revoke failed.')
    } finally {
      setBusyId('')
    }
  }

  if (shares === null) return <Spinner label="Loading links…" />

  const filtered = tab === 'all' ? shares : shares.filter((s) => s.status === tab)

  return (
    <div className="fade-up">
      <PageHeader
        title="Shared links"
        subtitle="Every link is a 256-bit token — only its hash is stored. Revocation is immediate."
      />

      <div className="grid grid-cols-3 gap-4 max-w-lg">
        {(['active', 'expired', 'revoked'] as const).map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`panel-solid rounded-2xl p-4 text-left transition-all focus-ring ${
              tab === k ? 'ring-2 ring-cognac/40 border-cognac/40' : 'hover:shadow-[var(--shadow-lift)]'
            }`}
          >
            <div className="eyebrow">{k}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{summary[k] ?? 0}</div>
          </button>
        ))}
      </div>

      <div className="flex gap-1.5 mt-6 mb-3 flex-wrap">
        {(['active', 'expired', 'revoked', 'all'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-full border px-3.5 py-1.5 text-[13px] capitalize transition-all focus-ring ${
              tab === t
                ? 'border-cognac/70 bg-cognac/8 text-cognac-deep'
                : 'border-beige bg-white/70 text-graphite hover:border-faint/60'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<Link2 size={22} />}
          title={tab === 'active' ? 'No active links' : `No ${tab} links`}
          description="Create a share link from any document in your vault. You can set an expiry and revoke it at any time."
        />
      ) : (
        <div className="panel-solid rounded-2xl divide-y divide-[color:var(--color-beige)] overflow-hidden">
          {filtered.map((s) => (
            <div key={s.share_id} className="px-5 py-4 flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-medium flex items-center gap-2">
                  {s.mode === 'link' ? <Link2 size={13} className="text-cognac" /> : <Mail size={13} className="text-cognac" />}
                  <span className="truncate">{s.filename}</span>
                </div>
                <div className="text-xs text-faint mt-0.5">
                  {s.mode === 'link' ? 'Anyone with link' : `Shared with ${s.grantee_email}`} · {s.permission} ·
                  created {formatDate(s.created_at)} · {s.access_count} accesses
                  {s.last_accessed_at && ` · last ${expiryLabel(s.last_accessed_at)}`}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {s.expires_at && s.status !== 'revoked' && (
                  <Badge tone={s.status === 'expired' ? 'warning' : 'neutral'} icon={<Timer size={11} />}>
                    {expiryLabel(s.expires_at)}
                  </Badge>
                )}
                <Badge tone={s.status === 'active' ? 'success' : s.status === 'expired' ? 'warning' : 'danger'}>
                  {s.status}
                </Badge>
                {s.status === 'active' && (
                  <Button
                    variant="danger"
                    size="sm"
                    loading={busyId === s.share_id}
                    onClick={() => revoke(s.share_id)}
                  >
                    <Trash2 size={13} /> Revoke
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <p className="text-xs text-faint mt-4">
        Raw tokens are never stored or logged — links are shown once at creation. Share access
        itself is audited with a correlation ID.
      </p>
    </div>
  )
}
