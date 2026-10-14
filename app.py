"""ContentFlow: self-hosted social content review MVP."""
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('DATA_DIR', str(ROOT / 'data')))
UPLOADS = DATA / 'uploads'
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)
DB = DATA / 'contentflow.sqlite'
SECRET = os.getenv('APP_SECRET', 'local-dev-change-me')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'change-me-before-deploying')
PUBLIC_URL = os.getenv('PUBLIC_URL', os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:8000')).rstrip('/')
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '250'))
serializer = URLSafeTimedSerializer(SECRET, salt='admin-session')
app = FastAPI(title='ContentFlow', docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')

@contextmanager
def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT, token TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER NOT NULL,
            title TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '',
            publish_at TEXT, filename TEXT, original_filename TEXT,
            status TEXT NOT NULL DEFAULT 'pending', feedback TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id));
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL,
            event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', timestamp TEXT NOT NULL,
            FOREIGN KEY(post_id) REFERENCES posts(id));
        ''')
init_db()

def now(): return datetime.now(timezone.utc).isoformat()
def rowdict(row): return dict(row) if row else None

def is_admin(request: Request):
    cookie = request.cookies.get('cf_admin', '')
    try:
        return serializer.loads(cookie, max_age=60*60*24*7) == 'admin'
    except (BadSignature, SignatureExpired):
        return False

def require_admin(request: Request):
    if not is_admin(request): raise HTTPException(401, 'Please log in as admin')

def get_client(token: str):
    with db() as c:
        result = c.execute('SELECT * FROM clients WHERE token=?', (token,)).fetchone()
    if not result: raise HTTPException(404, 'Client portal not found')
    return dict(result)

def notify(to: Optional[str], subject: str, body: str):
    """Email notification optional; failure never invalidates an approval."""
    server = os.getenv('SMTP_HOST')
    if not server or not to: return 'not_configured'
    msg = EmailMessage()
    msg['Subject'], msg['To'] = subject, to
    msg['From'] = os.getenv('SMTP_FROM', 'contentflow@localhost')
    msg.set_content(body)
    try:
        with smtplib.SMTP(server, int(os.getenv('SMTP_PORT', '587')), timeout=12) as smtp:
            if os.getenv('SMTP_STARTTLS', 'true').lower() == 'true': smtp.starttls()
            user = os.getenv('SMTP_USERNAME')
            if user: smtp.login(user, os.getenv('SMTP_PASSWORD', ''))
            smtp.send_message(msg)
        return 'sent'
    except Exception as err:
        print('Notification failed:', err)
        return 'failed'

@app.get('/')
def index(): return FileResponse(ROOT / 'static' / 'index.html')

@app.get('/api/session')
def session(request: Request): return {'admin': is_admin(request)}

class Login(BaseModel): password: str
@app.post('/api/login')
def login(data: Login):
    if not hmac.compare_digest(data.password, ADMIN_PASSWORD):
        raise HTTPException(401, 'Incorrect password')
    response = RedirectResponse(url='/', status_code=303)
    response.set_cookie('cf_admin', serializer.dumps('admin'), max_age=604800,
                        httponly=True, samesite='lax', secure=PUBLIC_URL.startswith('https://'))
    return response

@app.post('/api/logout')
def logout():
    response = RedirectResponse(url='/', status_code=303)
    response.delete_cookie('cf_admin')
    return response

class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: Optional[str] = None
@app.post('/api/clients', dependencies=[Depends(require_admin)])
def create_client(data: ClientIn):
    with db() as c:
        cur = c.execute('INSERT INTO clients(name,email,token,created_at) VALUES (?,?,?,?)',
                        (data.name.strip(), (data.email or '').strip(), secrets.token_urlsafe(32), now()))
        row = c.execute('SELECT * FROM clients WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)

@app.get('/api/clients', dependencies=[Depends(require_admin)])
def list_clients():
    with db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM clients ORDER BY id DESC')]

@app.get('/api/posts', dependencies=[Depends(require_admin)])
def list_posts():
    with db() as c:
        return [dict(r) for r in c.execute('SELECT p.*, c.name client_name, c.token client_token FROM posts p JOIN clients c ON c.id=p.client_id ORDER BY p.id DESC')]

@app.post('/api/posts', dependencies=[Depends(require_admin)])
async def create_post(client_id: int = Form(...), title: str = Form(...),
                      caption: str = Form(''), publish_at: str = Form(''),
                      video: Optional[UploadFile] = File(None)):
    title = title.strip()
    if not title or len(title) > 200: raise HTTPException(400, 'Title must be 1-200 characters')
    if len(caption) > 10000: raise HTTPException(400, 'Caption is too long')
    if publish_at:
        try: datetime.fromisoformat(publish_at)
        except ValueError: raise HTTPException(400, 'Invalid publication date')
    with db() as c:
        client = c.execute('SELECT * FROM clients WHERE id=?', (client_id,)).fetchone()
    if not client: raise HTTPException(404, 'Client not found')
    stored, original = None, None
    if video and video.filename:
        original = Path(video.filename).name[:200]
        ext = Path(original).suffix.lower()
        if ext not in {'.mp4', '.mov', '.webm', '.m4v'}:
            raise HTTPException(400, 'Upload an MP4, MOV, WEBM or M4V video')
        stored = secrets.token_hex(20) + ext
        path = UPLOADS / stored
        size = 0
        try:
            with path.open('wb') as dest:
                while chunk := await video.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_MB * 1024 * 1024:
                        raise HTTPException(413, f'Maximum upload size is {MAX_UPLOAD_MB} MB')
                    dest.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    with db() as c:
        stamp = now()
        cur = c.execute('''INSERT INTO posts(client_id,title,caption,publish_at,filename,original_filename,status,created_at,updated_at)
                             VALUES(?,?,?,?,?,?,'pending',?,?)''',
                        (client_id,title,caption,publish_at or None,stored,original,stamp,stamp))
        pid = cur.lastrowid
        c.execute('INSERT INTO activity(post_id,event,timestamp) VALUES(?,?,?)', (pid,'Submitted for review',stamp))
    link = f'{PUBLIC_URL}/?client={client["token"]}&post={pid}'
    email_status = notify(client['email'], f'Content ready to review: {title}',
                          f'A new reel is ready for your approval.\n\n{title}\nReview it: {link}')
    return {'id': pid, 'review_url': link, 'notification': email_status}

@app.get('/api/portal/{token}')
def portal(token: str):
    client = get_client(token)
    with db() as c:
        posts = [dict(r) for r in c.execute('SELECT * FROM posts WHERE client_id=? ORDER BY id DESC', (client['id'],))]
    return {'client': {'name':client['name']}, 'posts':posts}

@app.get('/api/video/{post_id}')
def video(post_id: int, request: Request, token: str = ''):
    with db() as c:
        post = c.execute('''SELECT p.*, c.token client_token FROM posts p
                            JOIN clients c ON c.id=p.client_id WHERE p.id=?''', (post_id,)).fetchone()
    if not post: raise HTTPException(404, 'Video not found')
    if not is_admin(request) and not hmac.compare_digest(token, post['client_token']):
        raise HTTPException(403, 'Not allowed to view this video')
    if not post['filename']: raise HTTPException(404, 'No video attached')
    return FileResponse(UPLOADS / post['filename'], media_type={'.mp4':'video/mp4','.webm':'video/webm','.mov':'video/quicktime','.m4v':'video/x-m4v'}.get(Path(post['filename']).suffix, 'application/octet-stream'))

class Decision(BaseModel):
    action: str
    feedback: str = Field(default='', max_length=2000)
@app.post('/api/portal/{token}/posts/{post_id}/decision')
def decision(token: str, post_id: int, data: Decision):
    client = get_client(token)
    if data.action not in ('approve','changes'): raise HTTPException(400, 'Invalid decision')
    if data.action == 'changes' and not data.feedback.strip():
        raise HTTPException(400, 'Please describe the changes needed')
    with db() as c:
        post = c.execute('SELECT * FROM posts WHERE id=? AND client_id=?', (post_id,client['id'])).fetchone()
        if not post: raise HTTPException(404, 'Post not found')
        if post['status'] != 'pending': raise HTTPException(409, 'This post has already been reviewed')
        state = 'approved' if data.action == 'approve' else 'changes'
        c.execute('UPDATE posts SET status=?,feedback=?,updated_at=? WHERE id=?', (state,data.feedback.strip(),now(),post_id))
        c.execute('INSERT INTO activity(post_id,event,detail,timestamp) VALUES (?,?,?,?)',
                  (post_id, 'Client approved' if state=='approved' else 'Changes requested',data.feedback.strip(),now()))
    notify(os.getenv('ADMIN_EMAIL'), f'{client["name"]}: {state} — {post["title"]}',
           f'Client: {client["name"]}\nPost: {post["title"]}\nStatus: {state}\nFeedback: {data.feedback}\n{PUBLIC_URL}')
    return {'status': state}

@app.post('/api/posts/{post_id}/resubmit', dependencies=[Depends(require_admin)])
def resubmit(post_id: int):
    with db() as c:
        post = c.execute('SELECT p.*, c.email, c.token FROM posts p JOIN clients c ON p.client_id=c.id WHERE p.id=?', (post_id,)).fetchone()
        if not post: raise HTTPException(404, 'Post not found')
        c.execute("UPDATE posts SET status='pending',feedback='',updated_at=? WHERE id=?", (now(),post_id))
        c.execute('INSERT INTO activity(post_id,event,timestamp) VALUES(?,?,?)',(post_id,'Sent back for review',now()))
    notify(post['email'], f'Please review again: {post["title"]}',
           f'This item is waiting for your review: {PUBLIC_URL}/?client={post["token"]}&post={post_id}')
    return {'status':'pending'}

@app.get('/api/posts/{post_id}/activity', dependencies=[Depends(require_admin)])
def history(post_id: int):
    with db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM activity WHERE post_id=? ORDER BY id DESC', (post_id,))]

@app.get('/api/health')
def health(): return {'status':'ok'}
