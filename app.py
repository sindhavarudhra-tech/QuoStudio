import os
import csv
import json
import secrets
import hashlib
from io import StringIO
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
import psycopg2.errors
import psycopg2.extras
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv('.env.local')

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', "quostudio_super_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 

# ==========================================
# SUPABASE INITIALIZATION
# ==========================================
SUPABASE_URL = os.getenv('NEXT_PUBLIC_SUPABASE_URL')
SUPABASE_KEY = os.getenv('NEXT_PUBLIC_SUPABASE_ANON_KEY')

if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("WARNING: Supabase credentials not found. Check your .env.local file.")
    supabase = None

def get_db_connection():
    database_url = os.getenv('DATABASE_URL') or "postgresql://postgres:Rudhrapatel15*@db.ureklqoahnubcxzqjynd.supabase.co:5432/postgres"
    return psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)

# ==========================================
# 10-DIGIT HASH MAP UNIQUENESS ALGORITHM
# ==========================================
class TenBitHashMap:
    def __init__(self):
        self.registered_hashes = set()
        
    def _get_10_bit_hash(self, text):
        full_hash = int(hashlib.sha256(text.encode()).hexdigest(), 16)
        return format(full_hash & 0x3FF, '010b')
        
    def is_unique(self, username):
        new_hash = self._get_10_bit_hash(username)
        for existing_hash in self.registered_hashes:
            if new_hash == existing_hash:
                return False 
        return True
        
    def register(self, username):
        self.registered_hashes.add(self._get_10_bit_hash(username))

username_checker = TenBitHashMap()

