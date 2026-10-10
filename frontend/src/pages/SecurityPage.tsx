import { Link } from 'react-router-dom'
import { Fingerprint, KeyRound, Lock, ShieldAlert, ShieldCheck, Waypoints } from 'lucide-react'
import { PageNav } from './About'

const sections = [
  {
    icon: Lock,
    t: 'AES-256-GCM document encryption',
    b: 'Each upload generates a fresh 256-bit data encryption key. The file is encrypted with AES-256-GCM (authenticated encryption, so tampering is detected), and the key itself is wrapped by AWS KMS. Only ciphertext ever lands in the private S3 bucket — metadata and wrapped keys live in DynamoDB.',
  },
  {
    icon: KeyRound,
    t: 'Envelope key management',
    b: 'KMS master key → wrapped per-document DEK → ciphertext. Keys never leave the backend, never appear in API responses, never enter vector storage, and never touch a model prompt. Key versions are retained for rotation.',
  },
  {
    icon: Fingerprint,
    t: 'Authentication & MFA',
    b: 'Argon2id password hashing, server-side sessions in HttpOnly SameSite cookies, and email one-time codes delivered through Resend: cryptographically generated, time-limited, single-use, attempt-limited and rate-limited. Google OAuth validates issuer, audience and expiry.',
  },
  {
    icon: ShieldCheck,
    t: 'Server-side authorization',
    b: 'Every request is authenticated from the session, then authorized by role, ownership and share state. The frontend never supplies a role, owner, permission or RAG identity that the server trusts. Denials are generic so hidden resources cannot be probed.',
  },
  {
    icon: Waypoints,
    t: 'Isolated personal AI',
    b: 'If you consent, your knowledge base lives in its own partition keyed by your user ID. Retrieval is scoped to that partition before anything else happens; there is no global index with filters. Ask about another student and the assistant returns a scope message — it never confirms anyone exists.',
  },
  {
    icon: ShieldAlert,
    t: 'Audit without leakage',
    b: 'Sign-ins, MFA attempts, uploads, downloads, share activity, lookups and security events are recorded with request correlation IDs. Passwords, OTPs, keys and raw share tokens are never written to logs.',
  },
]

export default function SecurityPage() {
  return (
    <div className="min-h-screen">
      <PageNav />
      <section className="max-w-3xl mx-auto px-5 py-14 sm:py-20">
        <div className="eyebrow">Security model</div>
        <h1 className="mt-4 text-3xl sm:text-4xl font-semibold text-editorial">
          Defense in depth, fail closed
        </h1>
        <p className="mt-5 text-muted leading-relaxed">
          Encryption is not a substitute for authorization, and a vector namespace is not a
          security boundary. When a check cannot be completed safely, OBSIDIAN denies access
          rather than guesses.
        </p>

        <div className="mt-8 panel-solid rounded-2xl p-5">
          <div className="eyebrow">Every sensitive request passes through</div>
          <div className="mt-3 flex flex-wrap gap-2 text-[13px]">
            {['Authenticate', 'Identify user', 'Validate role', 'Authorize resource',
              'Validate share expiry/revocation', 'Validate integrity', 'Decrypt only when necessary',
              'Return minimum data', 'Write audit event'].map((s, i) => (
              <span key={s} className="rounded-full bg-ivory-deep border hairline px-3 py-1.5 text-graphite">
                <span className="text-cognac font-semibold mr-1.5">{i + 1}</span>
                {s}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-6 grid sm:grid-cols-2 gap-4">
          {sections.map((s) => (
            <div key={s.t} className="panel-solid rounded-2xl p-5">
              <s.icon size={17} className="text-cognac" />
              <h2 className="mt-3 text-[15px] font-semibold">{s.t}</h2>
              <p className="mt-1.5 text-[13.5px] text-muted leading-relaxed">{s.b}</p>
            </div>
          ))}
        </div>

        <div className="glass rounded-2xl p-6 mt-8">
          <div className="eyebrow">Share link guarantees</div>
          <div className="mt-3 space-y-2 text-sm text-graphite">
            <p>• 256-bit cryptographically random tokens — only the SHA-256 hash is stored.</p>
            <p>• Expiry is enforced server-side: 1 hour, 24 hours, 7 days, custom, or never.</p>
            <p>• Revocation is immediate and permanent — a revoked link never revives.</p>
            <p>• Token endpoints are rate-limited against brute force and fully audited.</p>
          </div>
        </div>

        <div className="mt-10 flex gap-3">
          <Link to="/signup" className="btn btn-accent focus-ring">Create your vault</Link>
          <Link to="/about" className="btn btn-soft focus-ring">About OBSIDIAN</Link>
        </div>
      </section>
    </div>
  )
}
