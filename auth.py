"""Local account, session, CSRF, and administration support."""

from __future__ import annotations

import hmac
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


PASSWORD_MIN_LENGTH = 8

from catalog import DATA_DIR, connect_db


bp = Blueprint('auth', __name__)
USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,32}$')
LOGIN_WINDOW = 5 * 60
LOGIN_LIMIT = 8
_attempts: dict[str, deque[float]] = defaultdict(deque)
_attempts_lock = threading.Lock()


def _secret_key() -> bytes:
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = DATA_DIR / 'session.key'
    if not path.exists():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    path.chmod(0o600)
    return path.read_bytes().strip()


def _user_count() -> int:
    with connect_db() as db:
        return db.execute('SELECT COUNT(*) FROM users').fetchone()[0]


def _user_by_id(user_id: int):
    with connect_db() as db:
        return db.execute(
            'SELECT id, username, display_name, role, active, created_at, last_login_at '
            'FROM users WHERE id = ?', (user_id,)
        ).fetchone()


def _is_safe_next(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    return not parsed.scheme and not parsed.netloc and value.startswith('/')


def csrf_token() -> str:
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def _login_limited(client: str) -> bool:
    now = time.monotonic()
    with _attempts_lock:
        attempts = _attempts[client]
        while attempts and now - attempts[0] > LOGIN_WINDOW:
            attempts.popleft()
        return len(attempts) >= LOGIN_LIMIT


def _record_failed_login(client: str) -> None:
    with _attempts_lock:
        _attempts[client].append(time.monotonic())


def _clear_login_attempts(client: str) -> None:
    with _attempts_lock:
        _attempts.pop(client, None)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not g.user or g.user['role'] != 'admin':
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def _create_user(username: str, display_name: str, password: str,
                 role: str = 'user') -> int:
    if not USERNAME_RE.fullmatch(username):
        raise ValueError('Username must be 3–32 letters, numbers, dots, dashes, or underscores.')
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f'Password must be at least {PASSWORD_MIN_LENGTH} characters.'
        )
    display_name = display_name.strip() or username
    if len(display_name) > 80:
        raise ValueError('Display name must be 80 characters or fewer.')
    with connect_db() as db:
        cursor = db.execute(
            '''INSERT INTO users
                   (username, display_name, password_hash, role, active, created_at)
               VALUES (?, ?, ?, ?, 1, ?)''',
            (username, display_name, generate_password_hash(password, method='scrypt'),
             role, time.time()),
        )
        return cursor.lastrowid


def _migrate_global_favorites(user_id: int) -> None:
    with connect_db() as db:
        db.execute(
            '''INSERT OR IGNORE INTO user_favorites (user_id, media_id, created_at)
               SELECT ?, m.id, f.created
               FROM favorites f
               JOIN media_items m
                 ON m.collection = f.collection AND m.subpath = f.subpath''',
            (user_id,),
        )


def init_auth(app) -> None:
    app.secret_key = _secret_key()
    app.config.update(
        SESSION_COOKIE_NAME='visionmini_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    app.register_blueprint(bp)
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def load_and_require_user():
        g.user = None
        user_id = session.get('user_id')
        if user_id:
            user = _user_by_id(int(user_id))
            if user and user['active']:
                g.user = user
            else:
                session.clear()

        public = {
            'auth.login', 'auth.setup', 'health', 'static',
            'manifest', 'service_worker',
        }
        if request.endpoint in public or request.method == 'OPTIONS':
            return None
        if _user_count() == 0:
            return redirect(url_for('auth.setup'))
        if g.user is None:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'authentication required'}), 401
            return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))
        return None

    @app.before_request
    def verify_csrf():
        if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return None
        expected = session.get('_csrf_token', '')
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('_csrf_token', '')
        if not expected or not hmac.compare_digest(expected, supplied):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'invalid CSRF token'}), 400
            abort(400, 'Invalid or expired form token. Reload the page and try again.')
        return None

    @app.context_processor
    def auth_context():
        return {'current_user': g.get('user')}


@bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if _user_count():
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password != request.form.get('password_confirm', ''):
            flash('The passwords do not match.', 'error')
        else:
            try:
                user_id = _create_user(
                    request.form.get('username', '').strip(),
                    request.form.get('display_name', '').strip(),
                    password,
                    role='admin',
                )
            except ValueError as exc:
                flash(str(exc), 'error')
            except sqlite3.IntegrityError:
                flash('That username is already in use.', 'error')
            else:
                _migrate_global_favorites(user_id)
                session.clear()
                session['user_id'] = user_id
                session.permanent = True
                csrf_token()
                flash('Your private gallery is ready.', 'success')
                return redirect(url_for('index'))
    return render_template('setup.html')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if not _user_count():
        return redirect(url_for('auth.setup'))
    if g.user:
        return redirect(url_for('index'))
    client = request.remote_addr or 'unknown'
    if request.method == 'POST':
        if _login_limited(client):
            flash('Too many attempts. Wait five minutes and try again.', 'error')
            return render_template('login.html'), 429
        username = request.form.get('username', '').strip()
        with connect_db() as db:
            user = db.execute(
                'SELECT * FROM users WHERE username = ? COLLATE NOCASE', (username,)
            ).fetchone()
        if not user or not user['active'] or not check_password_hash(
                user['password_hash'], request.form.get('password', '')):
            _record_failed_login(client)
            flash('Incorrect username or password.', 'error')
        else:
            _clear_login_attempts(client)
            session.clear()
            session['user_id'] = user['id']
            session.permanent = request.form.get('remember') == '1'
            csrf_token()
            with connect_db() as db:
                db.execute('UPDATE users SET last_login_at = ? WHERE id = ?',
                           (time.time(), user['id']))
            next_url = request.args.get('next')
            return redirect(next_url if _is_safe_next(next_url) else url_for('index'))
    return render_template('login.html')


@bp.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@bp.route('/account', methods=['GET', 'POST'])
def account():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        with connect_db() as db:
            full_user = db.execute('SELECT * FROM users WHERE id = ?',
                                   (g.user['id'],)).fetchone()
            if not check_password_hash(full_user['password_hash'], current_password):
                flash('Current password is incorrect.', 'error')
            elif len(new_password) < PASSWORD_MIN_LENGTH:
                flash(
                    f'New password must be at least {PASSWORD_MIN_LENGTH} characters.',
                    'error',
                )
            elif new_password != request.form.get('new_password_confirm', ''):
                flash('The new passwords do not match.', 'error')
            else:
                db.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                           (generate_password_hash(new_password, method='scrypt'),
                            g.user['id']))
                flash('Password updated.', 'success')
                return redirect(url_for('auth.account'))
    return render_template('account.html')


@bp.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create_user':
            try:
                _create_user(
                    request.form.get('username', '').strip(),
                    request.form.get('display_name', '').strip(),
                    request.form.get('password', ''),
                    role='admin' if request.form.get('role') == 'admin' else 'user',
                )
                flash('Account created.', 'success')
            except ValueError as exc:
                flash(str(exc), 'error')
            except sqlite3.IntegrityError:
                flash('That username is already in use.', 'error')
        elif action == 'toggle_user':
            user_id = request.form.get('user_id', type=int)
            if user_id == g.user['id']:
                flash('You cannot deactivate your own account.', 'error')
            else:
                with connect_db() as db:
                    db.execute('UPDATE users SET active = 1 - active WHERE id = ?',
                               (user_id,))
                flash('Account status updated.', 'success')
        return redirect(url_for('auth.admin'))

    with connect_db() as db:
        users = db.execute(
            'SELECT id, username, display_name, role, active, created_at, last_login_at '
            'FROM users ORDER BY created_at'
        ).fetchall()
        scans = db.execute(
            'SELECT * FROM scan_state ORDER BY collection'
        ).fetchall()
        stats = {
            'media': db.execute('SELECT COUNT(*) FROM media_items').fetchone()[0],
            'metadata_done': db.execute(
                "SELECT COUNT(*) FROM media_items WHERE metadata_status = 'ready'"
            ).fetchone()[0],
            'embeddings': db.execute(
                "SELECT COUNT(*) FROM media_items WHERE embedding_status = 'ready'"
            ).fetchone()[0],
            'posters': db.execute(
                "SELECT COUNT(*) FROM media_items WHERE poster_status = 'ready'"
            ).fetchone()[0],
        }
        jobs = db.execute('SELECT * FROM job_state ORDER BY job').fetchall()
    return render_template('admin.html', users=users, scans=scans, stats=stats,
                           jobs=jobs)


@bp.post('/admin/jobs/<job>')
@admin_required
def run_job(job):
    units = {
        'scan': 'nfs-image-viewer-index.service',
        'metadata': 'nfs-image-viewer-enrich.service',
        'posters': 'nfs-image-viewer-posters.service',
        'semantic': 'nfs-image-viewer-semantic-index.service',
        'backup': 'nfs-image-viewer-backup.service',
    }
    unit = units.get(job)
    if not unit:
        abort(404)
    result = subprocess.run(
        ['systemctl', '--user', 'start', '--no-block', unit],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode:
        flash(result.stderr.strip() or 'Could not start the job.', 'error')
    else:
        flash(f'{job.title()} job started.', 'success')
    return redirect(url_for('auth.admin'))