# ==========================================
# DATABASE SETUP (SECURE: NO PLAINTEXT PASSWORDS)
# ==========================================
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            username VARCHAR(255) UNIQUE NOT NULL,
            company_name VARCHAR(255),
            is_verified BOOLEAN DEFAULT FALSE,
            currency VARCHAR(10) DEFAULT 'EUR',
            date_format VARCHAR(20) DEFAULT 'DD/MM/YYYY',
            quote_validity INTEGER DEFAULT 30,
            tax_rate NUMERIC(5,2) DEFAULT 19.0,
            notif_quote_accepted BOOLEAN DEFAULT TRUE,
            notif_new_messages BOOLEAN DEFAULT TRUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quotations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            recipient_id INTEGER REFERENCES users(id),
            client_name VARCHAR(255) NOT NULL,
            document_data TEXT,
            status VARCHAR(50) DEFAULT 'draft',
            signature_data TEXT,
            signature_ip VARCHAR(45),
            signature_user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS catalogs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            name VARCHAR(255) NOT NULL,
            headers JSONB,
            rows JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_history (
            sender_id INTEGER REFERENCES users(id),
            recipient_id INTEGER REFERENCES users(id),
            last_sent TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (sender_id, recipient_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            sender_id INTEGER REFERENCES users(id),
            recipient_id INTEGER REFERENCES users(id),
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read BOOLEAN DEFAULT FALSE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contact_messages (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read BOOLEAN DEFAULT FALSE
        )
    ''')
    
    try:
        cursor.execute("ALTER TABLE users DROP COLUMN IF EXISTS password;")
        cursor.execute("ALTER TABLE users DROP COLUMN IF EXISTS verify_token;")
        cursor.execute("ALTER TABLE users DROP COLUMN IF EXISTS reset_token;")
        cursor.execute("ALTER TABLE users DROP COLUMN IF EXISTS avatar_url;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(255) UNIQUE;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS company_name VARCHAR(255);")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'EUR';")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS date_format VARCHAR(20) DEFAULT 'DD/MM/YYYY';")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS quote_validity INTEGER DEFAULT 30;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5,2) DEFAULT 19.0;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_quote_accepted BOOLEAN DEFAULT TRUE;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_new_messages BOOLEAN DEFAULT TRUE;")
    except Exception:
        pass
        
    cursor.execute("SELECT username FROM users WHERE username IS NOT NULL")
    for row in cursor.fetchall():
        username_checker.register(row['username'])
        
    conn.commit()
    cursor.close()
    conn.close()

init_db()

# ==========================================
# AUTHENTICATION & LAUNCH
# ==========================================
@app.route('/')
def index():
    logged_in = 'user_id' in session
    initials = "".join([w[0].upper() for w in session.get('username', '').split()[:2]]) if session.get('username') else "Q"
    return render_template('index.html', logged_in=logged_in, initials=initials)

@app.route('/launch')
def launch_app():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    else:
        return redirect(url_for('login'))

@app.route('/check_username', methods=['GET'])
def check_username():
    requested_username = request.args.get('username', '')
    if not requested_username:
        return jsonify({"available": False})
        
    is_free = username_checker.is_unique(requested_username)
    return jsonify({"available": is_free})

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        action = request.form.get('action')
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            if action == 'login':
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                if res and res.session:
                    access_token = res.session.access_token
                    
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
                    user = cursor.fetchone()
                    cursor.close()
                    conn.close()
                    
                    if user:
                        session['access_token'] = access_token
                        session['user_id'] = user['id']
                        session['user_email'] = user['email']
                        session['username'] = user.get('username', '')
                        session['company_name'] = user.get('company_name', '')
                        return redirect(url_for('dashboard'))
                
                flash("Invalid credentials or unverified email.", "error")
            
            elif action == 'signup':
                requested_username = request.form.get('username')
                company = request.form.get('company_name')
                
                if not username_checker.is_unique(requested_username):
                    flash("Username is already taken! Please choose another.", "error")
                    return redirect(url_for('auth'))
                
                if supabase:
                    try:
                        supabase.auth.sign_up({
                            "email": email,
                            "password": password,
                            "options": {
                                "data": {"username": requested_username},
                                "email_redirect_to": "http://127.0.0.1:5000/verify-email"
                            }
                        })
                    except Exception as e:
                        flash(f"Supabase Auth Error: {str(e)}", "error")
                        return redirect(url_for('auth'))
                
                conn = get_db_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        'INSERT INTO users (email, username, company_name, is_verified) VALUES (%s, %s, %s, FALSE) RETURNING id',
                        (email, requested_username, company)
                    )
                    conn.commit()
                    username_checker.register(requested_username)
                    flash("Registration successful! Please check your email to verify your account.", "success")
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                    flash("An account with this email already exists. Please sign in or reset your password.", "error")
                except Exception as db_err:
                    conn.rollback()
                    flash(f"Database Error: {str(db_err)}", "error")
                finally:
                    cursor.close()
                    conn.close()
                
                return redirect(url_for('auth'))
                
        except Exception as e:
            flash(f"Error: {str(e)}", "error")
            
        return redirect(url_for('auth'))
            
    return render_template('login.html', supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)

@app.route('/verify-email', methods=['GET'])
def verify_email_page():
    return render_template('verify_success.html', supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        try:
            if supabase:
                supabase.auth.reset_password_email(
                    email, 
                    options={"redirect_to": "http://127.0.0.1:5000/reset-password"}
                )
            flash("If an account exists, a reset link has been sent to your email.", "success")
        except Exception as e:
            flash(f"Error: {str(e)}", "error")
            
        return redirect(url_for('forgot_password'))
        
    return render_template('forgot_password.html')

@app.route('/reset-password', methods=['GET'])
def reset_password():
    return render_template('reset_password.html', supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)

@app.route('/update-password-backend', methods=['POST'])
def update_password_backend():
    data = request.get_json()
    email = data.get('email')
    new_password = data.get('password')
    
    if not email or not new_password:
        return jsonify({'error': 'Missing parameters'}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET password = %s WHERE email = %s', (new_password, email))
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'status': 'success'})

@app.route('/login')
def login():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('login.html', supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)

@app.route('/set_flask_session', methods=['POST'])
def set_flask_session():
    data = request.get_json()
    access_token = data.get('access_token')
    if not access_token:
        return jsonify({'error': 'No access token provided'}), 400

    try:
        user_res = supabase.auth.get_user(access_token)
        if user_res and user_res.user:
            sb_user = user_res.user
            email = sb_user.email
            requested_username = sb_user.user_metadata.get('username', email.split('@')[0])
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
            local_user = cursor.fetchone()
            
            if not local_user:
                if not username_checker.is_unique(requested_username):
                    suffix = secrets.token_hex(4)
                    requested_username = f"{requested_username}#{suffix}"
                    
                cursor.execute(
                    'INSERT INTO users (email, username, company_name, is_verified) VALUES (%s, %s, %s, TRUE) RETURNING id, username, company_name, email',
                    (email, requested_username, '')
                )
                local_user = cursor.fetchone()
                conn.commit()
                username_checker.register(requested_username)
            else:
                cursor.execute('UPDATE users SET is_verified = TRUE WHERE email = %s', (email,))
                conn.commit()
            
            session['access_token'] = access_token
            session['user_id'] = local_user['id']
            session['user_email'] = local_user['email']
            session['username'] = local_user['username']
            session['company_name'] = local_user.get('company_name', '')
            
            cursor.close()
            conn.close()
            return jsonify({'status': 'success'})
        return jsonify({'error': 'Invalid token'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 401

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ==========================================
# DASHBOARD & SETTINGS
# ==========================================
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('index'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, username, company_name FROM users WHERE id = %s', (user_id,))
    user_profile = cursor.fetchone()
    
    cursor.execute('''
        SELECT q.id, q.client_name, q.status, q.created_at, u.username as recipient_name 
        FROM quotations q 
        LEFT JOIN users u ON q.recipient_id = u.id 
        WHERE q.user_id = %s ORDER BY q.created_at DESC
    ''', (user_id,))
    my_quotes = cursor.fetchall()
    
    cursor.execute('''
        SELECT q.id, q.client_name, q.status, q.created_at, u.username as sender_name, u.company_name as sender_company
        FROM quotations q 
        JOIN users u ON q.user_id = u.id 
        WHERE q.recipient_id = %s ORDER BY q.created_at DESC
    ''', (user_id,))
    inbox = cursor.fetchall()
    
    cursor.execute('SELECT id, name FROM catalogs WHERE user_id = %s ORDER BY created_at DESC', (user_id,))
    catalogs = cursor.fetchall()
    cursor.close()
    conn.close()
    
    initials = "".join([w[0].upper() for w in user_profile['username'].split()[:2]]) if user_profile['username'] else "Q"
    
    return render_template('dashboard.html', my_quotes=my_quotes, inbox=inbox, catalogs=catalogs, profile=user_profile, initials=initials)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        new_username = request.form.get('username')
        new_company = request.form.get('company_name')

        cursor.execute('SELECT id, username FROM users WHERE id = %s', (user_id,))
        current_profile = cursor.fetchone()
        
        if new_username and new_username != current_profile['username']:
            if not username_checker.is_unique(new_username):
                flash("That username is already taken. Please choose another.", "error")
            else:
                cursor.execute('UPDATE users SET username = %s, company_name = %s WHERE id = %s', (new_username, new_company, user_id))
                conn.commit()
                username_checker.register(new_username)
                session['username'] = new_username
                session['company_name'] = new_company
                flash("Profile updated successfully.", "success")
        else:
            cursor.execute('UPDATE users SET company_name = %s WHERE id = %s', (new_company, user_id))
            conn.commit()
            session['company_name'] = new_company
            flash("Profile updated successfully.", "success")
            
    cursor.execute('SELECT email, username, company_name, currency, date_format, quote_validity, tax_rate, notif_quote_accepted, notif_new_messages FROM users WHERE id = %s', (user_id,))
    profile = cursor.fetchone()
    cursor.close()
    conn.close()
    
    initials = "".join([w[0].upper() for w in profile['username'].split()[:2]]) if profile['username'] else "Q"
    return render_template('settings.html', profile=profile, initials=initials)

@app.route('/update_general_settings', methods=['POST'])
def update_general_settings():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT currency, date_format, quote_validity, tax_rate FROM users WHERE id = %s', (user_id,))
    existing = cursor.fetchone()
    
    currency = request.form.get('currency', existing['currency'] if existing and existing['currency'] else 'EUR')
    date_format = request.form.get('date_format', existing['date_format'] if existing and existing['date_format'] else 'DD/MM/YYYY')
    quote_validity = request.form.get('quote_validity', existing['quote_validity'] if existing and existing['quote_validity'] is not None else 30)
    tax_rate = request.form.get('tax_rate', existing['tax_rate'] if existing and existing['tax_rate'] is not None else 19.0)
    
    notif_quote_accepted = True if request.form.get('notif_quote_accepted') else False
    notif_new_messages = True if request.form.get('notif_new_messages') else False
    
    cursor.execute('''
        UPDATE users 
        SET currency = %s, date_format = %s, quote_validity = %s, tax_rate = %s, notif_quote_accepted = %s, notif_new_messages = %s 
        WHERE id = %s
    ''', (currency, date_format, quote_validity, tax_rate, notif_quote_accepted, notif_new_messages, user_id))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash("Notification and preferences updated successfully.", "success")
    return redirect(url_for('settings'))

@app.route('/export_data')
def export_data():
    if 'user_id' not in session: return jsonify({'error': 'Unauthorized'}), 401
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT email, username, company_name FROM users WHERE id = %s', (user_id,))
    profile = cursor.fetchone()
    
    cursor.execute('SELECT id, client_name, status, document_data, signature_data, signature_ip, created_at FROM quotations WHERE user_id = %s OR recipient_id = %s', (user_id, user_id))
    quotes = cursor.fetchall()
    
    cursor.execute('SELECT name, created_at FROM catalogs WHERE user_id = %s', (user_id,))
    catalogs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return jsonify({"data_subject": profile, "quotations": quotes, "inventory_catalogs": catalogs, "export_date": str(psycopg2.TimestampFromTicks(0))})

@app.route('/delete_account', methods=['POST'])
def delete_account():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM messages WHERE sender_id = %s OR recipient_id = %s', (user_id, user_id))
    cursor.execute('DELETE FROM client_history WHERE sender_id = %s OR recipient_id = %s', (user_id, user_id))
    cursor.execute('DELETE FROM catalogs WHERE user_id = %s', (user_id,))
    cursor.execute('DELETE FROM quotations WHERE user_id = %s OR recipient_id = %s', (user_id, user_id))
    cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    session.clear()
    return redirect(url_for('index'))

# ==========================================
# EDITOR & QUOTE MANAGEMENT
# ==========================================
@app.route('/new_quotation', methods=['POST'])
def new_quotation():
    if 'user_id' not in session: 
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
    client_name = request.form.get('client_name') or (request.json.get('client_name') if request.is_json else 'Untitled Project')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO quotations (user_id, client_name, document_data, status) VALUES (%s, %s, %s, %s) RETURNING id',
        (session['user_id'], client_name, "", "draft")
    )
    new_quote_id = cursor.fetchone()['id']
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'quote_id': new_quote_id})

@app.route('/editor/<int:quote_id>')
def editor(quote_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM quotations WHERE id = %s', (quote_id,))
    quote = cursor.fetchone()
    if not quote: return redirect(url_for('dashboard'))
        
    is_owner = (quote['user_id'] == user_id)
    is_recipient = (quote['recipient_id'] == user_id)
    if not is_owner and not is_recipient: return redirect(url_for('dashboard'))
        
    cursor.execute('SELECT id, name FROM catalogs WHERE user_id = %s ORDER BY name ASC', (quote['user_id'],))
    catalogs = cursor.fetchall()
    
    cursor.execute('SELECT currency, tax_rate, quote_validity, date_format FROM users WHERE id = %s', (user_id,))
    user_settings = cursor.fetchone()

    cursor.close()
    conn.close()

    initials = "".join([w[0].upper() for w in session.get('username', '').split()[:2]]) if session.get('username') else "Q"
    return render_template('editor.html', quote=quote, catalogs=catalogs, is_owner=is_owner, is_recipient=is_recipient, initials=initials, user_settings=user_settings)

@app.route('/save_quote/<int:quote_id>', methods=['POST'])
def save_quote(quote_id):
    if 'user_id' not in session: return jsonify({'status': 'error'}), 401
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE quotations SET document_data = %s WHERE id = %s AND user_id = %s',
        (request.json.get('document_data'), quote_id, session['user_id'])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/delete_quote/<int:quote_id>', methods=['POST', 'DELETE', 'GET'])
def delete_quote(quote_id):
    if 'user_id' not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM quotations WHERE id = %s AND (user_id = %s OR recipient_id = %s)', (quote_id, user_id, user_id))
    conn.commit()
    cursor.close()
    conn.close()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.method in ['POST', 'DELETE']:
        return jsonify({'success': True, 'message': 'Quote deleted successfully.'})
        
    return redirect(url_for('dashboard'))

# ==========================================
# ECOSYSTEM & MESSAGING
# ==========================================
@app.route('/search_users')
def search_users():
    if 'user_id' not in session: return jsonify([])
    query = request.args.get('q', '').lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if not query:
        cursor.execute('''
            SELECT DISTINCT u.id, u.username, u.email, u.company_name 
            FROM users u
            LEFT JOIN client_history ch ON (ch.recipient_id = u.id AND ch.sender_id = %s)
            LEFT JOIN messages m ON (m.recipient_id = u.id AND m.sender_id = %s) OR (m.sender_id = u.id AND m.recipient_id = %s)
            WHERE (ch.sender_id IS NOT NULL OR m.id IS NOT NULL) AND u.id != %s
            LIMIT 15
        ''', (session['user_id'], session['user_id'], session['user_id'], session['user_id']))
    else:
        cursor.execute('''
            SELECT id, username, email, company_name FROM users 
            WHERE id != %s AND (LOWER(username) LIKE %s OR LOWER(email) LIKE %s)
            LIMIT 10
        ''', (session['user_id'], f"%{query}%", f"%{query}%"))
        
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(results)

@app.route('/send_quote/<int:quote_id>', methods=['POST'])
def send_quote(quote_id):
    if 'user_id' not in session: return jsonify({'status': 'error'}), 401
    recipient_id = request.json.get('recipient_id')
    sender_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE quotations SET recipient_id = %s, status = 'sent' WHERE id = %s AND user_id = %s", (recipient_id, quote_id, sender_id))
    cursor.execute('''INSERT INTO client_history (sender_id, recipient_id) VALUES (%s, %s) ON CONFLICT (sender_id, recipient_id) DO UPDATE SET last_sent = CURRENT_TIMESTAMP''', (sender_id, recipient_id))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/accept_quote/<int:quote_id>', methods=['POST'])
def accept_quote(quote_id):
    if 'user_id' not in session: return jsonify({'status': 'error'}), 401
    
    signature = request.json.get('signature')
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    user_agent = request.headers.get('User-Agent')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE quotations SET status = 'accepted', signature_data = %s, signature_ip = %s, signature_user_agent = %s WHERE id = %s AND recipient_id = %s", 
        (signature, ip_address, user_agent, quote_id, session['user_id'])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/reject_quote/<int:quote_id>', methods=['POST'])
def reject_quote(quote_id):
    if 'user_id' not in session: return jsonify({'status': 'error'}), 401
    
    data = request.get_json() or {}
    reason = data.get('reason', '')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE quotations SET status = 'rejected' WHERE id = %s AND recipient_id = %s", 
        (quote_id, session['user_id'])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/api/messages/<int:other_user_id>')
def get_messages(other_user_id):
    if 'user_id' not in session: return jsonify([])
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, sender_id, content, created_at
        FROM messages
        WHERE (sender_id = %s AND recipient_id = %s)
           OR (sender_id = %s AND recipient_id = %s)
        ORDER BY created_at ASC
    ''', (user_id, other_user_id, other_user_id, user_id))
    msgs = cursor.fetchall()
    cursor.execute("UPDATE messages SET is_read = TRUE WHERE recipient_id = %s AND sender_id = %s AND is_read = FALSE", (user_id, other_user_id))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify(msgs)

@app.route('/api/messages/send', methods=['POST'])
def send_message():
    if 'user_id' not in session: return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    recipient_id = data.get('recipient_id')
    content = data.get('content')
    if not recipient_id or not content:
        return jsonify({'error': 'Missing parameters'}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO messages (sender_id, recipient_id, content) VALUES (%s, %s, %s)',
        (session['user_id'], recipient_id, content)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'success'})

