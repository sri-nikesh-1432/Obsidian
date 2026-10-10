import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

export function PageNav() {
  return (
    <header className="glass sticky top-0 z-40 border-b border-white/60">
      <div className="max-w-6xl mx-auto px-5 h-16 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 text-graphite hover:text-charcoal transition-colors focus-ring rounded">
          <ArrowLeft size={15} />
          <span className="text-[13px] font-semibold tracking-[0.3em]">OBSIDIAN</span>
        </Link>
        <nav className="flex items-center gap-1 sm:gap-2">
          <Link to="/login" className="btn btn-soft btn-sm focus-ring">Sign in</Link>
          <Link to="/signup" className="btn btn-primary btn-sm focus-ring">Create account</Link>
        </nav>
      </div>
    </header>
  )
}

export default function About() {
  return (
    <div className="min-h-screen">
      <PageNav />

      <section className="max-w-3xl mx-auto px-5 py-14 sm:py-20">
        <div className="eyebrow">About the project</div>
        <h1 className="mt-4 text-3xl sm:text-4xl font-semibold text-editorial">
          Design and Development of a Secure Cloud-Based Student Document Sharing System Using Encryption
        </h1>
        <p className="mt-5 text-muted leading-relaxed">
          Students keep certificates, resumes, marksheets, internship records, project reports
          and recommendation letters scattered across phones, laptops, email threads, cloud
          drives and messaging apps. Sharing usually means losing control: links stay alive too
          long, nobody knows who accessed a file, and private records leak into public drives.
        </p>

        <div className="mt-8 space-y-4">
          {[
            {
              t: 'The problem',
              b: 'Documents are scattered, links are uncontrolled, access is invisible, profile data and private files get mixed, and generic AI assistants can leak context between users when isolation is built incorrectly.',
            },
            {
              t: 'The approach',
              b: 'Encryption before persistence, authorization enforced strictly server-side, explicit sharing decisions, expiring and revocable links, role-based access control, audit logs, profile privacy, and an optional per-user personal knowledge base.',
            },
            {
              t: 'What OBSIDIAN is not',
              b: 'Not a recruitment platform, not a job marketplace, not a LinkedIn clone, not a social network, not a generic cloud drive, and not a public chatbot. Recruiter and faculty access exist only as controlled consumption roles inside the document-sharing system.',
            },
          ].map((s) => (
            <div key={s.t} className="panel-solid rounded-2xl p-5">
              <h2 className="text-[15px] font-semibold text-cognac-deep">{s.t}</h2>
              <p className="mt-2 text-sm text-muted leading-relaxed">{s.b}</p>
            </div>
          ))}
        </div>

        <div className="glass rounded-2xl p-6 mt-8">
          <div className="eyebrow">Principles</div>
          <div className="mt-3 grid sm:grid-cols-2 gap-2.5 text-sm">
            {[
              'Security — encrypted at rest, authorized server-side',
              'Privacy — private unless the owner grants access',
              'Least privilege — minimum permission everywhere',
              'Explicit sharing — restricted, link, or profile-visible',
              'Revocability — access ends without deleting the file',
              'Isolation — one personal AI per user, never global',
              'Transparency — sensitive events are auditable',
              'Simplicity — understandable without weakening security',
            ].map((p) => (
              <div key={p} className="rounded-xl bg-white/70 border hairline px-3.5 py-2.5 text-graphite">
                {p}
              </div>
            ))}
          </div>
        </div>

        <div className="mt-10 flex gap-3">
          <Link to="/signup" className="btn btn-accent focus-ring">Create your vault</Link>
          <Link to="/security" className="btn btn-soft focus-ring">Read the security model</Link>
        </div>
      </section>
    </div>
  )
}
