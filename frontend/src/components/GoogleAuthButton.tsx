import { useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { Role } from '../lib/types'
import { Button } from './ui'

/**
 * Google "G" mark. Shared so every auth surface renders the same branding.
 */
export function GoogleIcon({ size = 15 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
      <path fill="#4285F4" d="M23.5 12.3c0-.9-.1-1.5-.3-2.2H12v4.1h6.5c-.1 1.1-.8 2.7-2.4 3.8l3.7 2.9c2.3-2.1 3.7-5.2 3.7-8.6z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 7.9-2.9l-3.7-2.9c-1 .7-2.4 1.2-4.2 1.2-3.2 0-6-2.1-7-5.1L1.2 17C3.1 21.2 7.3 24 12 24z" />
      <path fill="#FBBC05" d="M5 14.3c-.3-.8-.4-1.6-.4-2.3s.2-1.6.4-2.3L1.2 6.7C.4 8.3 0 10.1 0 12s.4 3.7 1.2 5.3L5 14.3z" />
      <path fill="#EA4335" d="M12 4.7c1.8 0 3 .8 3.7 1.4l3.3-3.2C17.9 1.1 15.2 0 12 0 7.3 0 3.1 2.8 1.2 6.7l3.8 3c1-3 3.8-5 7-5z" />
    </svg>
  )
}

/**
 * Starts the server-side Google OAuth flow for the selected role.
 *
 * The role is passed to `/auth/google/start`, which stashes it server-side with
 * a single-use `state` value. The callback then signs in an existing account or
 * provisions a new one with that role — so it works for both sign-in and
 * sign-up on every role. The backend keeps the OAuth client secret; the browser
 * only ever receives the authorization URL.
 */
export default function GoogleAuthButton({
  role,
  label = 'Continue with Google',
  variant = 'soft',
  size = 'md',
  className = '',
  onError,
}: {
  role: Role
  label?: string
  variant?: 'primary' | 'accent' | 'soft' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  className?: string
  onError?: (message: string) => void
}) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')

  const start = async () => {
    setError('')
    setLoading(true)
    setProgress(`Opening Google for ${role}…`)
    try {
      const data = await api<{ url: string }>(`/auth/google/start?role=${role}`)
      if (!data?.url) throw new Error('missing url')
      // Full-page redirect: the callback must be the registered redirect URI.
      window.location.href = data.url
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : 'Google sign-in could not be started.'
      setError(message)
      setProgress('')
      setLoading(false)
      onError?.(message)
    }
  }

  return (
    <div>
      <Button
        type="button"
        variant={variant}
        size={size}
        className={`w-full ${className}`}
        loading={loading}
        onClick={start}
      >
        <GoogleIcon />
        {label}
      </Button>
      {progress && !error && <p className="text-xs text-faint mt-2 text-center">{progress}</p>}
      {error && (
        <p className="text-xs text-danger mt-2 text-center leading-relaxed" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
