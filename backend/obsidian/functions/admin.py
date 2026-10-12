"""Admin endpoints: aggregate analytics, users, security monitoring.

Admin access never exposes document plaintext or encryption material —
administrative visibility follows the privacy policy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from .. import audit, aws, plans
from ..config import settings
from ..context import RequestContext
from ..errors import invalid_input, not_found
from ..router import route

ADMIN = ("admin",)


def _storage_backend_label() -> str:
    if settings.kv_configured:
        return "cloudflare-workers-kv"
    if settings.r2_configured:
        return "cloudflare-r2"
    return "s3"


@route("GET", "/admin/analytics", roles=ADMIN)
def analytics(req: RequestContext) -> dict:
    users = _scan("users", 2000)
    documents = _scan("documents", 5000)
    shares = _scan("shares", 5000)
    group_items = _scan("groups", 5000)

    active_docs = [d for d in documents if not d.get("deleted_at")]
    now = datetime.now(timezone.utc).isoformat()
    group_metas = [g for g in group_items if g.get("sk") == "META"]
    group_members = [g for g in group_items if str(g.get("sk", "")).startswith("MEMBER#")]
    group_messages = [g for g in group_items if str(g.get("sk", "")).startswith("MSG#")]

    by_role: dict[str, int] = {}
    ai_enabled = 0
    for u in users:
        by_role[u.get("role", "unknown")] = by_role.get(u.get("role", "unknown"), 0) + 1
        if u.get("ai_enabled"):
            ai_enabled += 1

    share_status = {"active": 0, "expired": 0, "revoked": 0}
    for s in shares:
        if s.get("revoked_at"):
            share_status["revoked"] += 1
        elif s.get("expires_at") and s["expires_at"] < now:
            share_status["expired"] += 1
        else:
            share_status["active"] += 1

    storage_bytes = sum(int(d.get("size_bytes", 0)) for d in active_docs)

    return {
        "users": {
            "total": len(users),
            "by_role": by_role,
            "mfa_enabled": sum(1 for u in users if u.get("mfa_enabled")),
            "ai_enabled": ai_enabled,
        },
        "documents": {
            "total": len(active_docs),
            "storage_bytes": storage_bytes,
            "public": sum(1 for d in active_docs if d.get("visibility") == "public"),
            "private": sum(1 for d in active_docs if d.get("visibility") != "public"),
            "profile_visible": sum(1 for d in active_docs if d.get("profile_visible")),
        },
        "shares": {
            "total": len(shares),
            **share_status,
        },
        "groups": {
            "total": len(group_metas),
            "memberships": len(group_members),
            "messages": len(group_messages),
        },
        "security": _security_counts(),
        "health": {
            "status": "operational",
            "storage_backend": _storage_backend_label(),
            "metadata_backend": "dynamodb",
            "encryption": "AES-256-GCM (envelope, KMS)",
            "checked_at": now,
        },
    }


def _security_counts() -> dict:
    counts = {}
    for et in ("login_failure", "otp_failure", "authorization_denied",
               "share_access_denied", "rate_limit_triggered", "suspicious_activity"):
        try:
            resp = aws.table("audit").query(
                IndexName="gsi1",
                KeyConditionExpression=Key("gsi1pk").eq(f"TYPE#{et}"),
                Select="COUNT",
            )
            counts[et] = resp.get("Count", 0)
        except Exception:
            counts[et] = 0
    return counts


def _scan(table_name: str, limit: int) -> list[dict]:
    tbl = aws.table(table_name)
    items: list[dict] = []
    kwargs: dict = {"Limit": min(limit, 1000)}
    while len(items) < limit:
        resp = tbl.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


@route("GET", "/admin/users", roles=ADMIN)
def list_users(req: RequestContext) -> dict:
    role_filter = str(req.query.get("role", "")).lower()
    try:
        limit = min(int(req.query.get("limit", 100)), 500)
    except ValueError:
        limit = 100
    users = _scan("users", 2000)
    if role_filter:
        users = [u for u in users if u.get("role") == role_filter]
    users.sort(key=lambda u: u.get("created_at", ""), reverse=True)

    now = datetime.now(timezone.utc).isoformat()
    out = []
    for u in users[:limit]:
        out.append({
            "user_id": u["user_id"],
            "email": u.get("email", ""),
            "role": u.get("role", ""),
            "status": u.get("status", ""),
            "mfa_enabled": bool(u.get("mfa_enabled")),
            "ai_enabled": bool(u.get("ai_enabled")),
            "verification_status": u.get("verification_status", "verified"),
            "created_at": u.get("created_at", ""),
            "last_login_at": u.get("last_login_at", ""),
        })
    return {"users": out, "total": len(users)}


@route("POST", "/admin/users/{user_id}/verification", roles=ADMIN)
def set_verification(req: RequestContext) -> dict:
    """Approve or withdraw a faculty/recruiter account's access."""
    actor = req.require_auth()
    target = str(req.path_params["user_id"])
    status = str(req.body.get("status", "")).lower()
    if status not in ("verified", "pending"):
        raise invalid_input("Status must be 'verified' or 'pending'.")
    if target == actor["user_id"]:
        raise invalid_input("You cannot change your own verification status.")

    resp = aws.table("users").get_item(Key={"pk": f"USER#{target}", "sk": "META"})
    if not resp.get("Item"):
        raise not_found()

    aws.table("users").update_item(
        Key={"pk": f"USER#{target}", "sk": "META"},
        UpdateExpression="SET verification_status = :s, updated_at = :t",
        ExpressionAttributeValues={":s": status, ":t": audit.now_iso()},
    )
    audit.write_event(
        actor_id=actor["user_id"], actor_role=actor["role"],
        event_type="verification_changed", resource_type="user",
        resource_id=target, request_id=req.request_id,
        metadata={"verification_status": status},
    )
    return {"user_id": target, "verification_status": status}