# ==========================================
# CONTACT FORM API ROUTE
# ==========================================
@app.route('/api/contact', methods=['POST'])
def contact_submit():
    data = request.get_json() or request.form
    name = data.get('name')
    email = data.get('email')
    message = data.get('message')
    
    if not name or not email or not message:
        return jsonify({'success': False, 'error': 'All fields are required.'}), 400
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO contact_messages (name, email, message) VALUES (%s, %s, %s)',
            (name, email, message)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Message sent successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==========================================
# INVENTORY & CATALOG ROUTES
# ==========================================
@app.route('/upload_catalog', methods=['POST'])
def upload_catalog():
    if 'user_id' not in session: return redirect(url_for('login'))
    catalog_name = request.form.get('catalog_name')
    quote_id = request.form.get('quote_id') 
    file = request.files.get('csv_file')
    
    if file and file.filename.endswith('.csv'):
        filename = secure_filename(file.filename)
        data = list(csv.reader(StringIO(file.stream.read().decode("UTF8"), newline=None)))
        if len(data) > 0:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT INTO catalogs (user_id, name, headers, rows) VALUES (%s, %s, %s, %s)', (session['user_id'], catalog_name, json.dumps(data[0]), json.dumps(data[1:]))
            )
            conn.commit()
            cursor.close()
            conn.close()
            
    if quote_id:
        return redirect(url_for('editor', quote_id=quote_id))
    return redirect(url_for('dashboard'))

@app.route('/get_catalog/<int:catalog_id>')
def get_catalog(catalog_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT headers, rows FROM catalogs WHERE id = %s', (catalog_id,))
    catalog = cursor.fetchone()
    cursor.close()
    conn.close()
    if catalog:
        return jsonify({'status': 'success', 'data': {'headers': catalog['headers'], 'rows': catalog['rows']}})
    return jsonify({'status': 'error'}), 404

@app.route('/delete_catalog/<int:catalog_id>')
def delete_catalog(catalog_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM catalogs WHERE id = %s AND user_id = %s', (catalog_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/verify_password_backend', methods=['POST'])
def verify_password_backend():
    if 'user_id' not in session: return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    data = request.get_json()
    password = data.get('password')
    email = session.get('user_email')
    
    try:
        if supabase and email and password:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            if res and res.session:
                return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Invalid password'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, port=5000)