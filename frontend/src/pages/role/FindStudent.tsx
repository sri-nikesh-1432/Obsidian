import { useState } from 'react'
import { Download, GraduationCap, Search, ShieldAlert, UserRoundSearch } from 'lucide-react'
import { api, ApiError, triggerDownload } from '../../lib/api'
import { useAuth } from '../../store/auth'
import type { StudentLookup } from '../../lib/types'
import { formatBytes, formatDateShort } from '../../lib/format'
import { Badge, Button, EmptyState, Field, Input, PageHeader } from '../../components/ui'
import { useToast } from '../../store/toast'

export default function FindStudent() {
  const { user } = useAuth()
  const toast = useToast()
  const [studentId, setStudentId] = useState('')
  const [lookup, setLookup] = useState<StudentLookup | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [busy, setBusy] = useState(false)

  const isRecruiter = user?.role === 'recruiter'

  const search = async (e: React.FormEvent) => {
    e.preventDefault()
    const id = studentId.trim().toUpperCase()
    if (!id) return
    setBusy(true)
    setNotFound(false)
    setLookup(null)
    try {
      const data = await api<StudentLookup>(`/profile/student/${encodeURIComponent(id)}`)
      setLookup(data)
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
        setNotFound(true)
      } else {
        toast.push('error', err instanceof ApiError ? err.message : 'Lookup failed.')
      }
    } finally {
      setBusy(false)
    }
  }

  const openDoc = async (documentId: string, filename: string) => {
    if (!lookup) return
    try {
      const data = await api<{ content_base64: string; mime_type: string }>(
        `/profile/student/${encodeURIComponent(lookup.student.student_id)}/documents/${documentId}/content`,
      )
      triggerDownload(data.content_base64, data.mime_type, filename)
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not open the document.')
    }
  }

  return (
    <div className="fade-up max-w-4xl mx-auto">
      <PageHeader
        title="Find a student"
        subtitle={
          isRecruiter
            ? 'Enter a student ID to view the profile content they have deliberately exposed.'
            : 'Enter the student’s exact ID. OBSIDIAN has no directory — lookup requires the ID itself.'
        }
      />

      <form onSubmit={search} className="glass rounded-2xl p-5 sm:p-6">
        <Field label="Student ID" htmlFor="sid" hint="Format: OBS-XXXX-XXXXXX — copied directly from the student.">
          <div className="flex gap-2">
            <Input
              id="sid"
              value={studentId}
              onChange={(e) => setStudentId(e.target.value.toUpperCase())}
              placeholder="OBS-4F2K-9QW7ZP"
              className="font-mono tracking-wider"
              maxLength={20}
              autoComplete="off"
            />
            <Button type="submit" variant="primary" loading={busy} disabled={!studentId.trim()}>
              <Search size={15} /> Search
            </Button>
          </div>
        </Field>

        <div className="mt-4 flex items-start gap-2.5 text-[13px] text-muted">
          <ShieldAlert size={14} className="text-warning mt-0.5 shrink-0" />
          <span>
            Failed lookups return a generic response and are rate-limited and audited. You
            cannot browse students, see other {isRecruiter ? 'recruiters' : 'faculty'}, or
            enumerate accounts.
          </span>
        </div>
      </form>

      {notFound && (
        <div className="mt-5">
          <EmptyState
            icon={<ShieldAlert size={22} />}
            title="The requested resource is unavailable"
            description="No profile matches that ID, or its owner has set their profile to private. OBSIDIAN returns the same response in both cases."
            action={
              <Button variant="soft" onClick={() => { setNotFound(false); setStudentId('') }}>
                Clear
              </Button>
            }
          />
        </div>
      )}

      {lookup && (
        <div className="mt-5 fade-up">
          {/* profile card */}
          <div className="glass rounded-2xl p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="w-14 h-14 rounded-2xl bg-cognac/12 text-cognac-deep ring-1 ring-cognac/20 flex items-center justify-center text-lg font-semibold">
                  {(lookup.student.full_name || '?').slice(0, 1).toUpperCase()}
                </div>
                <div>
                  <h2 className="text-xl font-semibold text-editorial">
                    {lookup.student.full_name || 'Student'}
                  </h2>
                  <div className="text-sm text-muted flex flex-wrap items-center gap-x-3 gap-y-1 mt-1">
                    <span className="font-mono">{lookup.student.student_id}</span>
                    {lookup.student.course && <span>{lookup.student.course}</span>}
                    {lookup.student.institution && <span>{lookup.student.institution}</span>}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {lookup.student.cgpa && <Badge tone="accent">CGPA {lookup.student.cgpa}</Badge>}
                {lookup.student.education_level && <Badge tone="neutral">{lookup.student.education_level}</Badge>}
                {lookup.student.graduation_year && <Badge tone="info">Class of {lookup.student.graduation_year}</Badge>}
              </div>
            </div>

            {lookup.student.bio && (
              <p className="mt-4 text-sm text-graphite leading-relaxed max-w-2xl">
                {lookup.student.bio}
              </p>
            )}

            {(lookup.student.skills?.length > 0 || lookup.student.achievements?.length > 0) && (
              <div className="mt-4 grid sm:grid-cols-2 gap-4">
                {lookup.student.skills?.length > 0 && (
                  <div>
                    <div className="eyebrow">Skills</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {lookup.student.skills.map((s) => (
                        <span key={s} className="rounded-full bg-white/80 border hairline px-2.5 py-1 text-[12.5px]">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {lookup.student.achievements?.length > 0 && (
                  <div>
                    <div className="eyebrow">Achievements</div>
                    <ul className="mt-2 space-y-1 text-[13px] text-graphite">
                      {lookup.student.achievements.map((a) => (
                        <li key={a} className="flex gap-2">
                          <span className="text-cognac">·</span> {a}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <div className="mt-5 pt-4 border-t hairline grid sm:grid-cols-3 gap-3 text-[13px]">
              {[
                ['Department', lookup.student.department || '—'],
                ['Year', lookup.student.year || '—'],
                ['Phone', lookup.student.phone || 'Not shared'],
              ].map(([k, v]) => (
                <div key={k}>
                  <div className="text-faint text-[11px] uppercase tracking-wider">{k}</div>
                  <div className="mt-0.5 font-medium">{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* documents */}
          <div className="panel-solid rounded-2xl p-5 mt-4">
            <div className="eyebrow flex items-center gap-2">
              <GraduationCap size={12} /> Profile-visible documents
            </div>
            {lookup.documents.length === 0 ? (
              <p className="text-sm text-muted mt-3">
                This student has not exposed any documents on their profile.
              </p>
            ) : (
              <div className="mt-3 grid sm:grid-cols-2 gap-3">
                {lookup.documents.map((d) => (
                  <div
                    key={d.document_id}
                    className="rounded-xl border hairline bg-white/70 px-4 py-3 flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">{d.filename}</div>
                      <div className="text-xs text-faint">
                        {formatBytes(d.size_bytes)} · {formatDateShort(d.created_at)}
                      </div>
                    </div>
                    <Button variant="soft" size="sm" onClick={() => openDoc(d.document_id, d.filename)}>
                      <Download size={13} /> Open
                    </Button>
                  </div>
                ))}
              </div>
            )}
            <p className="text-xs text-faint mt-4 flex items-center gap-1.5">
              <UserRoundSearch size={12} />
              Only documents explicitly marked profile-visible can be opened here — private vault
              content is never reachable through this route.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
