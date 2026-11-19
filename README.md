# Rendezvous

A campus community app built with HTML, CSS, vanilla JavaScript, Python Flask, and SQLite. Members can create accounts, submit events and group requests, RSVP, report events, join approved groups, and chat with group members. Administrators manage accounts, review event and group requests, and resolve reports.

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

4. Start the Flask app in the VS Code terminal:

   ```powershell
   python backend.py
   ```

5. Open `http://127.0.0.1:5500` in your browser.

Live Server serves the HTML/CSS/JavaScript on port 5500. Flask must remain running on port 8000 because it provides login, database, and admin APIs. The API accepts the local Live Server origins only.

The first account created becomes the administrator; later accounts are regular members. Use a password with at least 12 characters. The database is created at `instance/rendezvous.sqlite3`.

The app starts with no sample users, events, or groups. Groups can be created in categories such as academics, career development, clubs, community service, health, and social activities; member-created groups remain pending until an administrator approves them. Members can join approved groups. Joined group conversations are available in the **Chats** tab. Members can select dark mode in **Settings → Appearance**; the preference is saved on the current device. Events use the same category options and are automatically approved when created.

## Admin features

- View accounts and disable or re-enable regular member accounts.
- Review, approve, reject, or delete events.
- Approve or reject member group requests, and create or delete campus groups.
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

## Deploy the backend for Vercel

Vercel is currently serving the static frontend; it does not automatically run this Flask app. One simple setup is to run the backend as a Render Web Service and proxy `/api/*` requests through Vercel.

1. Push the project to a GitHub repository. Do not include `.env`, secrets, or `instance/rendezvous.sqlite3`.
2. In Render, create a **Web Service** from that repository.
3. Use these commands:

   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn --bind 0.0.0.0:$PORT backend:app`
   - Health check path: `/healthz`

4. If keeping SQLite, attach a persistent disk mounted at `/var/data`. Set these Render environment variables:

   - `FLASK_ENV` = `production`
   - `SECRET_KEY` = a new random value (generate one locally; never paste it into chat or commit it)
   - `DATABASE_PATH` = `/var/data/rendezvous.sqlite3`

   Without persistent storage, the deployed SQLite file may be lost on redeploy or restart. The current backend supports SQLite; using PostgreSQL would require adapting `database.py`.

5. After Render deploys, use the service URL shown in its dashboard.
6. Add a `vercel.json` file at the project root and replace the example host below with that Render URL:

   ```json
   {
     "rewrites": [
       {
         "source": "/api/(.*)",
         "destination": "https://your-service.onrender.com/api/$1"
       }
     ]
   }
   ```

7. Commit and push `vercel.json`, then redeploy the Vercel frontend. The frontend calls `/api/...` on its own domain, and Vercel forwards those requests to Flask. This same-origin proxy keeps the session cookie working without opening the API to arbitrary websites.

The deployed backend starts with an empty database unless you migrate one. In this app, the first registered account becomes the administrator. Keep the deployment private until you create that account; otherwise, an outside visitor could register first.

## Project files

- `index.html` — account forms and main app pages.
- `style.css` — responsive layout and component styles.
- `script.js` — browser interactions and API requests.
- `admin.html`, `admin.css`, and `admin.js` — the standalone administrator page and its interface.
- `backend.py` — Flask routes, authentication, authorization, and CSRF checks.
- `database.py` — SQLite connection, schema initialization/migrations, and all database queries and write operations.
- `instance/rendezvous.sqlite3` — the SQLite data file created on first run.
- `test_backend.py` — focused API and access-control tests.
- `requirements.txt` — Python package dependencies.

After signing in as an administrator, use the **Admin** link to open `/admin`. The dashboard is separate from the main app page; its API remains protected by administrator authorization.

Run the backend tests with:

```powershell
python -m unittest
```
