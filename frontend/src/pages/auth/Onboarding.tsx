import { useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Brain, BookOpen, Briefcase, CheckCircle2, GraduationCap, ShieldCheck } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { homePathFor, useAuth } from '../../store/auth'
import type { FieldDef, Role } from '../../lib/roleProfile'
import { roleForm } from '../../lib/roleProfile'
import { Button, ChoiceRow, Field, Input, Select, Textarea } from '../../components/ui'
import { useToast } from '../../store/toast'

const CONSENT_TEXT =
  'I consent to processing my profile information and uploaded documents to create and maintain my private personal AI knowledge base. This information will be used by OBSIDIAN Intelligence to answer questions about my own information and documents. My personal knowledge base is isolated from other users.'

const ROLE_ICONS: Record<Role, ReactNode> = {
  student: <GraduationCap size={18} />,
  faculty: <BookOpen size={18} />,
  recruiter: <Briefcase size={18} />,
  admin: <ShieldCheck size={18} />,
}

export default function Onboarding() {
  const { user, refresh } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()

  const role = (user?.role as Role) ?? 'student'
  const form = roleForm(role)

  const [step, setStep] = useState<1 | 2>(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = { profile_visibility: 'public' }
    for (const f of form.fields) initial[f.name] = ''
    initial.full_name = user?.profile?.full_name ?? ''
    initial.phone = user?.profile?.phone ?? ''
    return initial
  })
  const [consent, setConsent] = useState<'yes' | 'no' | ''>('')

  const setValue = (name: string) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [name]: e.target.value }))

  const submitProfile = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const body: Record<string, unknown> = {}
      for (const f of form.fields) {
        const raw = (values[f.name] ?? '').trim()
        if (f.kind === 'list') {
          body[f.name] = raw ? raw.split(',').map((s) => s.trim()).filter(Boolean) : []
        } else if (raw) {
          body[f.name] = raw
        }
      }
      if (form.hasVisibility) body.profile_visibility = values.profile_visibility || 'public'
      await api('/profile', { method: 'PATCH', body })
      setStep(2)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save your profile.')
    } finally {
      setLoading(false)
    }
  }

  const submitConsent = async () => {
    if (!consent) {
      setError('Please choose whether to enable your personal knowledge base.')
      return
    }
    setError('')
    setLoading(true)
    try {
      await api('/intelligence/consent', { method: 'POST', body: { consent: consent === 'yes' } })
      await refresh()
      toast.push(
        'success',
        consent === 'yes'
          ? 'Welcome — your personal knowledge base is ready.'
          : 'Your profile is ready. Personal AI stays off.',
      )
      navigate(homePathFor(user?.role), { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save your choice.')
    } finally {
      setLoading(false)
    }
  }

  const renderField = (f: FieldDef) => {
    const common = { id: `ob-${f.name}`, value: values[f.name] ?? '', onChange: setValue(f.name) }
    return (
      <Field key={f.name} label={f.label} htmlFor={common.id} hint={f.hint}>
        {f.kind === 'textarea' ? (
          <Textarea {...common} rows={3} maxLength={1200} placeholder={f.placeholder} />
        ) : f.kind === 'select' ? (
          <Select {...common} required={f.required}>
            <option value="">Select…</option>
            {(f.options ?? []).map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </Select>
        ) : (
          <Input {...common} required={f.required} placeholder={f.placeholder} />
        )}
      </Field>
    )
  }

  return (
    <div className="min-h-screen px-5 py-10 sm:py-16">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between">
          <div className="text-[12px] font-semibold tracking-[0.34em] text-cognac">OBSIDIAN</div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <span className={step === 1 ? 'text-charcoal font-medium' : ''}>1 · Profile</span>
            <span className="w-6 h-px bg-beige-dark" />
            <span className={step === 2 ? 'text-charcoal font-medium' : ''}>2 · Personal AI</span>
          </div>
        </div>

        {step === 1 ? (
          <form onSubmit={submitProfile} className="glass rounded-3xl p-6 sm:p-8 mt-6 fade-up">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-ivory-deep flex items-center justify-center text-cognac">
                {ROLE_ICONS[role]}
              </div>
              <div>
                <h1 className="text-xl font-semibold text-editorial">{form.title}</h1>
                <p className="text-sm text-muted">{form.subtitle}</p>
              </div>
            </div>

            {user?.email && (
              <p className="mt-4 text-[13px] text-muted">
                Signed in as <span className="font-medium text-graphite">{user.email}</span> ·{' '}
                <span className="capitalize">{role}</span>
              </p>
            )}

            <div className="mt-6 grid sm:grid-cols-2 gap-4">
              {form.fields.filter((f) => !f.wide).map(renderField)}
            </div>
            {form.fields.filter((f) => f.wide).map((f) => (
              <div key={f.name} className="mt-4">
                {renderField(f)}
              </div>
            ))}

            {form.hasVisibility && (
              <>
                <div className="mt-5">
                  <ChoiceRow
                    name="Profile visibility"
                    value={values.profile_visibility || 'public'}
                    onChange={(v) => setValues((s) => ({ ...s, profile_visibility: v }))}
                    options={[
                      { value: 'public', label: 'Profile visible', description: 'Faculty and recruiters can find you with your student ID.' },
                      { value: 'private', label: 'Private', description: 'Nobody can look you up until you make it visible.' },
                    ]}
                  />
                </div>
                <div className="mt-5 rounded-xl border hairline bg-white/70 px-4 py-3 text-[13px] text-muted flex items-center gap-2.5">
                  <ShieldCheck size={15} className="text-success shrink-0" />
                  Your opaque student ID is generated automatically — it's the only key faculty
                  can use to find you.
                </div>
              </>
            )}

            {form.note && (
              <div className="mt-5 rounded-xl border hairline bg-white/70 px-4 py-3 text-[13px] text-muted flex items-center gap-2.5">
                <ShieldCheck size={15} className="text-success shrink-0" />
                {form.note}
              </div>
            )}

            {error && (
              <div className="mt-4 rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
                {error}
              </div>
            )}

            <div className="mt-6 flex justify-end">
              <Button type="submit" variant="primary" loading={loading}>
                Continue
              </Button>
            </div>
          </form>
        ) : (
          <div className="glass rounded-3xl p-6 sm:p-8 mt-6 fade-up">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-ivory-deep flex items-center justify-center text-cognac">
                <Brain size={18} />
              </div>
              <div>
                <h1 className="text-xl font-semibold text-editorial">Personal AI — optional</h1>
                <p className="text-sm text-muted">
                  OBSIDIAN Intelligence answers questions about your own documents and profile.
                </p>
              </div>
            </div>

            <div className="mt-6 rounded-2xl border hairline bg-white/75 p-5">
              <div className="eyebrow">Consent</div>
              <p className="mt-2 text-sm text-graphite leading-relaxed">{CONSENT_TEXT}</p>
              <ul className="mt-4 space-y-2 text-[13px] text-muted">
                <li className="flex gap-2"><CheckCircle2 size={14} className="text-success mt-0.5 shrink-0" />Personal — stored in a partition only you can query.</li>
                <li className="flex gap-2"><CheckCircle2 size={14} className="text-success mt-0.5 shrink-0" />Query-only — the assistant can never change files, links or settings.</li>
                <li className="flex gap-2"><CheckCircle2 size={14} className="text-success mt-0.5 shrink-0" />Reversible — turn it off any time and every vector is deleted.</li>
              </ul>
            </div>

            <div className="mt-5">
              <ChoiceRow
                name="consent"
                value={consent}
                onChange={(v) => setConsent(v)}
                options={[
                  { value: 'yes', label: 'Yes, create my personal knowledge base' },
                  { value: 'no', label: 'Keep personal AI off', description: 'No indexing, no embeddings, and no AI interface anywhere in your account.' },
                ]}
              />
            </div>

            {error && (
              <div className="mt-4 rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
                {error}
              </div>
            )}

            <div className="mt-6 flex justify-between items-center">
              <Button variant="ghost" onClick={() => setStep(1)} type="button">
                ← Back
              </Button>
              <Button variant="accent" loading={loading} onClick={submitConsent} type="button">
                Finish setup
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
