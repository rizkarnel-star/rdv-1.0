import sqlite3

from flask import current_app, g, session


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_by INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS event_rsvps (
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (event_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            created_by INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'approved' CHECK (status IN ('pending', 'approved', 'rejected')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY,
            reporter_id INTEGER NOT NULL REFERENCES users(id),
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
            reviewed_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    group_columns = {row["name"] for row in db.execute("PRAGMA table_info(groups)")}
    if "status" not in group_columns:
        db.execute(
            "ALTER TABLE groups ADD COLUMN status TEXT NOT NULL DEFAULT 'approved' "
            "CHECK (status IN ('pending', 'approved', 'rejected'))"
        )
    db.commit()


def get_current_user():
    user_id = session.get("user_id")
    return get_user(user_id) if user_id else None


def get_user(user_id):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def public_user(user):
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "status": user["status"],
    }


def event_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "starts_at": row["starts_at"],
        "location": row["location"],
        "description": row["description"],
        "creator_name": row["creator_name"],
        "status": row["status"],
        "attendee_count": row["attendee_count"],
        "is_joined": bool(row["is_joined"]),
    }


def count_users():
    return get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]


def register_user(name, email, password_hash):
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        db.rollback()
        return None
    role = "admin" if count_users() == 0 else "user"
    cursor = db.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (name, email, password_hash, role),
    )
    db.commit()
    return get_user(cursor.lastrowid)


def get_user_by_email(email):
    return get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def list_events(user_id, include_unapproved=False):
    query = (
        "SELECT e.*, u.name AS creator_name, COUNT(DISTINCT r.user_id) AS attendee_count, "
        "MAX(CASE WHEN r.user_id = ? THEN 1 ELSE 0 END) AS is_joined "
        "FROM events e JOIN users u ON u.id = e.created_by "
        "LEFT JOIN event_rsvps r ON r.event_id = e.id "
    )
    if not include_unapproved:
        query += "WHERE e.status = 'approved' "
    query += "GROUP BY e.id ORDER BY e.starts_at"
    rows = get_db().execute(query, (user_id,)).fetchall()
    return [event_dict(row) for row in rows]


def insert_event(event_data, user_id, status):
    cursor = get_db().execute(
        "INSERT INTO events (title, category, starts_at, location, description, created_by, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (*event_data, user_id, status),
    )
    get_db().commit()
    return cursor.lastrowid


def toggle_event_rsvp(event_id, user_id):
    db = get_db()
    if db.execute(
        "SELECT 1 FROM events WHERE id = ? AND status = 'approved'", (event_id,)
    ).fetchone() is None:
        return None
    existing = db.execute(
        "SELECT 1 FROM event_rsvps WHERE event_id = ? AND user_id = ?",
        (event_id, user_id),
    ).fetchone()
    if existing:
        db.execute("DELETE FROM event_rsvps WHERE event_id = ? AND user_id = ?", (event_id, user_id))
    else:
        db.execute("INSERT INTO event_rsvps (event_id, user_id) VALUES (?, ?)", (event_id, user_id))
    db.commit()
    return existing is None


def list_groups(user_id, is_admin):
    visibility = "" if is_admin else "WHERE groups.status = 'approved' OR groups.created_by = ?"
    parameters = (user_id,) if not is_admin else ()
    rows = get_db().execute(
        "SELECT groups.*, users.name AS creator_name, COUNT(DISTINCT group_members.user_id) AS member_count, "
        "MAX(CASE WHEN group_members.user_id = ? THEN 1 ELSE 0 END) AS is_joined "
        "FROM groups JOIN users ON users.id = groups.created_by "
        "LEFT JOIN group_members ON group_members.group_id = groups.id "
        f"{visibility} GROUP BY groups.id ORDER BY groups.name",
        (user_id, *parameters),
    ).fetchall()
    result = [dict(row) for row in rows]
    for group in result:
        group["is_joined"] = bool(group["is_joined"])
    return result


def insert_group(group_data, user_id, status):
    cursor = get_db().execute(
        "INSERT INTO groups (name, category, description, created_by, status) VALUES (?, ?, ?, ?, ?)",
        (*group_data, user_id, status),
    )
    get_db().commit()
    return cursor.lastrowid


def join_group(group_id, user_id):
    db = get_db()
    if db.execute(
        "SELECT 1 FROM groups WHERE id = ? AND status = 'approved'", (group_id,)
    ).fetchone() is None:
        return False
    db.execute(
        "INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)",
        (group_id, user_id),
    )
    db.commit()
    return True


