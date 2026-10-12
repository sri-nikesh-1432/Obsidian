import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import type { Role } from '../../lib/types'
import AuthLayout, { RoleSelector } from './AuthLayout'
import GoogleAuthButton from '../../components/GoogleAuthButton'
import { Button, Field, Input } from '../../components/ui'

export default function Login() {
  const [role, setRole] = useState<Role>('student')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = params.get('next') || ''

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await api<{ challenge_id: string; email: string }>(
        '/auth/login',
        { method: 'POST', body: { email, password, role } },
      )
      navigate('/verify', {
        state: { ...data, purpose: 'login', role, next },
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Sign-in failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Select your role, then verify with your email code."
      footer={
        <>
          New to OBSIDIAN?{' '}
          <Link to="/signup" className="text-cognac-deep font-medium hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-5">
        <RoleSelector value={role} onChange={setRole} />

        <Field label="Email" htmlFor="login-email">
          <Input
            id="login-email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@university.edu"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>

        <Field label="Password" htmlFor="login-password">
          <Input
            id="login-password"
            type="password"
            autoComplete="current-password"
            required
            placeholder="Your password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>

        {error && (
          <div className="rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex items-center justify-between">
          <Link to="/forgot" className="text-[13px] text-muted hover:text-cognac-deep transition-colors">
            Forgot password?
          </Link>
          <Button type="submit" variant="primary" loading={loading}>
            Continue
          </Button>
        </div>
      </form>

      <div className="my-5 flex items-center gap-3 text-xs text-faint">
        <span className="h-px bg-beige flex-1" />
        or
        <span className="h-px bg-beige flex-1" />
      </div>

      <GoogleAuthButton role={role} />
    </AuthLayout>
  )
}
