import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import type { Role } from '../../lib/types'
import AuthLayout, { RoleSelector } from './AuthLayout'
import GoogleAuthButton from '../../components/GoogleAuthButton'
import { Button, Field, Input } from '../../components/ui'

export default function Signup() {
  const [role, setRole] = useState<Role>('student')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await api<{ challenge_id: string; email: string }>(
        '/auth/register',
        { method: 'POST', body: { role, email, password, full_name: name } },
      )
      navigate('/verify', { state: { ...data, purpose: 'signup', role } })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Registration failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout
      title="Create your vault"
      subtitle="Choose your role. We'll send a one-time code to verify your email."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="text-cognac-deep font-medium hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-5">
        <RoleSelector value={role} onChange={setRole} />

        <Field label="Full name" htmlFor="su-name">
          <Input
            id="su-name"
            required
            maxLength={120}
            placeholder="Your name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>

        <Field label="Email" htmlFor="su-email">
          <Input
            id="su-email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@university.edu"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>

        <Field
          label="Password"
          htmlFor="su-password"
          hint="At least 10 characters."
        >
          <Input
            id="su-password"
            type="password"
            required
            minLength={10}
            autoComplete="new-password"
            placeholder="Choose a strong password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>

        {error && (
          <div className="rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        <Button type="submit" variant="accent" className="w-full" loading={loading}>
          Send verification code
        </Button>

        <p className="text-xs text-faint leading-relaxed text-center">
          By continuing you agree to the platform rules: documents stay private unless you
          share them, and role permissions are enforced server-side.
        </p>
      </form>

      <div className="my-5 flex items-center gap-3 text-xs text-faint">
        <span className="h-px bg-beige flex-1" />
        or sign up with
        <span className="h-px bg-beige flex-1" />
      </div>

      <GoogleAuthButton role={role} label="Sign up with Google" />
    </AuthLayout>
  )
}
