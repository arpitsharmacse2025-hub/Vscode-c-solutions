# Campus Lost & Found — Global Web Version

This is the web conversion of the original Tkinter/SQLite mini-project. It runs as a Flask website and is deployment-ready for services such as Render, Railway, or a VPS.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open `http://127.0.0.1:5000`.

Demo admin: `admin@campus.local` / `admin123`

## Deploy on Render
1. Create a GitHub repository and upload this folder.
2. On Render, create a **Web Service** from that repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add environment variable `SECRET_KEY` to a long random value.
6. Deploy. Render gives you a public `onrender.com` URL.

### Database note
This version keeps SQLite to stay beginner-friendly and preserve the original project. Some cloud hosts have an ephemeral filesystem, so data can be lost on redeploy/restart. For a real long-term campus deployment, move the database to PostgreSQL and set up persistent storage/backups.
