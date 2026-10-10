import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import AuthLayout from './AuthLayout'
import { Button, Field, Input } from '../../components/ui'

export default function Forgot() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [dev, setDev] = useState<{ challenge_id: string; dev_otp?: string } | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await api<any>('/auth/password/forgot', {
        method: 'POST',
        body: { email },
      })
      setSent(true)
      if (data.challenge_id) setDev({ challenge_id: data.challenge_id, dev_otp: data.dev_otp })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Request failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="We'll email you a one-time reset code."
      footer={
        <Link to="/login" className="text-cognac-deep font-medium hover:underline">
          Back to sign in
        </Link>
      }
    >
      {!sent ? (
        <form onSubmit={submit} className="space-y-5">
          <Field label="Email" htmlFor="forgot-email">
            <Input
              id="forgot-email"
              type="email"
              required
              autoComplete="email"
              placeholder="you@university.edu"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          {error && (
            <div className="rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
              {error}
            </div>
          )}
          <Button type="submit" variant="primary" className="w-full" loading={loading}>
            Send reset code
          </Button>
        </form>
      ) : (
        <div className="panel-solid rounded-2xl p-5 text-sm text-muted leading-relaxed">
          If an account exists for that email, a reset code is on its way. It expires in
          5 minutes.
          {dev?.dev_otp && (
            <button
              type="button"
              onClick={() => navigate('/reset', { state: dev })}
              className="mt-4 w-full rounded-xl border border-dashed border-cognac/40 bg-cognac/5 px-4 py-2.5 text-[13px] text-cognac-deep hover:bg-cognac/10 transition-colors focus-ring"
            >
              Dev mode — continue with code <span className="font-semibold tracking-widest">{dev.dev_otp}</span>
            </button>
          )}
        </div>
      )}
    </AuthLayout>
  )
}
