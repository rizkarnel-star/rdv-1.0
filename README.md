# Rendezvous

A campus community app built with HTML, CSS, vanilla JavaScript, Python Flask, and SQLite. New users can create accounts, sign in, submit events, RSVP, and report events. Administrators can manage accounts, review events, create groups, and resolve reports.

## Run locally

1. Open this folder in Visual Studio Code.
2. In the terminal, create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install the app dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Start the Flask API server in the VS Code terminal:

   ```powershell
   python backend.py
   ```

5. In VS Code, click **Go Live** to start Live Server on port 5500, then open `http://127.0.0.1:5500`.

Live Server serves the HTML/CSS/JavaScript on port 5500. Flask must remain running on port 8000 because it provides login, database, and admin APIs. The app allows this local Live Server origin only. The Flask server listens on the local computer only.

The first account created becomes the administrator; later accounts are regular members. Use a password with at least 12 characters. The database is created at `instance/rendezvous.sqlite3`.

The app starts with no sample users, events, or groups. Administrators can add campus groups in the Admin panel. Members can submit events, which remain pending until an administrator approves them.

## Admin features

- View accounts and disable or re-enable regular member accounts.
- Review, approve, reject, or delete events.
- Create and delete campus groups.
- Review event reports and mark them open, resolved, or dismissed.
- Promote existing member accounts to administrator so multiple administrators can sign in.
- A maximum of three accounts can have the administrator role.

The administrator setup is intentionally a first-run flow for local development. Do not expose a fresh deployment to the internet before creating the first administrator: otherwise, the first person to register could claim the administrator role.
Administrators use the **Administrator? Sign in here** option on the login screen and sign in with their own account password. Do not use a shared default administrator password; create individual accounts and promote trusted members from the Admin panel.

## Production note

This project is suitable as a local learning app, not as a deployment-ready public service. Before deploying it, set a private, persistent `SECRET_KEY`, enable HTTPS, configure secure cookie and host settings, add login rate limiting and operational monitoring, and use managed database backups. Do not commit secrets or the generated SQLite database.

In PowerShell, generate a key for a local run with:

```powershell
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
python backend.py
```

## Project files

- `index.html` — account forms and main app pages.
- `style.css` — responsive layout and component styles.
- `script.js` — browser interactions and API requests.
- `admin.html`, `admin.css`, and `admin.js` — the standalone administrator page and its interface.
- `backend.py` — Flask routes, authentication, authorization, and CSRF checks.
- `database.py` — SQLite connection, schema initialization, and shared database row helpers.
- `instance/rendezvous.sqlite3` — the SQLite data file created on first run.
- `test_backend.py` — focused API and access-control tests.
- `requirements.txt` — Python package dependencies.

After signing in as an administrator, use the **Admin** link to open `/admin`. The dashboard is separate from the main app page; its API remains protected by administrator authorization.

Run the backend tests with:

```powershell
python -m unittest
```
