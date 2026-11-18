import hmac
import os
import secrets
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from database import event_dict, get_current_user, get_db, get_user, init_db, public_user


BASE_DIR = Path(__file__).resolve().parent
CATEGORIES = {"Tech & AI", "Arts & Culture", "Sports", "Academic"}


def create_app(test_config=None):
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key and os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("Set SECRET_KEY before running in production.")
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=secret_key or secrets.token_hex(32),
        DATABASE=str(BASE_DIR / "instance" / "rendezvous.sqlite3"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    @app.teardown_appcontext
    def close_db(_error=None):
        _ = _error
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with app.app_context():
        init_db()

    @app.before_request
    def enforce_csrf():
        if request.path.startswith("/api/") and request.method in {"POST", "PATCH", "DELETE"}:
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                return api_error("Invalid or expired request token. Refresh and try again.", 400)

    @app.after_request
    def allow_live_server_origin(response):
        origin = request.headers.get("Origin")
        allowed_origins = {"http://127.0.0.1:5500", "http://localhost:5500"}
        if request.path.startswith("/api/") and origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRF-Token"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            response.headers["Vary"] = "Origin"
        return response

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if user is None or user["status"] != "active":
                return api_error("Please sign in to continue.", 401)
            g.current_user = user
            return view(*args, **kwargs)
        return wrapped

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.current_user["role"] != "admin":
                return api_error("Administrator access is required.", 403)
            return view(*args, **kwargs)
        return wrapped

    @app.get("/")
    def index():
        return send_from_directory(BASE_DIR, "index.html")

    @app.get("/style.css")
    def stylesheet():
        return send_from_directory(BASE_DIR, "style.css")

    @app.get("/admin")
    def admin_page():
        return send_from_directory(BASE_DIR, "admin.html")

    @app.get("/admin.html")
    def admin_html_file():
        return send_from_directory(BASE_DIR, "admin.html")

    @app.get("/admin.css")
    def admin_stylesheet():
        return send_from_directory(BASE_DIR, "admin.css")

    @app.get("/admin.js")
    def admin_javascript():
        return send_from_directory(BASE_DIR, "admin.js")

    @app.get("/script.js")
    def javascript():
        return send_from_directory(BASE_DIR, "script.js")

    @app.get("/api/status")
    def status():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        user = get_current_user()
        user_count = get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return jsonify({
            "csrf_token": session["csrf_token"],
            "setup_required": user_count == 0,
            "user": public_user(user) if user is not None and user["status"] == "active" else None,
        })

    @app.post("/api/auth/register")
    def register():
        payload = json_payload()
        if payload is None:
            return api_error("Send account details as JSON.", 400)
        name = clean_text(payload.get("name"), 100)
        email = clean_text(payload.get("email"), 254).lower()
        password = payload.get("password")
        if not name or not email or "@" not in email or not isinstance(password, str) or len(password) < 12:
            return api_error("Enter your name, a valid email address, and a password of at least 12 characters.", 400)

        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            db.rollback()
            return api_error("An account with that email already exists.", 409)
        role = "admin" if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 else "user"
        cursor = db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, generate_password_hash(password), role),
        )
        db.commit()
        user = get_user(cursor.lastrowid)
        establish_session(user["id"])
        return jsonify({"user": public_user(user)}), 201

    def authenticate_user(admin_only=False):
        payload = json_payload()
        if payload is None:
            return api_error("Send your email and password as JSON.", 400)
        email = clean_text(payload.get("email"), 254).lower()
        password = payload.get("password")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if (
            user is None
            or not isinstance(password, str)
            or not check_password_hash(user["password_hash"], password)
            or (admin_only and user["role"] != "admin")
        ):
            return api_error("Email or password is incorrect.", 401)
        if user["status"] != "active":
            return api_error("This account is disabled. Contact an administrator.", 403)
        establish_session(user["id"])
        return jsonify({"user": public_user(user)})

    @app.post("/api/auth/login")
    def login():
        return authenticate_user()

    @app.post("/api/auth/admin-login")
    def admin_login():
        return authenticate_user(admin_only=True)

    @app.post("/api/auth/logout")
    @login_required
    def logout():
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/events")
    @login_required
    def events():
        if g.current_user["role"] == "admin":
            rows = get_db().execute(
                "SELECT e.*, u.name AS creator_name, COUNT(DISTINCT r.user_id) AS attendee_count, "
                "MAX(CASE WHEN r.user_id = ? THEN 1 ELSE 0 END) AS is_joined "
                "FROM events e JOIN users u ON u.id = e.created_by "
                "LEFT JOIN event_rsvps r ON r.event_id = e.id GROUP BY e.id ORDER BY e.starts_at",
                (g.current_user["id"],),
            ).fetchall()
        else:
            rows = get_db().execute(
                "SELECT e.*, u.name AS creator_name, COUNT(DISTINCT r.user_id) AS attendee_count, "
                "MAX(CASE WHEN r.user_id = ? THEN 1 ELSE 0 END) AS is_joined "
                "FROM events e JOIN users u ON u.id = e.created_by "
                "LEFT JOIN event_rsvps r ON r.event_id = e.id "
                "WHERE e.status = 'approved' GROUP BY e.id ORDER BY e.starts_at",
                (g.current_user["id"],),
            ).fetchall()
        return jsonify([event_dict(row) for row in rows])

    @app.post("/api/events")
    @login_required
    def create_event():
        payload = json_payload()
        event_data = valid_event(payload)
        if event_data is None:
            return api_error("Provide a title, valid category, date and time, and location.", 400)
        status_value = "approved" if g.current_user["role"] == "admin" else "pending"
        cursor = get_db().execute(
            "INSERT INTO events (title, category, starts_at, location, description, created_by, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (*event_data, g.current_user["id"], status_value),
        )
        get_db().commit()
        return jsonify({"id": cursor.lastrowid, "status": status_value}), 201

    @app.post("/api/events/<int:event_id>/rsvp")
    @login_required
    def toggle_rsvp(event_id):
        db = get_db()
        if db.execute("SELECT 1 FROM events WHERE id = ? AND status = 'approved'", (event_id,)).fetchone() is None:
            return api_error("That event is not available.", 404)
        existing = db.execute(
            "SELECT 1 FROM event_rsvps WHERE event_id = ? AND user_id = ?",
            (event_id, g.current_user["id"]),
        ).fetchone()
        if existing:
            db.execute("DELETE FROM event_rsvps WHERE event_id = ? AND user_id = ?", (event_id, g.current_user["id"]))
        else:
            db.execute("INSERT INTO event_rsvps (event_id, user_id) VALUES (?, ?)", (event_id, g.current_user["id"]))
        db.commit()
        return jsonify({"joined": existing is None})

    @app.get("/api/groups")
    @login_required
    def groups():
        rows = get_db().execute(
            "SELECT groups.*, users.name AS creator_name FROM groups "
            "JOIN users ON users.id = groups.created_by ORDER BY groups.name"
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/api/admin/users")
    @admin_required
    def admin_users():
        rows = get_db().execute(
            "SELECT id, name, email, role, status, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.patch("/api/admin/users/<int:user_id>")
    @admin_required
    def update_user(user_id):
        payload = json_payload()
        if payload is None:
            return api_error("Send account changes as JSON.", 400)
        status_value = payload.get("status")
        role_value = payload.get("role")
        if status_value is not None and (
            not isinstance(status_value, str) or status_value not in {"active", "disabled"}
        ):
            return api_error("Choose active or disabled for the account status.", 400)
        if role_value is not None and (
            not isinstance(role_value, str) or role_value not in {"admin", "user"}
        ):
            return api_error("Choose admin or user for the account role.", 400)
        if status_value is None and role_value is None:
            return api_error("Provide a role or account status to update.", 400)

        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        target = db.execute("SELECT role, status FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            db.rollback()
            return api_error("User not found.", 404)
        next_status = status_value if status_value is not None else target["status"]
        next_role = role_value if role_value is not None else target["role"]
        if user_id == g.current_user["id"] and (next_status != "active" or next_role != "admin"):
            db.rollback()
            return api_error("You cannot disable or demote your own administrator account.", 400)
        is_promoting_user = target["role"] != "admin" and next_role == "admin"
        if is_promoting_user:
            admin_count = db.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin'"
            ).fetchone()[0]
            if admin_count >= 3:
                db.rollback()
                return api_error("This app allows a maximum of 3 administrator accounts.", 400)
        is_removing_active_admin = (
            target["role"] == "admin"
            and target["status"] == "active"
            and (next_role != "admin" or next_status != "active")
        )
        if is_removing_active_admin:
            active_admins = db.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
            ).fetchone()[0]
            if active_admins <= 1:
                db.rollback()
                return api_error("At least one active administrator must remain.", 400)
        db.execute("UPDATE users SET status = ?, role = ? WHERE id = ?", (next_status, next_role, user_id))
        db.commit()
        return jsonify({"ok": True})

    @app.get("/api/admin/events")
    @admin_required
    def admin_events():
        rows = get_db().execute(
            "SELECT e.*, u.name AS creator_name, COUNT(DISTINCT r.user_id) AS attendee_count, 0 AS is_joined "
            "FROM events e JOIN users u ON u.id = e.created_by "
            "LEFT JOIN event_rsvps r ON r.event_id = e.id GROUP BY e.id ORDER BY e.created_at DESC"
        ).fetchall()
        return jsonify([event_dict(row) for row in rows])

    @app.patch("/api/admin/events/<int:event_id>")
    @admin_required
    def update_event(event_id):
        payload = json_payload()
        status_value = payload.get("status") if payload else None
        if status_value not in {"pending", "approved", "rejected"}:
            return api_error("Choose pending, approved, or rejected.", 400)
        cursor = get_db().execute("UPDATE events SET status = ? WHERE id = ?", (status_value, event_id))
        get_db().commit()
        if cursor.rowcount == 0:
            return api_error("Event not found.", 404)
        return jsonify({"ok": True})

    @app.delete("/api/admin/events/<int:event_id>")
    @admin_required
    def delete_event(event_id):
        cursor = get_db().execute("DELETE FROM events WHERE id = ?", (event_id,))
        get_db().commit()
        if cursor.rowcount == 0:
            return api_error("Event not found.", 404)
        return jsonify({"ok": True})

    @app.post("/api/admin/groups")
    @admin_required
    def create_group():
        payload = json_payload()
        if payload is None:
            return api_error("Send group details as JSON.", 400)
        name = clean_text(payload.get("name"), 100)
        category = clean_text(payload.get("category"), 40)
        description = clean_text(payload.get("description"), 500)
        if not name or category not in CATEGORIES or not description:
            return api_error("Provide a group name, valid category, and description.", 400)
        cursor = get_db().execute(
            "INSERT INTO groups (name, category, description, created_by) VALUES (?, ?, ?, ?)",
            (name, category, description, g.current_user["id"]),
        )
        get_db().commit()
        return jsonify({"id": cursor.lastrowid}), 201

    @app.delete("/api/admin/groups/<int:group_id>")
    @admin_required
    def delete_group(group_id):
        cursor = get_db().execute("DELETE FROM groups WHERE id = ?", (group_id,))
        get_db().commit()
        if cursor.rowcount == 0:
            return api_error("Group not found.", 404)
        return jsonify({"ok": True})

    @app.post("/api/reports")
    @login_required
    def create_report():
        payload = json_payload()
        target_type = payload.get("target_type") if payload else None
        target_id = payload.get("target_id") if payload else None
        reason = clean_text(payload.get("reason"), 500) if payload else ""
        if target_type != "event" or not isinstance(target_id, int) or not reason:
            return api_error("Provide an event and a short reason for the report.", 400)
        if get_db().execute("SELECT 1 FROM events WHERE id = ?", (target_id,)).fetchone() is None:
            return api_error("Event not found.", 404)
        get_db().execute(
            "INSERT INTO reports (reporter_id, target_type, target_id, reason) VALUES (?, ?, ?, ?)",
            (g.current_user["id"], target_type, target_id, reason),
        )
        get_db().commit()
        return jsonify({"ok": True}), 201

    @app.get("/api/admin/reports")
    @admin_required
    def admin_reports():
        rows = get_db().execute(
            "SELECT reports.*, users.name AS reporter_name, events.title AS event_title "
            "FROM reports JOIN users ON users.id = reports.reporter_id "
            "LEFT JOIN events ON reports.target_type = 'event' AND events.id = reports.target_id "
            "ORDER BY reports.created_at DESC"
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.patch("/api/admin/reports/<int:report_id>")
    @admin_required
    def update_report(report_id):
        payload = json_payload()
        status_value = payload.get("status") if payload else None
        if status_value not in {"open", "resolved", "dismissed"}:
            return api_error("Choose open, resolved, or dismissed.", 400)
        cursor = get_db().execute(
            "UPDATE reports SET status = ?, reviewed_by = ? WHERE id = ?",
            (status_value, g.current_user["id"], report_id),
        )
        get_db().commit()
        if cursor.rowcount == 0:
            return api_error("Report not found.", 404)
        return jsonify({"ok": True})

    return app


def establish_session(user_id):
    session.clear()
    session["user_id"] = user_id
    session["csrf_token"] = secrets.token_urlsafe(32)


def clean_text(value, limit):
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def valid_event(payload):
    if not isinstance(payload, dict):
        return None
    title = clean_text(payload.get("title"), 120)
    category = clean_text(payload.get("category"), 40)
    starts_at = clean_text(payload.get("starts_at"), 32)
    location = clean_text(payload.get("location"), 160)
    description = clean_text(payload.get("description"), 1000)
    try:
        datetime.fromisoformat(starts_at)
    except ValueError:
        return None
    if not title or category not in CATEGORIES or not location:
        return None
    return title, category, starts_at, location, description


def json_payload():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def api_error(message, status_code):
    return jsonify({"error": message}), status_code


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), debug=False)