def list_group_messages(group_id, user_id):
    db = get_db()
    if db.execute(
        "SELECT 1 FROM group_members JOIN groups ON groups.id = group_members.group_id "
        "WHERE group_members.group_id = ? AND group_members.user_id = ? AND groups.status = 'approved'",
        (group_id, user_id),
    ).fetchone() is None:
        return None
    rows = db.execute(
        "SELECT group_messages.id, group_messages.content, group_messages.created_at, "
        "group_messages.user_id, users.name AS sender_name "
        "FROM group_messages JOIN users ON users.id = group_messages.user_id "
        "WHERE group_messages.group_id = ? ORDER BY group_messages.id",
        (group_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def insert_group_message(group_id, user_id, content):
    db = get_db()
    if db.execute(
        "SELECT 1 FROM group_members JOIN groups ON groups.id = group_members.group_id "
        "WHERE group_members.group_id = ? AND group_members.user_id = ? AND groups.status = 'approved'",
        (group_id, user_id),
    ).fetchone() is None:
        return None
    cursor = db.execute(
        "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, ?, ?)",
        (group_id, user_id, content),
    )
    db.commit()
    return cursor.lastrowid


def list_admin_users():
    rows = get_db().execute(
        "SELECT id, name, email, role, status, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def update_user_account(user_id, current_user_id, status_value, role_value):
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    target = db.execute("SELECT role, status FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        db.rollback()
        return "not_found"
    next_status = status_value if status_value is not None else target["status"]
    next_role = role_value if role_value is not None else target["role"]
    if user_id == current_user_id and (next_status != "active" or next_role != "admin"):
        db.rollback()
        return "self_change"
    is_promoting_user = target["role"] != "admin" and next_role == "admin"
    if is_promoting_user and db.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin'"
    ).fetchone()[0] >= 3:
        db.rollback()
        return "admin_limit"
    is_removing_active_admin = (
        target["role"] == "admin"
        and target["status"] == "active"
        and (next_role != "admin" or next_status != "active")
    )
    if is_removing_active_admin and db.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
    ).fetchone()[0] <= 1:
        db.rollback()
        return "last_admin"
    db.execute("UPDATE users SET status = ?, role = ? WHERE id = ?", (next_status, next_role, user_id))
    db.commit()
    return "updated"


def list_admin_events():
    rows = get_db().execute(
        "SELECT e.*, u.name AS creator_name, COUNT(DISTINCT r.user_id) AS attendee_count, 0 AS is_joined "
        "FROM events e JOIN users u ON u.id = e.created_by "
        "LEFT JOIN event_rsvps r ON r.event_id = e.id GROUP BY e.id ORDER BY e.created_at DESC"
    ).fetchall()
    return [event_dict(row) for row in rows]


def update_event_status(event_id, status):
    db = get_db()
    cursor = db.execute("UPDATE events SET status = ? WHERE id = ?", (status, event_id))
    db.commit()
    return cursor.rowcount > 0


def delete_event(event_id):
    db = get_db()
    cursor = db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()
    return cursor.rowcount > 0


def update_group_status(group_id, status):
    db = get_db()
    cursor = db.execute("UPDATE groups SET status = ? WHERE id = ?", (status, group_id))
    db.commit()
    return cursor.rowcount > 0


def delete_group(group_id):
    db = get_db()
    cursor = db.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    db.commit()
    return cursor.rowcount > 0


def create_report(reporter_id, target_id, reason):
    db = get_db()
    if db.execute("SELECT 1 FROM events WHERE id = ?", (target_id,)).fetchone() is None:
        return False
    db.execute(
        "INSERT INTO reports (reporter_id, target_type, target_id, reason) VALUES (?, 'event', ?, ?)",
        (reporter_id, target_id, reason),
    )
    db.commit()
    return True


def list_admin_reports():
    rows = get_db().execute(
        "SELECT reports.*, users.name AS reporter_name, events.title AS event_title "
        "FROM reports JOIN users ON users.id = reports.reporter_id "
        "LEFT JOIN events ON reports.target_type = 'event' AND events.id = reports.target_id "
        "ORDER BY reports.created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def update_report(report_id, status, reviewer_id):
    db = get_db()
    cursor = db.execute(
        "UPDATE reports SET status = ?, reviewed_by = ? WHERE id = ?",
        (status, reviewer_id, report_id),
    )
    db.commit()
    return cursor.rowcount > 0
