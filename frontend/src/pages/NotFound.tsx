import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center px-5">
      <div className="text-center max-w-sm">
        <div className="text-[11px] font-semibold tracking-[0.34em] text-cognac">OBSIDIAN</div>
        <h1 className="mt-5 text-3xl font-semibold text-editorial">Page not found</h1>
        <p className="mt-3 text-sm text-muted">
          The page you requested does not exist, or you do not have permission to view it.
        </p>
        <Link to="/" className="btn btn-primary mt-6 focus-ring">Return home</Link>
      </div>
    </div>
  )
}
