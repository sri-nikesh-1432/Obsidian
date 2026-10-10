import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import AuthLayout from './AuthLayout'
import { Button, Field, Input } from '../../components/ui'
import { useToast } from '../../store/toast'

interface ResetState {
  challenge_id: string
  dev_otp?: string
}

export default function Reset() {
  const location = useLocation()
  const navigate = useNavigate()
  const toast = useToast()
  const state = location.state as ResetState | null

  const [code, setCode] = useState(state?.dev_otp ?? '')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (!state) return <Navigate to="/forgot" replace />

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api('/auth/password/reset', {
        method: 'POST',
        body: { challenge_id: state.challenge_id, code: code.trim(), new_password: password },
      })
      toast.push('success', 'Password updated. Please sign in again.')
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Reset failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout
      title="Choose a new password"
      subtitle="Enter the code we emailed, then your new password. All sessions will be signed out."
      footer={
        <Link to="/login" className="text-cognac-deep font-medium hover:underline">
          Back to sign in
        </Link>
      }
    >
      <form onSubmit={submit} className="space-y-5">
        <Field label="One-time code" htmlFor="reset-code">
          <Input
            id="reset-code"
            inputMode="numeric"
            maxLength={6}
            required
            placeholder="••••••"
            className="text-center tracking-[0.5em] text-lg font-semibold"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          />
        </Field>
        <Field label="New password" htmlFor="reset-password" hint="At least 10 characters.">
          <Input
            id="reset-password"
            type="password"
            minLength={10}
            required
            autoComplete="new-password"
            placeholder="New password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        {error && (
          <div className="rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}
        <Button type="submit" variant="primary" className="w-full" loading={loading}>
          Update password
        </Button>
      </form>
    </AuthLayout>
  )
}
