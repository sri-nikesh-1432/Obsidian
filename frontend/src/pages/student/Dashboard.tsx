import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Activity, ArrowUpRight, FileLock2, FolderUp, Link2, ShieldCheck, Sparkles,
  Clock3,
} from 'lucide-react'
import { api } from '../../lib/api'
import { useAuth } from '../../store/auth'
import type { ActivityEvent, DocumentMeta, IntelligenceStatus, Share } from '../../lib/types'
import { eventLabel, formatBytes, relativeTime } from '../../lib/format'
import { Badge, Button, EmptyState, PageHeader, Spinner, StatCard } from '../../components/ui'
import UploadDialog from '../../components/UploadDialog'

export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [docs, setDocs] = useState<DocumentMeta[] | null>(null)
  const [shares, setShares] = useState<Share[] | null>(null)
  const [events, setEvents] = useState<ActivityEvent[] | null>(null)
  const [ai, setAi] = useState<IntelligenceStatus | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)

  const load = useCallback(async () => {
    const [d, s, e] = await Promise.allSettled([
      api<{ documents: DocumentMeta[]; total_bytes: number }>('/documents?limit=6'),
      api<{ shares: Share[]; summary: Record<string, number> }>('/shares'),
      api<{ events: ActivityEvent[] }>('/activity?limit=6'),
    ])
    if (d.status === 'fulfilled') setDocs(d.value.documents)
    if (s.status === 'fulfilled') setShares(s.value.shares)
    if (e.status === 'fulfilled') setEvents(e.value.events)
    if (user?.ai_enabled) {
      const st = await api<IntelligenceStatus>('/intelligence/status').catch(() => null)
      setAi(st)
    }
  }, [user?.ai_enabled])

  useEffect(() => {
    void load()
  }, [load])

  const totalBytes = docs?.reduce((sum, d) => sum + d.size_bytes, 0) ?? 0
  const activeShares = shares?.filter((s) => s.status === 'active') ?? []
  const expiringSoon = activeShares.filter((s) => {
    if (!s.expires_at) return false
    const diff = new Date(s.expires_at).getTime() - Date.now()
    return diff < 48 * 3600 * 1000
  })

  const p = user?.profile
  const completionFields = [
    p?.full_name, p?.institution, p?.course, p?.education_level, p?.bio,
    (p?.skills?.length ? 'y' : ''), p?.cgpa, p?.graduation_year,
  ]
  const filled = completionFields.filter(Boolean).length
  const completion = Math.round((filled / completionFields.length) * 100)

  const name = p?.full_name || 'there'
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'

  if (docs === null) return <Spinner label="Loading your vault…" />

  return (
    <div className="fade-up">
      <PageHeader
        title={`${greeting}, ${name.split(' ')[0]}`}
        subtitle="Everything below reflects server-side state — permissions, expiry and encryption included."
        actions={
          <Button variant="accent" onClick={() => setUploadOpen(true)}>
            <FolderUp size={15} /> Upload document
          </Button>
        }
      />

      {docs.length === 0 ? (
        <EmptyState
          icon={<FileLock2 size={22} />}
          title="Your vault is empty"
          description="Upload your first document and OBSIDIAN will encrypt it with AES-256-GCM before storing it — nothing readable ever touches storage."
          action={
            <Button variant="accent" onClick={() => setUploadOpen(true)}>
              Upload your first document
            </Button>
          }
        />
      ) : (
        <>
          {/* bento stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="Documents" value={docs.length} icon={<FileLock2 size={15} />} hint="encrypted at rest" />
            <StatCard label="Storage used" value={formatBytes(totalBytes)} icon={<FolderUp size={15} />} hint="ciphertext size" />
            <StatCard
              label="Active shares"
              value={activeShares.length}
              icon={<Link2 size={15} />}
              hint={`${shares?.filter((s) => s.status === 'revoked').length ?? 0} revoked · ${shares?.filter((s) => s.status === 'expired').length ?? 0} expired`}
            />
            <StatCard
              label="Expiring soon"
              value={expiringSoon.length}
              icon={<Clock3 size={15} />}
              hint="within 48 hours"
            />
          </div>

          <div className="grid lg:grid-cols-3 gap-4 mt-4">
            {/* recent documents */}
            <div className="lg:col-span-2 panel-solid rounded-2xl p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-[15px] font-semibold">Recent documents</h2>
                <Link to="/app/vault" className="text-[13px] text-cognac-deep hover:underline flex items-center gap-1">
                  Open vault <ArrowUpRight size={13} />
                </Link>
              </div>
              <div className="mt-3 divide-y divide-[color:var(--color-beige)]">
                {docs.slice(0, 5).map((d) => (
                  <button
                    key={d.document_id}
                    onClick={() => navigate(`/app/vault/${d.document_id}`)}
                    className="w-full flex items-center justify-between gap-3 py-2.5 text-left group focus-ring rounded-lg"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate group-hover:text-cognac-deep transition-colors">
                        {d.filename}
                      </div>
                      <div className="text-xs text-faint">
                        {formatBytes(d.size_bytes)} · {relativeTime(d.created_at)}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {d.visibility === 'private' ? (
                        <Badge tone="neutral">Private</Badge>
                      ) : (
                        <Badge tone="info">Public</Badge>
                      )}
                      {d.active_share_count > 0 && <Badge tone="success">{d.active_share_count} links</Badge>}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* side column */}
            <div className="space-y-4">
              {user?.ai_enabled && (
                <Link
                  to="/app/intelligence"
                  className="glass rounded-2xl p-5 block hover:shadow-[var(--shadow-lift)] transition-shadow"
                >
                  <div className="flex items-center justify-between">
                    <div className="w-9 h-9 rounded-xl bg-cognac/10 flex items-center justify-center text-cognac">
                      <Sparkles size={16} />
                    </div>
                    <ArrowUpRight size={15} className="text-faint" />
                  </div>
                  <div className="mt-3 text-sm font-semibold">OBSIDIAN Intelligence</div>
                  <p className="text-xs text-muted mt-1">
                    {ai?.chunk_count ?? 0} chunks across {ai?.document_count ?? 0} documents in
                    your private knowledge base.
                  </p>
                </Link>
              )}

              <div className="panel-solid rounded-2xl p-5">
                <div className="flex items-center justify-between">
                  <h3 className="text-[15px] font-semibold">Profile completion</h3>
                  <span className="text-sm text-cognac-deep font-semibold">{completion}%</span>
                </div>
                <div className="mt-3 h-1.5 rounded-full bg-beige overflow-hidden">
                  <div
                    className="h-full rounded-full bg-cognac transition-all"
                    style={{ width: `${completion}%` }}
                  />
                </div>
                <p className="text-xs text-muted mt-3">
                  {completion < 100
                    ? 'Add your bio, skills and CGPA so permitted viewers see a complete picture.'
                    : 'Your profile is complete.'}
                </p>
                <Link to="/app/profile" className="text-[13px] text-cognac-deep hover:underline inline-block mt-2">
                  Edit profile
                </Link>
              </div>

              <div className="panel-solid rounded-2xl p-5">
                <div className="flex items-center gap-2.5">
                  <ShieldCheck size={16} className="text-success" />
                  <h3 className="text-[15px] font-semibold">Security status</h3>
                </div>
                <ul className="mt-3 space-y-2 text-[13px] text-graphite">
                  <li className="flex items-center justify-between">
                    Email MFA <Badge tone="success">Enabled</Badge>
                  </li>
                  <li className="flex items-center justify-between">
                    Document encryption <Badge tone="success">AES-256-GCM</Badge>
                  </li>
                  <li className="flex items-center justify-between">
                    Profile visibility{' '}
                    <Badge tone={p?.profile_visibility === 'public' ? 'info' : 'neutral'}>
                      {p?.profile_visibility === 'public' ? 'Visible' : 'Private'}
                    </Badge>
                  </li>
                  <li className="flex items-center justify-between">
                    Student ID <Badge tone="accent">{p?.student_id ? 'Issued' : 'Pending'}</Badge>
                  </li>
                </ul>
                <Link to="/app/security" className="text-[13px] text-cognac-deep hover:underline inline-block mt-3">
                  Open security center
                </Link>
              </div>
            </div>
          </div>

          {/* activity strip */}
          <div className="panel-solid rounded-2xl p-5 mt-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-semibold flex items-center gap-2">
                <Activity size={15} className="text-cognac" /> Recent activity
              </h2>
              <Link to="/app/activity" className="text-[13px] text-cognac-deep hover:underline">
                View all
              </Link>
            </div>
            <div className="mt-3 space-y-2">
              {(events ?? []).slice(0, 5).map((e) => (
                <div key={e.event_id} className="flex items-center justify-between text-[13px]">
                  <span className="text-graphite">{eventLabel(e.event_type)}</span>
                  <span className="text-faint">{relativeTime(e.timestamp)}</span>
                </div>
              ))}
              {(events ?? []).length === 0 && (
                <p className="text-sm text-muted">No activity recorded yet.</p>
              )}
            </div>
          </div>
        </>
      )}

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={() => {
          void load()
          navigate('/app/vault')
        }}
        aiEnabled={!!user?.ai_enabled}
      />
    </div>
  )
}
