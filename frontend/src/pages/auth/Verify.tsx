import { useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { homePathFor, useAuth } from '../../store/auth'
import AuthLayout from './AuthLayout'
import { Button, Field, Input } from '../../components/ui'
import { useToast } from '../../store/toast'

interface VerifyState {
  challenge_id: string
  email: string
  purpose: 'signup' | 'login'
  role: string
  next?: string
}

export default function Verify() {
  const location = useLocation()
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const toast = useToast()
  const state = location.state as VerifyState | null

  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [resending, setResending] = useState(false)
  const [seconds, setSeconds] = useState(30)

  useEffect(() => {
    if (!state) return
    const t = setInterval(() => setSeconds((s) => (s > 0 ? s - 1 : 0)), 1000)
    return () => clearInterval(t)
  }, [state])

  if (!state) return <Navigate to="/login" replace />

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await api<any>('/auth/otp/verify', {
        method: 'POST',
        body: { challenge_id: state.challenge_id, code: code.trim() },
      })

      if (state.purpose === 'login' && state.role && data.role && data.role !== state.role) {
        await api('/auth/logout', { method: 'POST' }).catch(() => undefined)
        setError(
          `This account is registered as ${data.role}. Continue as ${data.role}, or create a ${state.role} account.`,
        )
        setLoading(false)
        return
      }

      await refresh()
      const onboarded = Boolean(data.onboarding_complete) || data.role === 'admin'
      if (!onboarded) {
        navigate('/onboarding', { replace: true })
      } else {
        navigate(state.next || homePathFor(data.role), { replace: true })
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification failed.')
      setCode('')
    } finally {
      setLoading(false)
    }
  }

  const resend = async () => {
    setResending(true)
    setError('')
    try {
      await api('/auth/otp/request', {
        method: 'POST',
        body: { challenge_id: state.challenge_id },
      })
      toast.push('success', 'A new code has been sent.')
      setSeconds(30)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resend the code.')
    } finally {
      setResending(false)
    }
  }

  return (
    <AuthLayout
      title="Enter your code"
      subtitle={`We sent a one-time code to ${state.email}. It expires in 5 minutes and can be used once.`}
      footer={
        <button
          type="button"
          className="text-muted hover:text-cognac-deep transition-colors"
          onClick={() => navigate('/login')}
        >
          ← Back to sign in
        </button>
      }
    >
      <form onSubmit={submit} className="space-y-5">
        <Field
          label="One-time code"
          htmlFor="otp"
          hint="6 digits, delivered by email"
        >
          <Input
            id="otp"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            required
            placeholder="••••••"
            className="text-center tracking-[0.5em] text-lg font-semibold"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          />
        </Field>

        {error && (
          <div className="rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        <Button type="submit" variant="primary" className="w-full" loading={loading} disabled={code.length !== 6}>
          Verify and continue
        </Button>

        <div className="text-center text-[13px] text-muted">
          Didn't receive it?{' '}
          <button
            type="button"
            onClick={resend}
            disabled={resending || seconds > 0}
            className="text-cognac-deep font-medium hover:underline disabled:opacity-50 disabled:no-underline"
          >
            {seconds > 0 ? `Resend in ${seconds}s` : 'Resend code'}
          </button>
        </div>
      </form>
    </AuthLayout>
  )
}
