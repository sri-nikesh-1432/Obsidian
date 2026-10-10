import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { BookOpen, Briefcase, Check, Copy, GraduationCap, Lock, ShieldCheck, UserRoundCheck } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { useAuth } from '../../store/auth'
import type { DocumentMeta } from '../../lib/types'
import type { FieldDef, Role } from '../../lib/roleProfile'
import { roleForm } from '../../lib/roleProfile'
import {
  Badge, Button, ChoiceRow, Field, Input, PageHeader, Spinner, Select, Textarea, Toggle,
} from '../../components/ui'
import { useToast } from '../../store/toast'

type ProfileData = Record<string, unknown>

const ROLE_ICONS: Record<Role, ReactNode> = {
  student: <GraduationCap size={16} className="text-cognac" />,
  faculty: <BookOpen size={16} className="text-cognac" />,
  recruiter: <Briefcase size={16} className="text-cognac" />,
  admin: <ShieldCheck size={16} className="text-cognac" />,
}

export default function ProfilePage() {
  const { user, refresh } = useAuth()
  const toast = useToast()

  const role = (user?.role as Role) ?? 'student'
  const form = roleForm(role)

  const [profile, setProfile] = useState<ProfileData | null>(null)
  const [docs, setDocs] = useState<DocumentMeta[]>([])
  const [saving, setSaving] = useState(false)
  const [copied, setCopied] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [visibility, setVisibility] = useState<'public' | 'private'>('public')
  const [showPhone, setShowPhone] = useState(false)

  const load = useCallback(async () => {
    try {
      const p = await api<{ profile: ProfileData }>('/profile')
      setProfile(p.profile)
      const v: Record<string, string> = {}
      for (const f of form.fields) {
        const raw = p.profile[f.name]
        v[f.name] = f.kind === 'list'
          ? ((raw as string[] | undefined) ?? []).join(', ')
          : String(raw ?? '')
      }
      setValues(v)
      setVisibility((p.profile.profile_visibility as 'public' | 'private') ?? 'public')
      setShowPhone(Boolean(p.profile.show_phone))
      if (form.hasVisibility) {
        const d = await api<{ documents: DocumentMeta[] }>('/documents').catch(() => ({ documents: [] }))
        setDocs(d.documents)
      }
    } catch {
      /* handled by UI state */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role])

  useEffect(() => {
    void load()
  }, [load])

  const set = (name: string) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [name]: e.target.value }))

  const save = async () => {
    setSaving(true)
    try {
      const body: Record<string, unknown> = {}
      for (const f of form.fields) {
        const raw = (values[f.name] ?? '').trim()
        if (f.kind === 'list') {
          body[f.name] = raw ? raw.split(',').map((s) => s.trim()).filter(Boolean) : []
        } else {
          body[f.name] = raw
        }
      }
      if (form.hasVisibility) {
        body.profile_visibility = visibility
        body.show_phone = showPhone
      }
      const data = await api<{ profile: ProfileData }>('/profile', { method: 'PATCH', body })
      setProfile(data.profile)
      await refresh()
      toast.push('success', 'Profile updated.')
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not save profile.')
    } finally {
      setSaving(false)
    }
  }

  const toggleDoc = async (doc: DocumentMeta, value: boolean) => {
    try {
      await api(`/documents/${doc.document_id}`, {
        method: 'PATCH',
        body: { profile_visible: value },
      })
      setDocs((prev) =>
        prev.map((d) => (d.document_id === doc.document_id ? { ...d, profile_visible: value } : d)),
      )
      toast.push('success', value ? 'Shown on your profile.' : 'Removed from your profile.')
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Update failed.')
    }
  }

  const copyId = async () => {
    const sid = String(profile?.student_id ?? '')
    if (!sid) return
    try {
      await navigator.clipboard.writeText(sid)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.push('info', sid)
    }
  }

  if (!profile || !user) return <Spinner label="Loading profile…" />

  const studentId = String(profile.student_id ?? '')
  const visibleDocs = docs.filter((d) => d.profile_visible)

  const renderField = (f: FieldDef) => {
    const common = { id: `p-${f.name}`, value: values[f.name] ?? '', onChange: set(f.name) }
    return (
      <Field key={f.name} label={f.label} htmlFor={common.id} hint={f.hint}>
        {f.kind === 'textarea' ? (
          <Textarea {...common} rows={4} maxLength={1200} placeholder={f.placeholder} />
        ) : f.kind === 'select' ? (
          <Select {...common}>
            <option value="">Select…</option>
            {(f.options ?? []).map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </Select>
        ) : (
          <Input {...common} placeholder={f.placeholder} />
        )}
      </Field>
    )
  }

  return (
    <div className="fade-up">
      <PageHeader
        title="Profile"
        subtitle="What others can see — decided entirely by you."
        actions={
          <Button variant="primary" loading={saving} onClick={save}>
            Save changes
          </Button>
        }
      />

      <div className="grid lg:grid-cols-3 gap-4">
        {/* identity column */}
        <div className="space-y-4">
          <div className="glass rounded-2xl p-5">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-cognac/12 text-cognac-deep flex items-center justify-center ring-1 ring-cognac/20 font-semibold">
                {String(profile.full_name || user.email || '·').slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0">
                <div className="font-semibold truncate">{String(profile.full_name || 'Your name')}</div>
                <div className="text-xs text-muted truncate">{user.email}</div>
              </div>
            </div>

            {studentId && (
              <div className="mt-4 rounded-xl border hairline bg-white/70 p-3.5">
                <div className="eyebrow">Student ID</div>
                <div className="mt-1 flex items-center justify-between gap-2">
                  <code className="text-sm font-semibold tracking-wider text-charcoal">{studentId}</code>
                  <button onClick={copyId} className="btn btn-soft btn-sm focus-ring" title="Copy student ID">
                    {copied ? <Check size={13} className="text-success" /> : <Copy size={13} />}
                  </button>
                </div>
                <p className="text-xs text-muted mt-2 flex items-start gap-1.5">
                  <Lock size={11} className="mt-0.5 shrink-0 text-success" />
                  This opaque ID is the only way anyone can find you. There is no directory to browse.
                </p>
              </div>
            )}

            <div className="mt-4 flex flex-wrap gap-2">
              {form.hasVisibility && (
                <Badge tone={visibility === 'public' ? 'success' : 'neutral'} icon={<UserRoundCheck size={11} />}>
                  {visibility === 'public' ? 'Lookup enabled' : 'Lookup disabled'}
                </Badge>
              )}
              <Badge tone="accent">{user.role}</Badge>
            </div>
          </div>

          {form.hasVisibility && (
            <>
              <div className="panel-solid rounded-2xl p-5">
                <div className="eyebrow">Profile visibility</div>
                <div className="mt-3">
                  <ChoiceRow
                    name="visibility"
                    value={visibility}
                    onChange={(v) => setVisibility(v)}
                    options={[
                      { value: 'public', label: 'Findable by ID', description: 'Faculty & recruiters with your exact student ID can view permitted fields.' },
                      { value: 'private', label: 'Private', description: 'Lookups fail with a generic error until you switch back.' },
                    ]}
                  />
                </div>
                <div className="mt-4">
                  <Toggle
                    checked={showPhone}
                    onChange={setShowPhone}
                    label="Expose phone number"
                    description="Off by default — even when your profile is visible."
                  />
                </div>
              </div>

              <div className="panel-solid rounded-2xl p-5">
                <div className="eyebrow">Profile-visible documents</div>
                {visibleDocs.length === 0 ? (
                  <p className="text-sm text-muted mt-2">
                    None yet. Mark documents “Show on my profile” from your vault.
                  </p>
                ) : (
                  <div className="mt-3 space-y-2">
                    {visibleDocs.map((d) => (
                      <div key={d.document_id} className="flex items-center justify-between gap-2 text-[13px]">
                        <span className="truncate">{d.filename}</span>
                        <button
                          className="btn btn-danger btn-sm focus-ring"
                          onClick={() => toggleDoc(d, false)}
                        >
                          Hide
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* edit form */}
        <div className="lg:col-span-2 panel-solid rounded-2xl p-5 sm:p-6">
          <div className="flex items-center gap-2.5 mb-4">
            {ROLE_ICONS[role]}
            <h2 className="text-[15px] font-semibold">{form.title}</h2>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            {form.fields.filter((f) => !f.wide).map(renderField)}
          </div>
          {form.fields.filter((f) => f.wide).map((f) => (
            <div key={f.name} className="mt-4">
              {renderField(f)}
            </div>
          ))}

          <div className="mt-5 flex justify-end">
            <Button variant="primary" loading={saving} onClick={save}>
              Save changes
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