@route("GET", "/admin/security-events", roles=ADMIN)
def security_events(req: RequestContext) -> dict:
    try:
        limit = min(int(req.query.get("limit", 60)), 200)
    except ValueError:
        limit = 60
    events = audit.list_security_events(limit=limit)
    return {"events": [{
        "event_id": e.get("event_id", ""),
        "event_type": e.get("event_type", ""),
        "timestamp": e.get("timestamp", ""),
        "actor_id": (e.get("actor_id") or "")[:12],
        "actor_role": e.get("actor_role", ""),
        "result": e.get("result", ""),
        "resource_type": e.get("resource_type", ""),
        "request_id": e.get("request_id", "")[:16],
        "metadata": e.get("metadata", {}),
    } for e in events]}


@route("GET", "/admin/activity", roles=ADMIN)
def recent_activity(req: RequestContext) -> dict:
    events = _scan("audit", 500)
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return {"events": [{
        "event_id": e.get("event_id", ""),
        "event_type": e.get("event_type", ""),
        "timestamp": e.get("timestamp", ""),
        "actor_role": e.get("actor_role", ""),
        "result": e.get("result", ""),
        "resource_type": e.get("resource_type", ""),
        "metadata": e.get("metadata", {}),
    } for e in events[:80]]}


@route("GET", "/admin/shares", roles=ADMIN)
def share_stats(req: RequestContext) -> dict:
    shares = _scan("shares", 5000)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    status_counts = {"active": 0, "expired": 0, "revoked": 0}
    for s in shares:
        if s.get("sk") != "S":
            continue
        status = "revoked" if s.get("revoked_at") else (
            "expired" if s.get("expires_at") and s["expires_at"] < now else "active")
        status_counts[status] += 1
        rows.append({
            "share_id": s.get("share_id", ""),
            "mode": s.get("mode", ""),
            "permission": s.get("permission", ""),
            "status": status,
            "created_at": s.get("created_at", ""),
            "expires_at": s.get("expires_at", ""),
            "access_count": int(s.get("access_count", 0)),
            "document_id": s.get("document_id", ""),
        })
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return {"summary": status_counts, "shares": rows[:100], "total": len(rows)}


