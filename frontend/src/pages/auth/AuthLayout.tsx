import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { GraduationCap, Briefcase, ShieldCheck, UserRound } from 'lucide-react'
import type { Role } from '../../lib/types'

export function RoleSelector({
  value,
  onChange,
}: {
  value: Role
  onChange: (r: Role) => void
}) {
  const options: { value: Role; label: string; icon: typeof UserRound }[] = [
    { value: 'student', label: 'Student', icon: UserRound },
    { value: 'faculty', label: 'Faculty', icon: GraduationCap },
    { value: 'recruiter', label: 'Recruiter', icon: Briefcase },
    { value: 'admin', label: 'Admin', icon: ShieldCheck },
  ]
  return (
    <div>
      <span className="text-[13px] font-medium text-graphite">Continue as</span>
      <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2" role="radiogroup" aria-label="Account role">
        {options.map((opt) => {
          const active = opt.value === value
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(opt.value)}
              className={`flex flex-col items-center gap-1.5 rounded-xl border px-2 py-3 transition-all focus-ring ${
                active
                  ? 'border-cognac/70 bg-cognac/6 shadow-[0_0_0_3px_rgba(162,96,58,0.10)] text-cognac-deep'
                  : 'border-beige bg-white/70 text-graphite hover:border-faint/60'
              }`}
            >
              <opt.icon size={16} strokeWidth={1.9} />
              <span className="text-[12.5px] font-medium">{opt.label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string
  subtitle: string
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      {/* brand side */}
      <aside className="hidden lg:flex flex-col justify-between p-10 xl:p-14 glass border-r border-white/60">
        <Link to="/" className="text-[12px] font-semibold tracking-[0.34em] text-charcoal">
          OBSIDIAN
        </Link>
        <div>
          <h2 className="text-3xl xl:text-4xl font-semibold leading-tight text-editorial">
            A vault that keeps
            <br />
            its promises.
          </h2>
          <p className="mt-4 text-sm text-muted max-w-sm leading-relaxed">
            Encrypted storage, deliberate sharing, expiring links, revocable access, audited
            activity — and an optional personal knowledge base that never crosses users.
          </p>
          <div className="mt-8 space-y-2.5 text-[13px] text-graphite">
            {[
              'AES-256-GCM encrypted before storage',
              'MFA email codes on every sign-in',
              'No global student directory, ever',
            ].map((line) => (
              <div key={line} className="flex items-center gap-2.5">
                <span className="w-1.5 h-1.5 rounded-full bg-cognac" />
                {line}
              </div>
            ))}
          </div>
        </div>
        <div className="text-xs text-faint">Store privately. Share deliberately. Revoke instantly.</div>
      </aside>

      {/* form side */}
      <main className="flex items-center justify-center px-5 py-12 sm:py-16">
        <div className="w-full max-w-md fade-up">
          <div className="lg:hidden text-[12px] font-semibold tracking-[0.34em] text-cognac mb-8 text-center">
            OBSIDIAN
          </div>
          <h1 className="text-2xl font-semibold text-editorial">{title}</h1>
          <p className="text-sm text-muted mt-1.5">{subtitle}</p>
          <div className="mt-7">{children}</div>
          {footer && <div className="mt-6 text-sm text-muted text-center">{footer}</div>}
        </div>
      </main>
    </div>
  )
}
