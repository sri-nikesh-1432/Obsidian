import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, ArrowUpRight, BadgeCheck, BookOpenCheck, Briefcase, Building2,
  Check, Clock3, Copy, Database, FileLock2, Fingerprint, GraduationCap,
  KeyRound, Link2, Lock, ScrollText, ShieldCheck, Sparkles, UserRound, Users,
} from 'lucide-react'
import type { Role } from '../lib/types'
import { RoleSelector } from './auth/AuthLayout'
import GoogleAuthButton from '../components/GoogleAuthButton'

/* ------------------------------------------------------------------ data */

const TRUST = [
  { k: 'AES-256-GCM', v: 'authenticated encryption' },
  { k: 'AWS KMS', v: 'envelope-wrapped keys' },
  { k: 'Argon2id', v: 'password hashing' },
  { k: 'Per-user RAG', v: 'no global index' },
]

const CAPABILITIES = [
  {
    icon: Link2,
    title: 'Links with a lifespan',
    body: 'Grant a viewer permission for one hour, a day, a week — or a custom window. Revoke with one click and access ends server-side, immediately.',
  },
  {
    icon: Users,
    title: 'Roles with hard edges',
    body: 'Faculty and recruiters find a student only by their exact issued ID. There is no directory, no browsing, and no way to enumerate accounts.',
  },
  {
    icon: ScrollText,
    title: 'A trail you can read',
    body: 'Sign-ins, uploads, views, downloads, share creation and revocation are recorded — accountability without leaking secrets into logs.',
  },
  {
    icon: Sparkles,
    title: 'Intelligence, isolated',
    body: 'Opt in and OBSIDIAN indexes only your own documents, in a partition no other account can reach. Opt out and every vector is deleted.',
  },
  {
    icon: Fingerprint,
    title: 'A code, every time',
    body: 'Single-use email one-time codes secure every sign-in: time-limited, attempt-limited and rate-limited, verified on the server.',
  },
]

const STEPS = [
  { n: '01', t: 'Store privately', b: 'Certificates, resumes and marksheets are encrypted before they touch storage.' },
  { n: '02', t: 'Share deliberately', b: 'One permission, one duration, one link — chosen by you, never inferred.' },
  { n: '03', t: 'Revoke instantly', b: 'Expired and revoked links fail server-side the moment you decide.' },
  { n: '04', t: 'Stay legible', b: 'Activity, security events and an optional personal knowledge base.' },
]

const ROLES: { icon: typeof UserRound; name: string; tagline: string; points: string[] }[] = [
  { icon: UserRound, name: 'Student', tagline: 'Owns the vault', points: ['Encrypted uploads', 'Expiring shares', 'Opt-in personal AI'] },
  { icon: GraduationCap, name: 'Faculty', tagline: 'Verifies by exact ID', points: ['ID-only lookup', 'Consent-scoped view', 'No directory'] },
  { icon: Briefcase, name: 'Recruiter', tagline: 'Sees only what is offered', points: ['Profile-visible only', 'No private vault', 'Every access audited'] },
  { icon: ShieldCheck, name: 'Administrator', tagline: 'Guards the whole system', points: ['Aggregate analytics', 'Security monitoring', 'Never file contents'] },
]

const DOCS = [
  { name: 'B.Tech_Degree_Certificate.pdf', size: '1.4 MB', tone: 'Private' },
  { name: 'Summer_Internship_Offer.pdf', size: '248 KB', tone: 'Shared' },
  { name: 'Semester_6_Marksheet.pdf', size: '512 KB', tone: 'Private' },
]

/* ------------------------------------------------------- product preview */