@route("GET", "/admin/rag", roles=ADMIN)
def rag_stats(req: RequestContext) -> dict:
    instances = [i for i in _scan("rag", 5000) if i.get("sk") == "INSTANCE"]
    enabled = [i for i in instances if i.get("enabled")]
    chunks = sum(int(i.get("chunk_count", 0)) for i in instances)
    return {
        "total_instances": len(instances),
        "enabled": len(enabled),
        "disabled": len(instances) - len(enabled),
        "total_chunks": chunks,
        "isolation_model": "per-user partition (RAG#<user_id>)",
    }


# --------------------------------------------------------------- insights

def _extension_of(doc: dict) -> str:
    name = str(doc.get("filename", ""))
    if "." not in name:
        return "other"
    ext = name.rsplit(".", 1)[-1].strip().lower()
    return ext or "other"


def _day_of(value: str | None) -> str:
    return str(value or "")[:10]


def build_insights() -> dict:
    """One aggregate snapshot of the whole platform for charts and the
    administration assistant. Never contains document plaintext or secrets."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    users = _scan("users", 5000)
    documents = _scan("documents", 20000)
    shares = _scan("shares", 20000)
    group_items = _scan("groups", 10000)
    orders = [o for o in _scan("billing", 20000) if str(o.get("sk", "")) == "B"]
    sessions = _scan("sessions", 20000)
    audit_events = _scan("audit", 5000)
    rag_instances = [i for i in _scan("rag", 5000) if i.get("sk") == "INSTANCE"]

    active_docs = [d for d in documents if not d.get("deleted_at")]

    by_role: dict[str, int] = {}
    for u in users:
        role = u.get("role", "unknown")
        by_role[role] = by_role.get(role, 0) + 1
    logged_in = sum(1 for u in users if u.get("last_login_at"))
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    new_7d = sum(1 for u in users if str(u.get("created_at", "")) >= cutoff_7d)

    active_sessions = [
        s for s in sessions
        if not s.get("revoked_at") and str(s.get("expires_at_iso", "")) >= now_iso
    ]
    active_user_ids = {s.get("user_id") for s in active_sessions if s.get("user_id")}

    by_type: dict[str, int] = {}
    for d in active_docs:
        ext = _extension_of(d)
        by_type[ext] = by_type.get(ext, 0) + 1
    storage_bytes = sum(int(d.get("size_bytes", 0)) for d in active_docs)

    share_status = {"active": 0, "expired": 0, "revoked": 0}
    for s in shares:
        if s.get("revoked_at"):
            share_status["revoked"] += 1
        elif s.get("expires_at") and str(s["expires_at"]) < now_iso:
            share_status["expired"] += 1
        else:
            share_status["active"] += 1

    by_status: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    revenue_paid_paise = 0
    revenue_pending_paise = 0
    paid_orders: list[dict] = []
    for o in orders:
        status = str(o.get("status", "created"))
        by_status[status] = by_status.get(status, 0) + 1
        amount = int(o.get("amount_paise", 0))
        if status == "paid":
            revenue_paid_paise += amount
            tier = str(o.get("tier", 0))
            by_tier[tier] = by_tier.get(tier, 0) + 1
            paid_orders.append(o)
        elif status in ("created", "authorized"):
            revenue_pending_paise += amount
    paid_orders.sort(
        key=lambda o: str(o.get("paid_at") or o.get("created_at") or ""), reverse=True)
    paid_count = by_status.get("paid", 0)

    group_metas = [g for g in group_items if g.get("sk") == "META"]
    group_members = [g for g in group_items if str(g.get("sk", "")).startswith("MEMBER#")]
    group_messages = [g for g in group_items if str(g.get("sk", "")).startswith("MSG#")]

    days = [(now.date() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    signups = {d: 0 for d in days}
    uploads = {d: 0 for d in days}
    logins = {d: 0 for d in days}
    for u in users:
        d = _day_of(u.get("created_at"))
        if d in signups:
            signups[d] += 1
    for doc in active_docs:
        d = _day_of(doc.get("created_at"))
        if d in uploads:
            uploads[d] += 1
    for e in audit_events:
        if e.get("event_type") == "login_success":
            d = _day_of(e.get("timestamp"))
            if d in logins:
                logins[d] += 1
    series = [
        {"date": d, "signups": signups[d], "uploads": uploads[d], "logins": logins[d]}
        for d in days
    ]

    rag_chunks = sum(int(i.get("chunk_count", 0)) for i in rag_instances)

    return {
        "generated_at": now_iso,
        "users": {
            "total": len(users),
            "by_role": by_role,
            "active": sum(1 for u in users if u.get("status", "active") == "active"),
            "logged_in": logged_in,
            "mfa_enabled": sum(1 for u in users if u.get("mfa_enabled")),
            "ai_enabled": sum(1 for u in users if u.get("ai_enabled")),
            "new_last_7d": new_7d,
        },
        "sessions": {
            "active": len(active_sessions),
            "logged_in_users": len(active_user_ids),
        },
        "documents": {
            "total": len(active_docs),
            "storage_bytes": storage_bytes,
            "public": sum(1 for d in active_docs if d.get("visibility") == "public"),
            "private": sum(1 for d in active_docs if d.get("visibility") != "public"),
            "profile_visible": sum(1 for d in active_docs if d.get("profile_visible")),
            "raggable": sum(1 for d in active_docs if d.get("rag_eligible")),
            "by_type": by_type,
        },
        "shares": {"total": len(shares), **share_status},
        "groups": {
            "total": len(group_metas),
            "memberships": len(group_members),
            "messages": len(group_messages),
        },
        "rag": {
            "instances": len(rag_instances),
            "enabled": sum(1 for i in rag_instances if i.get("enabled")),
            "chunks": rag_chunks,
        },
        "payments": {
            "orders_total": len(orders),
            "paid": paid_count,
            "pending": by_status.get("created", 0) + by_status.get("authorized", 0),
            "failed": by_status.get("failed", 0),
            "revenue_inr": revenue_paid_paise // 100,
            "pending_inr": revenue_pending_paise // 100,
            "avg_order_inr": (revenue_paid_paise // paid_count // 100) if paid_count else 0,
            "by_status": by_status,
            "by_tier": by_tier,
            "recent": [{
                "order_id": o.get("order_id", ""),
                "email": o.get("email", ""),
                "plan": plans.label_for_tier(int(o.get("tier", 0))),
                "amount_inr": int(o.get("amount_paise", 0)) // 100,
                "status": o.get("status", ""),
                "created_at": o.get("created_at", ""),
                "paid_at": o.get("paid_at", ""),
            } for o in paid_orders[:20]],
        },
        "series": series,
        "security": _security_counts(),
        "health": {
            "status": "operational",
            "storage_backend": _storage_backend_label(),
            "state_persistence": "enabled" if settings.state_persistence_enabled else "in-memory (non-durable)",
            "metadata_backend": "dynamodb",
            "checked_at": now_iso,
        },
    }


@route("GET", "/admin/insights", roles=ADMIN)
def insights(req: RequestContext) -> dict:
    return build_insights()


# --------------------------------------------------- administration assistant

def _inr(value: int) -> str:
    return f"INR {value:,}"


def _pct(part: int, whole: int) -> str:
    return f"{(part / whole * 100):.1f}%" if whole else "0.0%"


def _overview_answer(data: dict) -> str:
    u, d, p = data["users"], data["documents"], data["payments"]
    roles = ", ".join(f"{v} {k}" for k, v in sorted(u["by_role"].items(), key=lambda x: -x[1]))
    return (
        f"Platform overview — {data['generated_at'][:16].replace('T', ' ')} UTC\n"
        f"• Accounts: {u['total']} total ({roles or 'none'}); {u['logged_in']} have signed in; "
        f"{data['sessions']['active']} active session(s) right now.\n"
        f"• Vaults: {d['total']} documents, {_fmt_bytes(d['storage_bytes'])} stored "
        f"({d['private']} private / {d['public']} public).\n"
        f"• Shares: {data['shares']['total']} created ({data['shares']['active']} active).\n"
        f"• Payments: {p['paid']} paid order(s) for {_inr(p['revenue_inr'])}; "
        f"{p['pending']} pending, {p['failed']} failed.\n"
        f"• Groups: {data['groups']['total']} cohorts, {data['groups']['messages']} messages."
    )


def _users_answer(data: dict) -> str:
    u = data["users"]
    roles = "\n".join(
        f"  – {k.title()}: {v}" for k, v in sorted(u["by_role"].items(), key=lambda x: -x[1]))
    return (
        f"Accounts\n"
        f"• {u['total']} total; {u['active']} active; {u['new_last_7d']} created in the last 7 days.\n"
        f"• {u['logged_in']} have signed in at least once; {data['sessions']['logged_in_users']} "
        f"currently hold an unexpired session.\n"
        f"• {u['ai_enabled']} enabled personal AI; {u['mfa_enabled']} have MFA on.\n"
        f"By role:\n{roles or '  – none'}"
    )


def _logins_answer(data: dict) -> str:
    s = data["sessions"]
    u = data["users"]
    recent = sum(row["logins"] for row in data["series"][-7:])
    return (
        f"Sign-ins\n"
        f"• {u['logged_in']} of {u['total']} accounts have signed in at least once.\n"
        f"• {s['active']} session(s) are active right now across {s['logged_in_users']} user(s).\n"
        f"• {recent} successful sign-in(s) in the last 7 days."
    )


def _documents_answer(data: dict) -> str:
    d = data["documents"]
    if d["by_type"]:
        top = sorted(d["by_type"].items(), key=lambda x: -x[1])[:6]
        types = ", ".join(f"{k} ({v})" for k, v in top)
    else:
        types = "none"
    return (
        f"Files & storage\n"
        f"• {d['total']} documents totalling {_fmt_bytes(d['storage_bytes'])} of ciphertext.\n"
        f"• {d['private']} private, {d['public']} public, {d['profile_visible']} shown on profiles.\n"
        f"• {d['raggable']} eligible for personal AI indexing.\n"
        f"• Top file types: {types}."
    )


def _payments_answer(data: dict) -> str:
    p = data["payments"]
    tiers = ", ".join(f"tier {k}: {v}" for k, v in sorted(p["by_tier"].items())) or "none"
    lines = [
        "Payments & revenue",
        f"• {p['orders_total']} order(s) created: {p['paid']} paid, {p['pending']} pending, "
        f"{p['failed']} failed.",
        f"• Collected {_inr(p['revenue_inr'])}; {_inr(p['pending_inr'])} awaiting payment.",
        f"• Average paid order {_inr(p['avg_order_inr'])}. Paid by plan — {tiers}.",
    ]
    if p["recent"]:
        latest = p["recent"][0]
        lines.append(
            f"• Most recent paid order: {latest['plan']} for {_inr(latest['amount_inr'])} "
            f"({latest['email'] or 'unknown'}).")
    return "\n".join(lines)


def _shares_answer(data: dict) -> str:
    s = data["shares"]
    return (
        f"Share links\n"
        f"• {s['total']} links created — {s['active']} active, {s['expired']} expired, "
        f"{s['revoked']} revoked.\n"
        f"• {_pct(s['active'], s['total'])} of all links are currently live."
    )


def _groups_answer(data: dict) -> str:
    g = data["groups"]
    return (
        f"Groups\n"
        f"• {g['total']} cohort(s), {g['memberships']} memberships, {g['messages']} messages."
    )


def _security_answer(data: dict) -> str:
    sec = data["security"]
    total = sum(int(v) for v in sec.values())
    lines = ["Security posture", f"• {total} security event(s) recorded in total."]
    for name, count in sorted(sec.items(), key=lambda x: -int(x[1])):
        lines.append(f"  – {name.replace('_', ' ')}: {count}")
    return "\n".join(lines)


def _trend_answer(data: dict) -> str:
    series = data["series"]
    signups = sum(r["signups"] for r in series)
    uploads = sum(r["uploads"] for r in series)
    logins = sum(r["logins"] for r in series)
    return (
        f"Last 14 days\n"
        f"• {signups} new account(s) created.\n"
        f"• {uploads} document(s) uploaded.\n"
        f"• {logins} successful sign-in(s)."
    )


def _fmt_bytes(num: int) -> str:
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


_SUGGESTIONS = [
    "Give me a platform overview",
    "How many users signed in today?",
    "What are the payments and revenue?",
    "How much storage is used?",
    "Any security events to worry about?",
]


def answer_question(question: str, data: dict) -> dict:
    """A grounded, deterministic analyst over the live aggregate metrics.

    The assistant only ever reads the numbers in ``build_insights()`` — it
    cannot touch documents, users or settings, and it never fabricates data
    that is not present in the snapshot.
    """
    q = (question or "").lower()
    if any(w in q for w in ("revenue", "payment", "razorpay", "order", "money",
                            "paid", "rupee", "inr", "sales", "earning")):
        answer = _payments_answer(data)
    elif any(w in q for w in ("login", "sign in", "sign-in", "signin", "session",
                              "active user", "online")):
        answer = _logins_answer(data)
    elif any(w in q for w in ("upload", "file", "document", "vault", "storage",
                              "space", "byte", "gb")):
        answer = _documents_answer(data)
    elif any(w in q for w in ("share", "link")):
        answer = _shares_answer(data)
    elif any(w in q for w in ("group", "cohort", "chat", "message")):
        answer = _groups_answer(data)
    elif any(w in q for w in ("security", "attack", "failure", "threat", "denied",
                              "suspicious", "rate limit")):
        answer = _security_answer(data)
    elif any(w in q for w in ("trend", "growth", "week", "over time", "daily",
                              "last 14", "graph")):
        answer = _trend_answer(data)
    elif any(w in q for w in ("user", "account", "member", "role", "student",
                              "faculty", "recruiter", "how many people")):
        answer = _users_answer(data)
    else:
        answer = _overview_answer(data)

    facts = [
        f"{data['users']['total']} accounts · {data['users']['logged_in']} signed in",
        f"{data['documents']['total']} documents · {_fmt_bytes(data['documents']['storage_bytes'])}",
        f"{data['payments']['paid']} paid orders · {_inr(data['payments']['revenue_inr'])}",
        f"{data['sessions']['active']} active sessions",
    ]
    return {
        "question": question,
        "answer": answer,
        "facts": facts,
        "suggestions": _SUGGESTIONS,
        "model_mode": "grounded-analytics",
        "generated_at": data["generated_at"],
    }


@route("POST", "/admin/intelligence", roles=ADMIN)
def admin_intelligence(req: RequestContext) -> dict:
    """Administration assistant: answers questions about platform analytics."""
    actor = req.require_auth()
    question = str(req.body.get("question", "")).strip()[:500]
    if not question:
        raise invalid_input("Please enter a question.")
    data = build_insights()
    result = answer_question(question, data)
    result["metrics"] = data
    audit.write_event(
        actor_id=actor["user_id"], actor_role=actor["role"],
        event_type="ai_query", resource_type="admin_analytics",
        request_id=req.request_id, metadata={"scope": "administration"},
    )
    return result
