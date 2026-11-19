import hmac
import os
import secrets
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    count_users,
    create_report as db_create_report,
    delete_event as db_delete_event,
    delete_group as db_delete_group,
    get_current_user,
    get_db,
    get_user_by_email,
    init_db,
    insert_event,
    insert_group,
    insert_group_message,
    join_group as join_group_record,
    list_admin_events,
    list_admin_reports,
    list_admin_users,
    list_events,
    list_group_messages,
    list_groups,
    public_user,
    register_user,
    toggle_event_rsvp as toggle_event_rsvp_record,
    update_event_status,
    update_group_status,
    update_report as update_report_record,
    update_user_account,
)


BASE_DIR = Path(__file__).resolve().parent
CATEGORIES = {
    "Tech & AI",
    "Arts & Culture",
    "Sports",
    "Academic",
    "Career & Professional Development",
    "Clubs & Organizations",
    "Community Service",
    "Health & Wellness",
    "Social & Entertainment",
}
ALLOWED_ORIGINS = {
    "http://127.0.0.1:5500",
    "http://localhost:5500",
}


def create_app(test_config=None):
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key and os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("Set SECRET_KEY before running in production.")
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=secret_key or secrets.token_hex(32),
        DATABASE=os.environ.get("DATABASE_PATH", str(BASE_DIR / "instance" / "rendezvous.sqlite3")),
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
    def allow_configured_origin(response):
        origin = request.headers.get("Origin")
        if request.path.startswith("/api/") and origin in ALLOWED_ORIGINS:
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
        user_count = count_users()
        return jsonify({
            "csrf_token": session["csrf_token"],
            "setup_required": user_count == 0,
            "user": public_user(user) if user is not None and user["status"] == "active" else None,
        })

    @app.get("/healthz")
    def health():
        return jsonify({"status": "ok"})

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

        user = register_user(name, email, generate_password_hash(password))
        if user is None:
            return api_error("An account with that email already exists.", 409)
        establish_session(user["id"])
        return jsonify({"user": public_user(user)}), 201

    def authenticate_user(admin_only=False):
        payload = json_payload()
        if payload is None:
            return api_error("Send your email and password as JSON.", 400)
        email = clean_text(payload.get("email"), 254).lower()
        password = payload.get("password")
        user = get_user_by_email(email)
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
        return jsonify(list_events(
            g.current_user["id"],
            include_unapproved=g.current_user["role"] == "admin",
        ))

    @app.post("/api/events")
    @login_required
    def create_event():
        payload = json_payload()
        event_data = valid_event(payload)
        if event_data is None:
            return api_error("Provide a title, valid category, date and time, and location.", 400)
        status_value = "approved" if g.current_user["role"] == "admin" else "pending"
        event_id = insert_event(event_data, g.current_user["id"], status_value)
        return jsonify({"id": event_id, "status": status_value}), 201

    @app.post("/api/events/<int:event_id>/rsvp")
    @login_required
    def toggle_rsvp(event_id):
        joined = toggle_event_rsvp_record(event_id, g.current_user["id"])
        if joined is None:
            return api_error("That event is not available.", 404)
        return jsonify({"joined": joined})

    @app.get("/api/groups")
    @login_required
    def groups():
        return jsonify(list_groups(
            g.current_user["id"],
            is_admin=g.current_user["role"] == "admin",
        ))

    @app.post("/api/groups")
    @login_required
    def request_group():
        payload = json_payload()
        group_data = valid_group(payload)
        if group_data is None:
            return api_error("Provide a group name, valid category, and description.", 400)
        group_id = insert_group(group_data, g.current_user["id"], "pending")
        return jsonify({"id": group_id, "status": "pending"}), 201

    @app.post("/api/groups/<int:group_id>/join")
    @login_required
    def join_group(group_id):
        if not join_group_record(group_id, g.current_user["id"]):
            return api_error("That group is not available to join.", 404)
        return jsonify({"joined": True})

    @app.get("/api/groups/<int:group_id>/messages")
    @login_required
    def group_messages(group_id):
        messages = list_group_messages(group_id, g.current_user["id"])
        if messages is None:
            return api_error("Join this group to view its chat.", 403)
        return jsonify(messages)

    @app.post("/api/groups/<int:group_id>/messages")
    @login_required
    def send_group_message(group_id):
        payload = json_payload()
        content = clean_text(payload.get("content"), 2000) if payload else ""
        if not content:
            return api_error("Write a message before sending it.", 400)
        message_id = insert_group_message(group_id, g.current_user["id"], content)
        if message_id is None:
            return api_error("Join this group to send messages.", 403)
        return jsonify({"id": message_id}), 201

    @app.get("/api/admin/users")
    @admin_required
    def admin_users():
        return jsonify(list_admin_users())

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

        result = update_user_account(
            user_id,
            g.current_user["id"],
            status_value,
            role_value,
        )
        if result == "not_found":
            return api_error("User not found.", 404)
        if result == "self_change":
            return api_error("You cannot disable or demote your own administrator account.", 400)
        if result == "admin_limit":
            return api_error("This app allows a maximum of 3 administrator accounts.", 400)
        if result == "last_admin":
            return api_error("At least one active administrator must remain.", 400)
        return jsonify({"ok": True})

    @app.get("/api/admin/events")
    @admin_required
    def admin_events():
        return jsonify(list_admin_events())

    @app.patch("/api/admin/events/<int:event_id>")
    @admin_required
    def update_event(event_id):
        payload = json_payload()
        status_value = payload.get("status") if payload else None
        if status_value not in {"pending", "approved", "rejected"}:
            return api_error("Choose pending, approved, or rejected.", 400)
        if not update_event_status(event_id, status_value):
            return api_error("Event not found.", 404)
        return jsonify({"ok": True})

    @app.delete("/api/admin/events/<int:event_id>")
    @admin_required
    def delete_event(event_id):
        if not db_delete_event(event_id):
            return api_error("Event not found.", 404)
        return jsonify({"ok": True})

    @app.post("/api/admin/groups")
    @admin_required
    def create_group():
        payload = json_payload()
        group_data = valid_group(payload)
        if group_data is None:
            return api_error("Provide a group name, valid category, and description.", 400)
        group_id = insert_group(group_data, g.current_user["id"], "approved")
        return jsonify({"id": group_id, "status": "approved"}), 201

    @app.patch("/api/admin/groups/<int:group_id>")
    @admin_required
    def update_group(group_id):
        payload = json_payload()
        status_value = payload.get("status") if payload else None
        if status_value not in {"pending", "approved", "rejected"}:
            return api_error("Choose pending, approved, or rejected.", 400)
        if not update_group_status(group_id, status_value):
            return api_error("Group not found.", 404)
        return jsonify({"ok": True})

    @app.delete("/api/admin/groups/<int:group_id>")
    @admin_required
    def delete_group(group_id):
        if not db_delete_group(group_id):
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
        if not db_create_report(g.current_user["id"], target_id, reason):
            return api_error("Event not found.", 404)
        return jsonify({"ok": True}), 201

    @app.get("/api/admin/reports")
    @admin_required
    def admin_reports():
        return jsonify(list_admin_reports())

    @app.patch("/api/admin/reports/<int:report_id>")
    @admin_required
    def update_report(report_id):
        payload = json_payload()
        status_value = payload.get("status") if payload else None
        if status_value not in {"open", "resolved", "dismissed"}:
            return api_error("Choose open, resolved, or dismissed.", 400)
        if not update_report_record(report_id, status_value, g.current_user["id"]):
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


def valid_group(payload):
    if not isinstance(payload, dict):
        return None
    name = clean_text(payload.get("name"), 100)
    category = clean_text(payload.get("category"), 40)
    description = clean_text(payload.get("description"), 500)
    if not name or category not in CATEGORIES or not description:
        return None
    return name, category, description


def json_payload():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def api_error(message, status_code):
    return jsonify({"error": message}), status_code


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5500")), debug=False)
