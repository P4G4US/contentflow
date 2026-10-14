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
from typing import List, Optional
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
VIDEO_MIME_TYPES = {
    '.mp4': 'video/mp4', '.mov': 'video/quicktime',
    '.webm': 'video/webm', '.m4v': 'video/x-m4v',
}
IMAGE_MIME_TYPES = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.webp': 'image/webp', '.gif': 'image/gif',
}
VOICE_MIME_TYPES = {
    'audio/webm': '.webm', 'audio/ogg': '.ogg', 'audio/mp4': '.m4a',
    'audio/mpeg': '.mp3', 'audio/wav': '.wav', 'audio/x-wav': '.wav',
}
MAX_VOICE_NOTE_BYTES = 10 * 1024 * 1024
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
            email TEXT, token TEXT NOT NULL UNIQUE, admin_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER NOT NULL,
            title TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '',
            publish_at TEXT, content_type TEXT NOT NULL DEFAULT 'reel',
            filename TEXT, original_filename TEXT,
            status TEXT NOT NULL DEFAULT 'pending', feedback TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id));
        CREATE TABLE IF NOT EXISTS post_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS post_feedback_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL,
            event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', timestamp TEXT NOT NULL,
            FOREIGN KEY(post_id) REFERENCES posts(id));
        ''')
        post_columns = {row['name'] for row in c.execute('PRAGMA table_info(posts)')}
        if 'content_type' not in post_columns:
            c.execute("ALTER TABLE posts ADD COLUMN content_type TEXT NOT NULL DEFAULT 'reel'")
        client_columns = {row['name'] for row in c.execute('PRAGMA table_info(clients)')}
        if 'admin_message' not in client_columns:
            c.execute("ALTER TABLE clients ADD COLUMN admin_message TEXT NOT NULL DEFAULT ''")
init_db()

def now(): return datetime.now(timezone.utc).isoformat()
def rowdict(row): return dict(row) if row else None

def posts_with_media(rows):
    posts = [dict(row) for row in rows]
    post_ids = {post['id'] for post in posts}
    media_by_post = {post_id: [] for post_id in post_ids}
    feedback_by_post = {post_id: [] for post_id in post_ids}
    if post_ids:
        with db() as c:
            media_rows = c.execute('SELECT * FROM post_media ORDER BY post_id, position, id')
            for media in media_rows:
                if media['post_id'] in media_by_post:
                    media_by_post[media['post_id']].append(dict(media))
            feedback_rows = c.execute('SELECT * FROM post_feedback_media ORDER BY created_at, id')
            for feedback_media in feedback_rows:
                if feedback_media['post_id'] in feedback_by_post:
                    feedback_by_post[feedback_media['post_id']].append(dict(feedback_media))
    for post in posts:
        post.setdefault('content_type', 'reel')
        post['media'] = media_by_post[post['id']]
        post['feedback_media'] = feedback_by_post[post['id']]
        if not post['media'] and post.get('filename'):
            extension = Path(post['filename']).suffix.lower()
            post['media'] = [{
                'id': None,
                'filename': post['filename'],
                'original_filename': post.get('original_filename') or post['filename'],
                'media_type': VIDEO_MIME_TYPES.get(extension, 'application/octet-stream'),
                'position': 0,
            }]
    return posts

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

class ClientMessage(BaseModel):
    message: str = Field(default='', max_length=2000)

@app.put('/api/clients/{client_id}/message', dependencies=[Depends(require_admin)])
def update_client_message(client_id: int, data: ClientMessage):
    with db() as c:
        result = c.execute('UPDATE clients SET admin_message=? WHERE id=?', (data.message.strip(), client_id))
    if not result.rowcount: raise HTTPException(404, 'Client not found')
    return {'message': data.message.strip()}

@app.get('/api/portal/{token}/message')
def get_client_message(token: str):
    client = get_client(token)
    return {'message': client['admin_message']}

def remove_media_files(filenames):
    for filename in set(filenames):
        if filename:
            (UPLOADS / Path(filename).name).unlink(missing_ok=True)

@app.delete('/api/posts/{post_id}', dependencies=[Depends(require_admin)])
def delete_post(post_id: int):
    with db() as c:
        post = c.execute('SELECT filename FROM posts WHERE id=?', (post_id,)).fetchone()
        if not post: raise HTTPException(404, 'Content not found')
        filenames = [post['filename']]
        filenames.extend(row['filename'] for row in c.execute('SELECT filename FROM post_media WHERE post_id=?', (post_id,)))
        filenames.extend(row['filename'] for row in c.execute('SELECT filename FROM post_feedback_media WHERE post_id=?', (post_id,)))
        c.execute('DELETE FROM post_media WHERE post_id=?', (post_id,))
        c.execute('DELETE FROM post_feedback_media WHERE post_id=?', (post_id,))
        c.execute('DELETE FROM activity WHERE post_id=?', (post_id,))
        c.execute('DELETE FROM posts WHERE id=?', (post_id,))
    remove_media_files(filenames)
    return {'deleted': True}

@app.delete('/api/clients/{client_id}', dependencies=[Depends(require_admin)])
def delete_client(client_id: int):
    with db() as c:
        client = c.execute('SELECT id FROM clients WHERE id=?', (client_id,)).fetchone()
        if not client: raise HTTPException(404, 'Client not found')
        post_rows = c.execute('SELECT id,filename FROM posts WHERE client_id=?', (client_id,)).fetchall()
        post_ids = [row['id'] for row in post_rows]
        filenames = [row['filename'] for row in post_rows]
        filenames.extend(row['filename'] for row in c.execute('SELECT filename FROM post_media WHERE post_id IN (SELECT id FROM posts WHERE client_id=?)', (client_id,)))
        filenames.extend(row['filename'] for row in c.execute('SELECT filename FROM post_feedback_media WHERE post_id IN (SELECT id FROM posts WHERE client_id=?)', (client_id,)))
        c.execute('DELETE FROM post_media WHERE post_id IN (SELECT id FROM posts WHERE client_id=?)', (client_id,))
        c.execute('DELETE FROM post_feedback_media WHERE post_id IN (SELECT id FROM posts WHERE client_id=?)', (client_id,))
        c.execute('DELETE FROM activity WHERE post_id IN (SELECT id FROM posts WHERE client_id=?)', (client_id,))
        c.execute('DELETE FROM posts WHERE client_id=?', (client_id,))
        c.execute('DELETE FROM clients WHERE id=?', (client_id,))
    remove_media_files(filenames)
    return {'deleted': True, 'posts_deleted': len(post_ids)}

@app.get('/api/posts', dependencies=[Depends(require_admin)])
def list_posts():
    with db() as c:
        rows = c.execute('SELECT p.*, c.name client_name, c.token client_token FROM posts p JOIN clients c ON c.id=p.client_id ORDER BY p.id DESC').fetchall()
    return posts_with_media(rows)

@app.post('/api/posts', dependencies=[Depends(require_admin)])
async def create_post(client_id: int = Form(...), title: str = Form(...),
                      caption: str = Form(''), publish_at: str = Form(''),
                      content_type: str = Form('reel'),
                      media_files: Optional[List[UploadFile]] = File(None),
                      video: Optional[UploadFile] = File(None)):
    title = title.strip()
    if not title or len(title) > 200: raise HTTPException(400, 'Title must be 1-200 characters')
    if len(caption) > 10000: raise HTTPException(400, 'Caption is too long')
    if content_type not in {'story', 'reel', 'carousel'}:
        raise HTTPException(400, 'Choose Story, Reel / Video, or Carousel / Static')
    if publish_at:
        try: datetime.fromisoformat(publish_at)
        except ValueError: raise HTTPException(400, 'Invalid publication date')
    with db() as c:
        client = c.execute('SELECT * FROM clients WHERE id=?', (client_id,)).fetchone()
    if not client: raise HTTPException(404, 'Client not found')
    uploads = [item for item in (media_files or []) if item.filename]
    if video and video.filename:
        uploads.insert(0, video)
    if not uploads:
        raise HTTPException(400, 'Choose media to upload')
    if content_type in {'story', 'reel'} and len(uploads) != 1:
        raise HTTPException(400, 'Stories and Reels must contain exactly one media file')
    if content_type == 'carousel' and len(uploads) > 10:
        raise HTTPException(400, 'A carousel can contain at most 10 images')

    stored_media = []
    total_size = 0
    try:
        for item in uploads:
            original = Path(item.filename).name[:200]
            extension = Path(original).suffix.lower()
            is_video = extension in VIDEO_MIME_TYPES
            is_image = extension in IMAGE_MIME_TYPES
            if content_type == 'reel' and not is_video:
                raise HTTPException(400, 'Reels require an MP4, MOV, WEBM, or M4V video')
            if content_type == 'carousel' and not is_image:
                raise HTTPException(400, 'Carousel / Static content requires JPG, PNG, WEBP, or GIF images')
            if content_type == 'story' and not (is_image or is_video):
                raise HTTPException(400, 'Stories require an image or video file')
            stored = secrets.token_hex(20) + extension
            path = UPLOADS / stored
            with path.open('wb') as destination:
                while chunk := await item.read(1024 * 1024):
                    total_size += len(chunk)
                    if total_size > MAX_UPLOAD_MB * 1024 * 1024:
                        raise HTTPException(413, f'Total upload size exceeds {MAX_UPLOAD_MB} MB')
                    destination.write(chunk)
            stored_media.append({
                'filename': stored,
                'original_filename': original,
                'media_type': (VIDEO_MIME_TYPES if is_video else IMAGE_MIME_TYPES)[extension],
                'position': len(stored_media),
            })
    except Exception:
        for item in stored_media:
            (UPLOADS / item['filename']).unlink(missing_ok=True)
        if 'path' in locals():
            path.unlink(missing_ok=True)
        raise

    first_media = stored_media[0]
    try:
        with db() as c:
            stamp = now()
            cur = c.execute('''INSERT INTO posts(client_id,title,caption,publish_at,content_type,filename,original_filename,status,created_at,updated_at)
                                 VALUES(?,?,?,?,?,?,?,'pending',?,?)''',
                            (client_id,title,caption,publish_at or None,content_type,first_media['filename'],first_media['original_filename'],stamp,stamp))
            pid = cur.lastrowid
            c.executemany('INSERT INTO post_media(post_id,filename,original_filename,media_type,position) VALUES(?,?,?,?,?)',
                          [(pid,item['filename'],item['original_filename'],item['media_type'],item['position']) for item in stored_media])
            c.execute('INSERT INTO activity(post_id,event,timestamp) VALUES(?,?,?)', (pid,'Submitted for review',stamp))
    except Exception:
        for item in stored_media:
            (UPLOADS / item['filename']).unlink(missing_ok=True)
        raise
    link = f'{PUBLIC_URL}/?client={client["token"]}&post={pid}'
    type_label = {'story': 'Story', 'reel': 'Reel / video', 'carousel': 'Carousel / static'}[content_type]
    email_status = notify(client['email'], f'Content ready to review: {title}',
                          f'A new {type_label} is ready for your approval.\n\n{title}\nReview it: {link}')
    return {'id': pid, 'review_url': link, 'notification': email_status}

@app.get('/api/portal/{token}')
def portal(token: str):
    client = get_client(token)
    with db() as c:
        rows = c.execute('SELECT * FROM posts WHERE client_id=? ORDER BY id DESC', (client['id'],)).fetchall()
    return {'client': {'name':client['name'], 'admin_message':client['admin_message']}, 'posts':posts_with_media(rows)}

@app.get('/api/media/{media_id}')
def media_file(media_id: int, request: Request, token: str = '', download: bool = False):
    with db() as c:
        media = c.execute('''SELECT m.*, c.token client_token FROM post_media m
                             JOIN posts p ON p.id=m.post_id
                             JOIN clients c ON c.id=p.client_id
                             WHERE m.id=?''', (media_id,)).fetchone()
    if not media: raise HTTPException(404, 'Media not found')
    if not is_admin(request) and not hmac.compare_digest(token, media['client_token']):
        raise HTTPException(403, 'Not allowed to view this media')
    return FileResponse(
        UPLOADS / media['filename'],
        media_type=media['media_type'],
        filename=media['original_filename'],
        content_disposition_type='attachment' if download else 'inline',
    )

@app.get('/api/feedback-media/{media_id}')
def feedback_media_file(media_id: int, request: Request, token: str = '', download: bool = False):
    with db() as c:
        media = c.execute('''SELECT m.*, c.token client_token FROM post_feedback_media m
                             JOIN posts p ON p.id=m.post_id
                             JOIN clients c ON c.id=p.client_id
                             WHERE m.id=?''', (media_id,)).fetchone()
    if not media: raise HTTPException(404, 'Voice note not found')
    if not is_admin(request) and not hmac.compare_digest(token, media['client_token']):
        raise HTTPException(403, 'Not allowed to view this voice note')
    return FileResponse(
        UPLOADS / media['filename'],
        media_type=media['media_type'],
        filename=media['original_filename'],
        content_disposition_type='attachment' if download else 'inline',
    )

@app.get('/api/video/{post_id}')
def video(post_id: int, request: Request, token: str = '', download: bool = False):
    with db() as c:
        post = c.execute('''SELECT p.*, c.token client_token FROM posts p
                            JOIN clients c ON c.id=p.client_id WHERE p.id=?''', (post_id,)).fetchone()
    if not post: raise HTTPException(404, 'Video not found')
    if not is_admin(request) and not hmac.compare_digest(token, post['client_token']):
        raise HTTPException(403, 'Not allowed to view this video')
    if not post['filename']: raise HTTPException(404, 'No video attached')
    return FileResponse(
        UPLOADS / post['filename'],
        media_type=VIDEO_MIME_TYPES.get(Path(post['filename']).suffix.lower(), 'application/octet-stream'),
        filename=post['original_filename'] or post['filename'],
        content_disposition_type='attachment' if download else 'inline',
    )

class Decision(BaseModel):
    action: str
    feedback: str = Field(default='', max_length=2000)
@app.post('/api/portal/{token}/posts/{post_id}/decision')
async def decision(token: str, post_id: int, request: Request):
    client = get_client(token)
    voice_note = None
    if request.headers.get('content-type', '').startswith('multipart/form-data'):
        form = await request.form()
        data = Decision(action=str(form.get('action', '')), feedback=str(form.get('feedback', '')))
        candidate = form.get('voice_note')
        if hasattr(candidate, 'filename') and candidate.filename:
            voice_note = candidate
    else:
        data = Decision.model_validate(await request.json())
    if data.action not in ('approve','changes'): raise HTTPException(400, 'Invalid decision')
    if data.action == 'changes' and not data.feedback.strip() and not voice_note:
        raise HTTPException(400, 'Write a description or record a voice note')
    if data.action == 'approve' and voice_note:
        raise HTTPException(400, 'Voice notes can only be attached to a change request')

    voice_media = None
    voice_path = None
    if voice_note:
        media_type = (voice_note.content_type or '').split(';', 1)[0].lower()
        extension = VOICE_MIME_TYPES.get(media_type)
        if not extension:
            raise HTTPException(400, 'Record voice feedback in a supported audio format')
        stored_filename = secrets.token_hex(20) + extension
        voice_path = UPLOADS / stored_filename
        size = 0
        try:
            with voice_path.open('wb') as destination:
                while chunk := await voice_note.read(256 * 1024):
                    size += len(chunk)
                    if size > MAX_VOICE_NOTE_BYTES:
                        raise HTTPException(413, 'Voice notes must be 10 MB or smaller')
                    destination.write(chunk)
        except Exception:
            voice_path.unlink(missing_ok=True)
            raise
        voice_media = {
            'filename': stored_filename,
            'original_filename': f'client-voice-feedback{extension}',
            'media_type': media_type,
        }

    with db() as c:
        post = c.execute('SELECT * FROM posts WHERE id=? AND client_id=?', (post_id,client['id'])).fetchone()
        if not post:
            if voice_path: voice_path.unlink(missing_ok=True)
            raise HTTPException(404, 'Post not found')
        if post['status'] != 'pending':
            if voice_path: voice_path.unlink(missing_ok=True)
            raise HTTPException(409, 'This post has already been reviewed')
        state = 'approved' if data.action == 'approve' else 'changes'
        try:
            c.execute('UPDATE posts SET status=?,feedback=?,updated_at=? WHERE id=?', (state,data.feedback.strip(),now(),post_id))
            c.execute('INSERT INTO activity(post_id,event,detail,timestamp) VALUES (?,?,?,?)',
                      (post_id, 'Client approved' if state=='approved' else 'Changes requested',data.feedback.strip(),now()))
            if voice_media:
                c.execute('INSERT INTO post_feedback_media(post_id,filename,original_filename,media_type,created_at) VALUES(?,?,?,?,?)',
                          (post_id,voice_media['filename'],voice_media['original_filename'],voice_media['media_type'],now()))
        except Exception:
            if voice_path: voice_path.unlink(missing_ok=True)
            raise
    notify(os.getenv('ADMIN_EMAIL'), f'{client["name"]}: {state} — {post["title"]}',
           f'Client: {client["name"]}\nPost: {post["title"]}\nStatus: {state}\nFeedback: {data.feedback or "Voice note attached"}\n{PUBLIC_URL}')
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