function VaultPreview() {
  return (
    <div className="relative">
      {/* ambient glow */}
      <div
        aria-hidden
        className="absolute -inset-6 -z-10 rounded-[36px] opacity-70 blur-2xl"
        style={{ background: 'radial-gradient(60% 60% at 70% 20%, rgba(201,141,99,0.30), transparent 70%)' }}
      />

      <div className="glass-deep rounded-3xl overflow-hidden">
        {/* window chrome */}
        <div className="flex items-center gap-2 px-4 h-11 border-b border-white/60 bg-white/40">
          <span className="w-2.5 h-2.5 rounded-full bg-beige-dark" />
          <span className="w-2.5 h-2.5 rounded-full bg-beige-dark" />
          <span className="w-2.5 h-2.5 rounded-full bg-beige-dark" />
          <span className="ml-3 flex items-center gap-1.5 text-[11px] text-faint">
            <Lock size={10} className="text-success" />
            obsidian.app / vault
          </span>
        </div>

        <div className="p-4 sm:p-5">
          {/* vault header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-charcoal flex items-center justify-center">
                <FileLock2 size={15} className="text-[#e6c9a8]" />
              </div>
              <div>
                <div className="text-[13px] font-semibold leading-tight">Your vault</div>
                <div className="text-[11px] text-faint">3 documents · 2.16 MB</div>
              </div>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-success/25 bg-success/10 px-2.5 py-0.5 text-[11px] font-medium text-success">
              <ShieldCheck size={11} /> Encrypted
            </span>
          </div>

          {/* document rows */}
          <div className="mt-4 space-y-2">
            {DOCS.map((d) => (
              <div
                key={d.name}
                className="flex items-center justify-between gap-3 rounded-xl border hairline bg-white/70 px-3.5 py-2.5"
              >
                <div className="min-w-0 flex items-center gap-3">
                  <span className="w-7 h-7 rounded-lg bg-cognac/10 text-cognac flex items-center justify-center shrink-0">
                    <FileLock2 size={13} />
                  </span>
                  <div className="min-w-0">
                    <div className="text-[12.5px] font-medium truncate">{d.name}</div>
                    <div className="text-[11px] text-faint">{d.size} · AES-256-GCM</div>
                  </div>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium border ${
                    d.tone === 'Shared'
                      ? 'border-info/25 bg-info/10 text-info'
                      : 'border-beige-dark bg-beige/60 text-graphite'
                  }`}
                >
                  {d.tone}
                </span>
              </div>
            ))}
          </div>

          {/* share chip */}
          <div className="mt-4 rounded-xl border border-cognac/25 bg-cognac/[0.04] p-3.5">
            <div className="flex items-center justify-between">
              <span className="eyebrow flex items-center gap-1.5 text-cognac-deep">
                <Link2 size={11} /> Share link
              </span>
              <span className="inline-flex items-center gap-1 text-[11px] text-warning font-medium">
                <Clock3 size={11} /> expires 23:59:59
              </span>
            </div>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 truncate rounded-lg bg-white/80 border hairline px-2.5 py-1.5 text-[11.5px] text-graphite">
                obsidian.app/s/9f3a…
              </code>
              <span className="btn btn-soft btn-sm pointer-events-none">
                <Copy size={12} /> Copy
              </span>
            </div>
            <div className="mt-2 text-[11px] text-faint">Viewer permission · revocable · access audited</div>
          </div>
        </div>
      </div>

      {/* floating audit toast */}
      <div className="hidden sm:flex absolute -left-5 bottom-8 items-center gap-2 rounded-xl glass px-3.5 py-2.5 shadow-[var(--shadow-lift)]">
        <span className="w-6 h-6 rounded-lg bg-success/12 text-success flex items-center justify-center">
          <BadgeCheck size={13} />
        </span>
        <div className="leading-tight">
          <div className="text-[11.5px] font-medium">Access logged</div>
          <div className="text-[10.5px] text-faint">viewer · 14:03</div>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ page */

export default function Landing() {
  const [role, setRole] = useState<Role>('student')
  return (
    <div className="min-h-screen">
      {/* ------------------------------------------------------------ nav */}
      <header className="glass sticky top-0 z-40 border-b border-white/60">
        <div className="max-w-6xl mx-auto px-5 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2.5 focus-ring rounded-lg">
            <span className="w-8 h-8 rounded-[10px] bg-charcoal flex items-center justify-center">
              <svg viewBox="0 0 32 32" className="w-5 h-5" aria-hidden>
                <path d="M16 7l7 4.5v9L16 25l-7-4.5v-9L16 7z" fill="none" stroke="#c98d63" strokeWidth="1.8" />
              </svg>
            </span>
            <span className="flex flex-col leading-none">
              <span className="text-[13px] font-semibold tracking-[0.32em] text-charcoal">OBSIDIAN</span>
              <span className="hidden sm:block text-[10px] text-faint tracking-wide mt-1">Secure document vault</span>
            </span>
          </Link>

          <nav className="hidden md:flex items-center gap-7 text-[13px] text-graphite">
            <a href="#capabilities" className="hover:text-charcoal transition-colors">Capabilities</a>
            <a href="#roles" className="hover:text-charcoal transition-colors">Roles</a>
            <Link to="/security" className="hover:text-charcoal transition-colors">Security</Link>
            <Link to="/about" className="hover:text-charcoal transition-colors">About</Link>
          </nav>

          <div className="flex items-center gap-1.5 sm:gap-2">
            <Link to="/login" className="btn btn-ghost btn-sm focus-ring">Sign in</Link>
            <Link to="/signup" className="btn btn-primary btn-sm focus-ring">Create account</Link>
          </div>
        </div>
      </header>

      {/* ----------------------------------------------------------- hero */}
      <section className="max-w-6xl mx-auto px-5 pt-14 sm:pt-20 pb-16">
        <div className="grid lg:grid-cols-12 gap-10 lg:gap-12 items-center">
          <div className="lg:col-span-6">
            <div className="inline-flex items-center gap-2 rounded-full border hairline bg-white/70 px-3 py-1.5 text-[11.5px] text-graphite">
              <ShieldCheck size={13} className="text-cognac" />
              Encrypted storage · deliberate sharing · full audit
            </div>

            <h1 className="mt-6 text-[2.6rem] sm:text-6xl font-semibold leading-[1.02] text-editorial">
              Own your records.
              <br />
              Share on
              <br />
              <span className="text-cognac">your terms.</span>
            </h1>

            <p className="mt-6 text-base sm:text-lg text-muted leading-relaxed max-w-lg">
              OBSIDIAN is a privacy-first vault for students. Files are encrypted before they
              are stored, links carry an expiry you set, and every role sees only what they
              are permitted — nothing more.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link to="/signup" className="btn btn-primary btn-lg focus-ring">
                Create your vault <ArrowRight size={16} />
              </Link>
              <Link to="/security" className="btn btn-soft btn-lg focus-ring">
                How security works
              </Link>
            </div>

            <p className="mt-4 text-xs text-faint flex flex-wrap items-center gap-x-4 gap-y-1">
              <span className="inline-flex items-center gap-1.5"><Check size={12} className="text-success" /> 5 GB free to start</span>
              <span className="inline-flex items-center gap-1.5"><Check size={12} className="text-success" /> No card required</span>
              <span className="inline-flex items-center gap-1.5"><Check size={12} className="text-success" /> Revoke anytime</span>
            </p>

            {/* role-aware Google auth — every role, sign-in and sign-up */}
            <div className="mt-9 max-w-md rounded-2xl border hairline bg-white/60 p-4">
              <RoleSelector value={role} onChange={setRole} />
              <div className="mt-3">
                <GoogleAuthButton role={role} />
              </div>
              <p className="mt-2.5 text-xs text-faint">
                One tap for students, faculty, recruiters and admins — Google handles both
                sign-in and sign-up.
              </p>
            </div>
          </div>

          <div className="lg:col-span-6 fade-up">
            <VaultPreview />
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------- trustbar */}
      <section className="border-y hairline bg-white/40">
        <div className="max-w-6xl mx-auto px-5 py-6 grid grid-cols-2 md:grid-cols-4 gap-6">
          {TRUST.map((t) => (
            <div key={t.k}>
              <div className="text-[15px] font-semibold text-editorial">{t.k}</div>
              <div className="text-xs text-faint mt-0.5">{t.v}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------- capabilities */}
      <section id="capabilities" className="max-w-6xl mx-auto px-5 py-16 sm:py-20">
        <div className="max-w-2xl">
          <div className="eyebrow">What it does</div>
          <h2 className="mt-3 text-3xl sm:text-4xl font-semibold text-editorial">
            Security as the product, not a coat of paint
          </h2>
          <p className="mt-4 text-muted leading-relaxed">
            Every guarantee below is enforced server-side. The interface simply tells the
            truth about what the system already does.
          </p>
        </div>

        <div className="mt-10 grid lg:grid-cols-3 gap-4">
          {/* feature spotlight */}
          <div className="lg:col-span-2 glass-deep rounded-3xl p-6 sm:p-8 flex flex-col justify-between">
            <div>
              <div className="w-10 h-10 rounded-2xl bg-cognac/10 text-cognac flex items-center justify-center">
                <KeyRound size={19} strokeWidth={1.9} />
              </div>
              <h3 className="mt-5 text-xl font-semibold text-editorial">Envelope encryption, before storage</h3>
              <p className="mt-2 text-sm text-muted leading-relaxed max-w-xl">
                Each document gets its own AES-256-GCM data key, wrapped by a rotating AWS KMS
                master key. Storage only ever holds ciphertext — the decryption path is
                controlled, per request, per permission.
              </p>
            </div>
            <div className="mt-6 flex flex-wrap items-center gap-2 text-[12px] text-graphite">
              {['Plaintext', 'Per-file key', 'KMS wrap', 'Ciphertext at rest'].map((step, i, arr) => (
                <span key={step} className="flex items-center gap-2">
                  <span className="rounded-lg border hairline bg-white/70 px-2.5 py-1.5">{step}</span>
                  {i < arr.length - 1 && <ArrowRight size={12} className="text-faint" />}
                </span>
              ))}
            </div>
          </div>

          <div className="panel-solid rounded-3xl p-6 flex flex-col justify-between">
            <div className="w-10 h-10 rounded-2xl bg-ivory-deep text-cognac flex items-center justify-center">
              <Database size={18} strokeWidth={1.9} />
            </div>
            <div>
              <h3 className="mt-5 text-[15px] font-semibold">Your own partition</h3>
              <p className="mt-2 text-sm text-muted leading-relaxed">
                The personal assistant only ever answers from your documents and profile. There
                is no shared index, so cross-user retrieval is structurally impossible.
              </p>
            </div>
          </div>

          {CAPABILITIES.map((c) => (
            <div key={c.title} className="panel-solid rounded-3xl p-6 hover:shadow-[var(--shadow-lift)] transition-shadow">
              <div className="w-10 h-10 rounded-2xl bg-ivory-deep text-cognac flex items-center justify-center">
                <c.icon size={18} strokeWidth={1.9} />
              </div>
              <h3 className="mt-5 text-[15px] font-semibold">{c.title}</h3>
              <p className="mt-2 text-sm text-muted leading-relaxed">{c.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* -------------------------------------------------------------- roles */}
      <section id="roles" className="max-w-6xl mx-auto px-5 py-16 sm:py-20">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="max-w-2xl">
            <div className="eyebrow">Four roles, one standard</div>
            <h2 className="mt-3 text-3xl sm:text-4xl font-semibold text-editorial">
              Everyone gets the same clarity
            </h2>
          </div>
          <p className="text-sm text-muted max-w-sm">
            Each role signs in through one flow, lands on a purpose-built home, and can only
            ever perform the actions their role allows.
          </p>
        </div>

        <div className="mt-10 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {ROLES.map((r) => (
            <div key={r.name} className="panel-solid rounded-3xl p-6 flex flex-col h-full">
              <div className="w-11 h-11 rounded-2xl bg-cognac/10 text-cognac-deep flex items-center justify-center ring-1 ring-cognac/15">
                <r.icon size={19} strokeWidth={1.9} />
              </div>
              <h3 className="mt-5 text-lg font-semibold text-editorial">{r.name}</h3>
              <p className="text-[13px] text-cognac-deep mt-0.5">{r.tagline}</p>
              <ul className="mt-4 space-y-2 text-[13px] text-graphite">
                {r.points.map((p) => (
                  <li key={p} className="flex items-start gap-2">
                    <Check size={13} className="text-success mt-0.5 shrink-0" />
                    {p}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* -------------------------------------------------------------- steps */}
      <section className="max-w-6xl mx-auto px-5 pb-16 sm:pb-20">
        <div className="glass rounded-3xl p-7 sm:p-10">
          <div className="grid lg:grid-cols-12 gap-8 items-start">
            <div className="lg:col-span-4">
              <div className="eyebrow">How it flows</div>
              <p className="mt-4 text-2xl leading-relaxed text-editorial">
                Store privately. Share deliberately.
                <span className="text-cognac"> Revoke instantly.</span>
              </p>
            </div>
            <div className="lg:col-span-8 grid sm:grid-cols-2 gap-4">
              {STEPS.map((s) => (
                <div key={s.n} className="rounded-2xl bg-white/70 border hairline p-4">
                  <div className="text-[11px] font-semibold text-cognac tracking-[0.2em]">{s.n}</div>
                  <div className="mt-2 text-sm font-semibold">{s.t}</div>
                  <div className="mt-1 text-[13px] text-muted leading-relaxed">{s.b}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------------- CTA */}
      <section className="max-w-6xl mx-auto px-5 pb-20">
        <div className="glass-deep rounded-3xl p-8 sm:p-12">
          <div className="grid lg:grid-cols-2 gap-10 items-center">
            <div>
              <BookOpenCheck className="text-cognac" size={26} />
              <h2 className="mt-4 text-3xl font-semibold text-editorial">
                Begin with a private vault
              </h2>
              <p className="mt-3 text-sm text-muted max-w-md leading-relaxed">
                Register with your role, verify with an email code, complete your profile, and
                decide — explicitly — whether you want a personal knowledge base.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <Link to="/signup" className="btn btn-accent focus-ring">
                  Create account <ArrowUpRight size={15} />
                </Link>
                <Link to="/login" className="btn btn-soft focus-ring">I have an account</Link>
              </div>
              <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-xs text-faint">
                <span className="inline-flex items-center gap-1.5"><Building2 size={12} /> Built for institutions</span>
                <span className="inline-flex items-center gap-1.5"><ShieldCheck size={12} /> Audited access</span>
              </div>
            </div>

            <div className="rounded-2xl border hairline bg-white/60 p-5 max-w-md w-full lg:ml-auto">
              <RoleSelector value={role} onChange={setRole} />
              <div className="mt-3">
                <GoogleAuthButton role={role} label="Continue with Google" />
              </div>
              <div className="my-4 flex items-center gap-3 text-xs text-faint">
                <span className="h-px bg-beige flex-1" />
                or
                <span className="h-px bg-beige flex-1" />
              </div>
              <div className="flex flex-wrap gap-3">
                <Link to="/signup" className="btn btn-accent focus-ring">Create account</Link>
                <Link to="/login" className="btn btn-soft focus-ring">Sign in</Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------- footer */}
      <footer className="border-t hairline">
        <div className="max-w-6xl mx-auto px-5 py-10 grid sm:grid-cols-2 gap-6 items-center">
          <div className="flex items-center gap-2.5">
            <span className="w-7 h-7 rounded-lg bg-charcoal flex items-center justify-center">
              <svg viewBox="0 0 32 32" className="w-4 h-4" aria-hidden>
                <path d="M16 7l7 4.5v9L16 25l-7-4.5v-9L16 7z" fill="none" stroke="#c98d63" strokeWidth="1.8" />
              </svg>
            </span>
            <span className="text-[13px] text-faint">
              OBSIDIAN — secure student document sharing, built with encryption.
            </span>
          </div>
          <div className="flex flex-wrap sm:justify-end gap-5 text-[13px] text-faint">
            <Link to="/about" className="hover:text-graphite transition-colors">About</Link>
            <Link to="/security" className="hover:text-graphite transition-colors">Security</Link>
            <Link to="/signup" className="hover:text-graphite transition-colors">Get started</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
