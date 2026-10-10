import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, BookOpenCheck, Brain, FileLock2, GaugeCircle, KeyRound, Link2,
  ScrollText, ShieldCheck, TimerReset, UserRoundCheck, Users,
} from 'lucide-react'
import type { Role } from '../lib/types'
import { RoleSelector } from './auth/AuthLayout'
import GoogleAuthButton from '../components/GoogleAuthButton'

const features = [
  {
    icon: FileLock2,
    title: 'Encrypted before storage',
    body: 'Every file is encrypted with AES-256-GCM using a unique per-document key wrapped by AWS KMS. Ciphertext at rest is unreadable without the controlled decryption path.',
  },
  {
    icon: Link2,
    title: 'Sharing you can revoke',
    body: 'Create high-entropy share links with viewer permissions and expiry — 1 hour, 24 hours, 7 days, or custom. Revoke instantly. Every access is audited.',
  },
  {
    icon: Users,
    title: 'Roles with boundaries',
    body: 'Faculty find students only by exact student ID. Recruiters see only profile-visible content. There is no global student directory, by design.',
  },
  {
    icon: ScrollText,
    title: 'A complete audit trail',
    body: 'Sign-ins, uploads, views, downloads, share creation and revocation are recorded — accountability without leaking secrets into logs.',
  },
  {
    icon: Brain,
    title: 'Private personal intelligence',
    body: 'Opt in to OBSIDIAN Intelligence: a personal knowledge base built only from your own documents, isolated in its own partition. Never a global RAG.',
  },
  {
    icon: TimerReset,
    title: 'MFA on every sign-in',
    body: 'Email one-time codes through Resend — single-use, time-limited, attempt-limited and rate-limited. Verified server-side, always.',
  },
]

const steps = [
  { n: '01', t: 'Store privately', b: 'Upload certificates, resumes and marksheets. They are encrypted before they ever touch storage.' },
  { n: '02', t: 'Share deliberately', b: 'Grant exactly one permission, for exactly one duration, to exactly one link or person.' },
  { n: '03', t: 'Revoke instantly', b: 'One click ends access — expired and revoked links fail server-side, immediately.' },
  { n: '04', t: 'Understand your data', b: 'Activity, security events and your personal knowledge base make your own data legible.' },
]

