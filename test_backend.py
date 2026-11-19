import tempfile
import unittest
from pathlib import Path

from backend import create_app


def response_json(response):
    payload = response.get_json()
    if payload is None:
        raise AssertionError("Response did not contain JSON.")
    return payload


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-key-not-for-production",
            "DATABASE": str(Path(self.temp_dir.name) / "test.sqlite3"),
        })
        self.client = self.app.test_client()
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def request_json(self, method, path, body=None):
        return self.client.open(
            path,
            method=method,
            json=body,
            headers={"X-CSRF-Token": self.csrf},
        )

    def create_account(self, name, email, password="correct-horse-battery-42"):
        response = self.request_json(
            "POST",
            "/api/auth/register",
            {"name": name, "email": email, "password": password},
        )
        self.assertEqual(response.status_code, 201, response_json(response))
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        return response_json(response)["user"]

    def login_as(self, email):
        self.request_json("POST", "/api/auth/logout")
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        response = self.request_json("POST", "/api/auth/login", {
            "email": email,
            "password": "correct-horse-battery-42",
        })
        self.assertEqual(response.status_code, 200, response_json(response))
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]

    def test_first_account_is_admin_and_database_starts_empty(self):
        status = response_json(self.client.get("/api/status"))
        self.assertTrue(status["setup_required"])
        admin = self.create_account("First Admin", "admin@example.test")
        self.assertEqual(admin["role"], "admin")
        self.assertFalse(response_json(self.client.get("/api/status"))["setup_required"])
        self.assertEqual(response_json(self.client.get("/api/events")), [])
        self.assertEqual(response_json(self.client.get("/api/groups")), [])
        self.assertEqual(response_json(self.client.get("/api/admin/users"))[0]["email"], "admin@example.test")

    def test_later_accounts_are_members_and_admin_routes_are_protected(self):
        self.create_account("First Admin", "admin@example.test")
        member = self.create_account("Campus Member", "member@example.test")
        self.assertEqual(member["role"], "user")
        self.request_json("POST", "/api/auth/logout")
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        login = self.request_json("POST", "/api/auth/login", {
            "email": "member@example.test",
            "password": "correct-horse-battery-42",
        })
        self.assertEqual(login.status_code, 200, response_json(login))
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        self.assertEqual(response_json(self.client.get("/api/status"))["user"]["id"], member["id"])
        event = self.request_json("POST", "/api/events", {
            "title": "Member Meetup",
            "category": "Career & Professional Development",
            "starts_at": "2027-05-01T10:00",
            "location": "Main Hall",
            "description": "",
        })
        self.assertEqual(event.status_code, 201, response_json(event))
        event_id = response_json(event)["id"]
        self.assertEqual(response_json(event)["status"], "pending")
        available_events = response_json(self.client.get("/api/events"))
        self.assertEqual(available_events, [])
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)

        self.login_as("admin@example.test")
        pending_events = response_json(self.client.get("/api/admin/events"))
        self.assertEqual(len(pending_events), 1)
        self.assertEqual(pending_events[0]["status"], "pending")
        self.assertEqual(
            self.request_json("PATCH", f"/api/admin/events/{event_id}", {"status": "approved"}).status_code,
            200,
        )
        approved_events = response_json(self.client.get("/api/events"))
        self.assertEqual(len(approved_events), 1)
        self.assertEqual(approved_events[0]["category"], "Career & Professional Development")

    def test_admin_can_create_manage_and_remove_campus_content(self):
        admin = self.create_account("First Admin", "admin@example.test")
        event = self.request_json("POST", "/api/events", {
            "title": "Campus Meetup",
            "category": "Health & Wellness",
            "starts_at": "2027-05-01T10:00",
            "location": "Main Hall",
            "description": "A campus meetup",
        })
        self.assertEqual(event.status_code, 201, response_json(event))
        event_id = response_json(event)["id"]
        self.assertEqual(response_json(self.client.get("/api/events"))[0]["status"], "approved")

        group = self.request_json("POST", "/api/admin/groups", {
            "name": "Reading Group",
            "category": "Academic",
            "description": "Read and discuss together.",
        })
        self.assertEqual(group.status_code, 201, response_json(group))
        self.assertEqual(len(response_json(self.client.get("/api/groups"))), 1)

        report = self.request_json("POST", "/api/reports", {
            "target_type": "event",
            "target_id": event_id,
            "reason": "Needs review",
        })
        self.assertEqual(report.status_code, 201, response_json(report))
        reports = response_json(self.client.get("/api/admin/reports"))
        self.assertEqual(reports[0]["reporter_name"], admin["name"])
        self.assertEqual(self.request_json("PATCH", f"/api/admin/reports/{reports[0]['id']}", {
            "status": "resolved",
        }).status_code, 200)

        self.assertEqual(self.request_json("PATCH", f"/api/admin/events/{event_id}", {
            "status": "rejected",
        }).status_code, 200)
        self.assertEqual(response_json(self.client.get("/api/events"))[0]["status"], "rejected")
        self.assertEqual(self.request_json("DELETE", f"/api/admin/events/{event_id}").status_code, 200)
        self.assertEqual(response_json(self.client.get("/api/events")), [])
        group_id = response_json(group)["id"]
        self.assertEqual(self.request_json("DELETE", f"/api/admin/groups/{group_id}").status_code, 200)

    def test_member_group_request_requires_admin_approval_before_join_and_chat(self):
        self.create_account("First Admin", "admin@example.test")
        self.create_account("Campus Member", "member@example.test")
        requester = self.create_account("Group Creator", "creator@example.test")

        request = self.request_json("POST", "/api/groups", {
            "name": "Design Circle",
            "category": "Clubs & Organizations",
            "description": "Share creative work.",
        })
        self.assertEqual(request.status_code, 201, response_json(request))
        group_id = response_json(request)["id"]
        self.assertEqual(response_json(request)["status"], "pending")
        own_group = response_json(self.client.get("/api/groups"))[0]
        self.assertEqual(own_group["status"], "pending")
        self.assertEqual(own_group["category"], "Clubs & Organizations")
        self.assertEqual(
            self.request_json("POST", f"/api/groups/{group_id}/join").status_code,
            404,
        )
        self.assertEqual(
            self.request_json("PATCH", f"/api/admin/groups/{group_id}", {"status": "approved"}).status_code,
            403,
        )

        self.login_as("admin@example.test")
        self.assertEqual(
            self.request_json("PATCH", f"/api/admin/groups/{group_id}", {"status": "approved"}).status_code,
            200,
        )
        self.login_as("creator@example.test")
        approved_group = response_json(self.client.get("/api/groups"))[0]
        self.assertEqual(approved_group["status"], "approved")
        self.assertIs(approved_group["is_joined"], False)
        self.assertEqual(
            self.request_json("POST", f"/api/groups/{group_id}/join").status_code,
            200,
        )
        self.assertIs(response_json(self.client.get("/api/groups"))[0]["is_joined"], True)
        message = self.request_json("POST", f"/api/groups/{group_id}/messages", {
            "content": "Hello, everyone!",
        })
        self.assertEqual(message.status_code, 201, response_json(message))
        messages = response_json(self.client.get(f"/api/groups/{group_id}/messages"))
        self.assertEqual(messages[0]["sender_name"], requester["name"])
        self.assertEqual(messages[0]["content"], "Hello, everyone!")

        self.login_as("member@example.test")
        self.assertEqual(
            self.client.get(f"/api/groups/{group_id}/messages").status_code,
            403,
        )
        self.assertEqual(response_json(self.client.get("/api/groups"))[0]["status"], "approved")
        self.assertEqual(
            self.request_json("POST", f"/api/groups/{group_id}/messages", {"content": "Not a member"}).status_code,
            403,
        )

    def test_csrf_and_password_validation(self):
        missing_token = self.client.post("/api/auth/register", json={
            "name": "First Admin",
            "email": "admin@example.test",
            "password": "short",
        })
        self.assertEqual(missing_token.status_code, 400)
        invalid_password = self.request_json("POST", "/api/auth/register", {
            "name": "First Admin",
            "email": "admin@example.test",
            "password": "short",
        })
        self.assertEqual(invalid_password.status_code, 400)

    def test_admin_panel_files_are_served_separately(self):
        admin_page = self.client.get("/admin")
        self.assertIn("admin.js", admin_page.get_data(as_text=True))
        admin_page.close()
        for path in ("/admin.js", "/admin.css"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_local_and_render_origins_can_call_api_but_other_origins_cannot(self):
        for origin in ("http://127.0.0.1:5500",):
            preflight = self.client.options("/api/auth/login", headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-csrf-token",
            })
            self.assertEqual(preflight.headers.get("Access-Control-Allow-Origin"), origin)
            self.assertEqual(preflight.headers.get("Access-Control-Allow-Credentials"), "true")
            preflight.close()

        for origin in ("http://example.test", "https://rdv-1-0.onrender.com"):
            rejected = self.client.get("/api/status", headers={"Origin": origin})
            self.assertIsNone(rejected.headers.get("Access-Control-Allow-Origin"))
            rejected.close()

    def test_multiple_admin_accounts_can_use_admin_login(self):
        first_admin = self.create_account("First Admin", "admin@example.test")
        member = self.create_account("Second Admin", "second@example.test")
        self.request_json("POST", "/api/auth/logout")
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]

        rejected_member = self.request_json("POST", "/api/auth/admin-login", {
            "email": member["email"],
            "password": "correct-horse-battery-42",
        })
        self.assertEqual(rejected_member.status_code, 401)

        admin_login = self.request_json("POST", "/api/auth/admin-login", {
            "email": first_admin["email"],
            "password": "correct-horse-battery-42",
        })
        self.assertEqual(admin_login.status_code, 200, response_json(admin_login))
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        promotion = self.request_json("PATCH", f"/api/admin/users/{member['id']}", {"role": "admin"})
        self.assertEqual(promotion.status_code, 200, response_json(promotion))

        self.request_json("POST", "/api/auth/logout")
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        second_admin_login = self.request_json("POST", "/api/auth/admin-login", {
            "email": member["email"],
            "password": "correct-horse-battery-42",
        })
        self.assertEqual(second_admin_login.status_code, 200, response_json(second_admin_login))
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        demotion = self.request_json("PATCH", f"/api/admin/users/{first_admin['id']}", {"role": "user"})
        self.assertEqual(demotion.status_code, 200, response_json(demotion))
        self.assertEqual(self.request_json("PATCH", f"/api/admin/users/{member['id']}", {
            "role": "user",
        }).status_code, 400)

    def test_admin_role_cannot_be_promoted_above_three_accounts(self):
        first_admin = self.create_account("First Admin", "admin@example.test")
        members = [
            self.create_account(f"Member {number}", f"member{number}@example.test")
            for number in range(1, 4)
        ]
        self.request_json("POST", "/api/auth/logout")
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        login = self.request_json("POST", "/api/auth/login", {
            "email": first_admin["email"],
            "password": "correct-horse-battery-42",
        })
        self.assertEqual(login.status_code, 200, response_json(login))
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]

        for member in members[:2]:
            response = self.request_json("PATCH", f"/api/admin/users/{member['id']}", {"role": "admin"})
            self.assertEqual(response.status_code, 200, response_json(response))
        last_promotion = self.request_json(
            "PATCH",
            f"/api/admin/users/{members[2]['id']}",
            {"role": "admin"},
        )
        self.assertEqual(last_promotion.status_code, 400)
        self.assertEqual(
            len([user for user in response_json(self.client.get("/api/admin/users")) if user["role"] == "admin"]),
            3,
        )

    def test_disabled_member_cannot_sign_in_and_admin_cannot_disable_self(self):
        admin = self.create_account("First Admin", "admin@example.test")
        member = self.create_account("Campus Member", "member@example.test")
        self.request_json("POST", "/api/auth/logout")
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        self.request_json("POST", "/api/auth/login", {
            "email": "admin@example.test",
            "password": "correct-horse-battery-42",
        })
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        self.assertEqual(self.request_json("PATCH", f"/api/admin/users/{admin['id']}", {
            "status": "disabled",
        }).status_code, 400)
        self.assertEqual(self.request_json("PATCH", f"/api/admin/users/{member['id']}", {
            "status": "disabled",
        }).status_code, 200)
        self.request_json("POST", "/api/auth/logout")
        self.csrf = response_json(self.client.get("/api/status"))["csrf_token"]
        login = self.request_json("POST", "/api/auth/login", {
            "email": "member@example.test",
            "password": "correct-horse-battery-42",
        })
        self.assertEqual(login.status_code, 403)


if __name__ == "__main__":
    unittest.main()
