import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import AuthLayout from './AuthLayout'
import { Button, Field, Input } from '../../components/ui'

export default function Forgot() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await api<{ challenge_id?: string }>('/auth/password/forgot', {
        method: 'POST',
        body: { email },
      })
      if (data.challenge_id) {
        navigate('/reset', { state: { challenge_id: data.challenge_id } })
        return
      }
      setSent(true)
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
        </div>
      )}
    </AuthLayout>
  )
}