export default function Landing() {
  const [role, setRole] = useState<Role>('student')
  return (
    <div className="min-h-screen">
      {/* nav */}
      <header className="glass sticky top-0 z-40 border-b border-white/60">
        <div className="max-w-6xl mx-auto px-5 h-16 flex items-center justify-between">
          <div className="flex items-baseline gap-3">
            <span className="text-[13px] font-semibold tracking-[0.34em] text-charcoal">OBSIDIAN</span>
            <span className="hidden sm:inline text-[11px] text-faint tracking-wide">Student document vault</span>
          </div>
          <nav className="flex items-center gap-1 sm:gap-2">
            <Link to="/about" className="btn btn-ghost btn-sm focus-ring">About</Link>
            <Link to="/security" className="btn btn-ghost btn-sm focus-ring">Security</Link>
            <Link to="/login" className="btn btn-soft btn-sm focus-ring">Sign in</Link>
            <Link to="/signup" className="btn btn-primary btn-sm focus-ring">Create account</Link>
          </nav>
        </div>
      </header>

      {/* hero */}
      <section className="max-w-6xl mx-auto px-5 pt-16 sm:pt-24 pb-14">
        <div className="max-w-3xl">
          <div className="eyebrow flex items-center gap-2">
            <ShieldCheck size={13} className="text-cognac" />
            Secure cloud document sharing · encrypted
          </div>
          <h1 className="mt-5 text-4xl sm:text-6xl font-semibold leading-[1.04] text-editorial">
            Your documents.
            <br />
            Your keys.
            <br />
            <span className="text-cognac">Your control.</span>
          </h1>
          <p className="mt-6 text-base sm:text-lg text-muted leading-relaxed max-w-xl">
            OBSIDIAN is a privacy-first vault for students: encrypted storage, deliberate
            sharing, expiring and revocable links, role-based access, full auditability —
            and an optional personal AI that only ever knows your own information.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/signup" className="btn btn-primary btn-lg focus-ring">
              Create your vault <ArrowRight size={16} />
            </Link>
            <Link to="/security" className="btn btn-soft btn-lg focus-ring">
              How security works
            </Link>
          </div>

          {/* role-aware Google auth — every role, sign-in and sign-up */}
          <div className="mt-8 max-w-md">
            <RoleSelector value={role} onChange={setRole} />
            <div className="mt-3">
              <GoogleAuthButton role={role} />
            </div>
            <p className="mt-3 text-xs text-faint">
              One tap for students, faculty, recruiters and admins — Google handles both
              sign-in and sign-up.
            </p>
          </div>
        </div>

        {/* floating vault preview */}
        <div className="mt-14 glass rounded-3xl p-4 sm:p-6 fade-up">
          <div className="grid sm:grid-cols-3 gap-4">
            {[
              { icon: KeyRound, label: 'Envelope encryption', value: 'AES-256-GCM · KMS-wrapped keys', tone: 'text-cognac' },
              { icon: GaugeCircle, label: 'Authorization', value: 'Server-side, every request', tone: 'text-success' },
              { icon: UserRoundCheck, label: 'Isolation', value: 'One personal RAG per user', tone: 'text-info' },
            ].map((x) => (
              <div key={x.label} className="panel-solid rounded-2xl p-4">
                <x.icon size={17} className={x.tone} />
                <div className="eyebrow mt-3">{x.label}</div>
                <div className="text-sm font-medium mt-1">{x.value}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* features */}
      <section className="max-w-6xl mx-auto px-5 py-14">
        <div className="eyebrow">Built around the security model</div>
        <h2 className="mt-3 text-2xl sm:text-3xl font-semibold text-editorial">
          Security is the product, not a visual theme
        </h2>
        <div className="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {features.map((f) => (
            <div key={f.title} className="panel-solid rounded-2xl p-5 hover:shadow-[var(--shadow-lift)] transition-shadow">
              <div className="w-9 h-9 rounded-xl bg-ivory-deep flex items-center justify-center text-cognac">
                <f.icon size={17} strokeWidth={1.9} />
              </div>
              <h3 className="mt-4 text-[15px] font-semibold">{f.title}</h3>
              <p className="mt-1.5 text-sm text-muted leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* promise */}
      <section className="max-w-6xl mx-auto px-5 py-14">
        <div className="glass rounded-3xl p-7 sm:p-10">
          <div className="eyebrow">The promise</div>
          <p className="mt-4 text-xl sm:text-2xl leading-relaxed text-editorial max-w-3xl">
            Store privately. Share deliberately. Revoke instantly.
            <span className="text-cognac"> Understand your own data.</span>
          </p>
          <div className="mt-8 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {steps.map((s) => (
              <div key={s.n} className="rounded-2xl bg-white/70 border hairline p-4">
                <div className="text-[11px] font-semibold text-cognac tracking-[0.2em]">{s.n}</div>
                <div className="mt-2 text-sm font-semibold">{s.t}</div>
                <div className="mt-1 text-[13px] text-muted leading-relaxed">{s.b}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* roles */}
      <section className="max-w-6xl mx-auto px-5 py-14">
        <div className="eyebrow">Controlled roles</div>
        <div className="mt-6 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { t: 'Student', b: 'Owns the vault: upload, encrypt, share, revoke, audit — and an optional personal AI.' },
            { t: 'Faculty', b: 'Looks up a student by exact student ID. Sees only what the student permits. No browsing.' },
            { t: 'Recruiter', b: 'Views profile-visible content only. Private vault documents remain unreachable.' },
            { t: 'Administrator', b: 'Aggregate analytics and security monitoring — never private document contents.' },
          ].map((r) => (
            <div key={r.t} className="panel-solid rounded-2xl p-5">
              <div className="text-sm font-semibold text-cognac-deep">{r.t}</div>
              <p className="mt-2 text-[13px] text-muted leading-relaxed">{r.b}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-6xl mx-auto px-5 pb-20">
        <div className="panel-solid rounded-3xl p-8 sm:p-10 text-center">
          <BookOpenCheck className="mx-auto text-cognac" size={26} />
          <h2 className="mt-4 text-2xl font-semibold text-editorial">Begin with a private vault</h2>
          <p className="mt-2 text-sm text-muted max-w-lg mx-auto">
            Register with your role, verify with an email code, complete your profile,
            and decide — explicitly — whether you want a personal knowledge base.
          </p>

          <div className="mt-7 max-w-md mx-auto">
            <RoleSelector value={role} onChange={setRole} />
          </div>

          <div className="mt-4 max-w-sm mx-auto">
            <GoogleAuthButton role={role} label="Continue with Google" />
            <div className="my-5 flex items-center gap-3 text-xs text-faint">
              <span className="h-px bg-beige flex-1" />
              or
              <span className="h-px bg-beige flex-1" />
            </div>
            <div className="flex flex-wrap justify-center gap-3">
              <Link to="/signup" className="btn btn-accent focus-ring">Create account</Link>
              <Link to="/login" className="btn btn-soft focus-ring">I have an account</Link>
            </div>
          </div>

          <p className="mt-6 text-xs text-faint">
            Google sign-in works for every role — student, faculty, recruiter and admin —
            for both sign-up and sign-in.
          </p>
        </div>
      </section>

      <footer className="border-t hairline">
        <div className="max-w-6xl mx-auto px-5 py-8 flex flex-col sm:flex-row items-center justify-between gap-3 text-[13px] text-faint">
          <span>OBSIDIAN — secure student document sharing, built with encryption.</span>
          <div className="flex gap-5">
            <Link to="/about" className="hover:text-graphite transition-colors">About</Link>
            <Link to="/security" className="hover:text-graphite transition-colors">Security</Link>
            <Link to="/signup" className="hover:text-graphite transition-colors">Get started</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
