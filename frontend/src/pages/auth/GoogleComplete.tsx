import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth, homePathFor } from '../../store/auth'
import { Spinner } from '../../components/ui'

/** Landing point after the Google OAuth redirect. */
export default function GoogleComplete() {
  const { refresh, user, loading } = useAuth()
  const navigate = useNavigate()
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current) return
    ran.current = true
    void refresh().then(() => {
      // small delay so the auth state is applied
      setTimeout(() => {
        const me = user
        if (me && !me.onboarding_complete) navigate('/onboarding', { replace: true })
      }, 0)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (loading) return
    if (!user) {
      navigate('/login?next=%2Fapp%2Fdashboard', { replace: true })
      return
    }
    navigate(user.onboarding_complete ? homePathFor(user.role) : '/onboarding', { replace: true })
  }, [user, loading, navigate])

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="text-[11px] font-semibold tracking-[0.34em] text-cognac mb-4">OBSIDIAN</div>
        <Spinner label="Completing sign-in…" />
      </div>
    </div>
  )
}
