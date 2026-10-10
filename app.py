import os
import csv
import json
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = "quostudio_super_secret_key"

# ==========================================
# DATABASE CONNECTION & SETUP
# ==========================================

def get_db_connection():
    supabase_url = "postgresql://postgres:Rudhrapatel15*@db.ureklqoahnubcxzqjynd.supabase.co:5432/postgres"
    return psycopg2.connect(supabase_url, cursor_factory=psycopg2.extras.RealDictCursor)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Users Table (Updated with username, company, avatar)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            username VARCHAR(255) UNIQUE NOT NULL,
            company_name VARCHAR(255),
            password VARCHAR(255) NOT NULL,
            avatar_url TEXT
        )
    ''')
    
    # 2. Quotations Table (Updated with recipient tracking, status, and signatures)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quotations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            recipient_id INTEGER REFERENCES users(id),
            client_name VARCHAR(255) NOT NULL,
            document_data TEXT,
            status VARCHAR(50) DEFAULT 'draft',
            signature_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 3. Catalogs Table
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

    # 4. Client History / Ecosystem Connections
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_history (
            sender_id INTEGER REFERENCES users(id),
            recipient_id INTEGER REFERENCES users(id),
            last_sent TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (sender_id, recipient_id)
        )
    ''')
    
    # Schema Migration for existing DBs (Fails safely if columns exist)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(255) UNIQUE;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS company_name VARCHAR(255);")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;")
        cursor.execute("ALTER TABLE quotations ADD COLUMN IF NOT EXISTS recipient_id INTEGER REFERENCES users(id);")
        cursor.execute("ALTER TABLE quotations ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'draft';")
        cursor.execute("ALTER TABLE quotations ADD COLUMN IF NOT EXISTS signature_data TEXT;")
    except:
        pass
        
    conn.commit()
    cursor.close()
    conn.close()

init_db()

# ==========================================
# AUTHENTICATION
# ==========================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        action = request.form.get('action')
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            if action == 'login':
                cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
                user = cursor.fetchone()
                if user and user['password'] == password:
                    session['user_id'] = user['id']
                    session['user_email'] = user['email']
                    session['username'] = user.get('username', '')
                    session['company_name'] = user.get('company_name', '')
                    return redirect(url_for('dashboard'))
                else:
                    flash("Invalid credentials.")
            
            elif action == 'signup':
                username = request.form.get('username')
                company = request.form.get('company_name')
                
                cursor.execute(
                    'INSERT INTO users (email, username, company_name, password) VALUES (%s, %s, %s, %s) RETURNING id',
                    (email, username, company, password)
                )
                new_id = cursor.fetchone()['id']
                conn.commit()
                
                session['user_id'] = new_id
                session['user_email'] = email
                session['username'] = username
                session['company_name'] = company
                return redirect(url_for('dashboard'))
                
        except Exception as e:
            flash(f"Error: {str(e)}")
        finally:
            cursor.close()
            conn.close()
            
        return redirect(url_for('auth'))
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth'))

# ==========================================
# DASHBOARD & MAILBOX
# ==========================================

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('auth'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # User Profile Data
    cursor.execute('SELECT username, company_name, avatar_url FROM users WHERE id = %s', (user_id,))
    user_profile = cursor.fetchone()
    
    # 1. My Quotes (Created by user)
    cursor.execute('''
        SELECT q.id, q.client_name, q.status, q.created_at, u.username as recipient_name 
        FROM quotations q 
        LEFT JOIN users u ON q.recipient_id = u.id 
        WHERE q.user_id = %s ORDER BY q.created_at DESC
    ''', (user_id,))
    my_quotes = cursor.fetchall()
    
    # 2. Inbox (Quotes sent to this user)
    cursor.execute('''
        SELECT q.id, q.client_name, q.status, q.created_at, u.username as sender_name, u.company_name as sender_company
        FROM quotations q 
        JOIN users u ON q.user_id = u.id 
        WHERE q.recipient_id = %s ORDER BY q.created_at DESC
    ''', (user_id,))
    inbox = cursor.fetchall()
    
    # 3. Catalogs
    cursor.execute('SELECT id, name FROM catalogs WHERE user_id = %s ORDER BY created_at DESC', (user_id,))
    catalogs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    # Generate Initials
    initials = "".join([w[0].upper() for w in user_profile['username'].split()[:2]]) if user_profile['username'] else "Q"
    
    return render_template('dashboard.html', 
                           my_quotes=my_quotes, 
                           inbox=inbox, 
                           catalogs=catalogs,
                           profile=user_profile,
                           initials=initials)

# ==========================================
# EDITOR & QUOTE MANAGEMENT
# ==========================================

@app.route('/new_quotation', methods=['POST'])
def new_quotation():
    if 'user_id' not in session: return redirect(url_for('auth'))
    
    client_name = request.form.get('client_name')
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
    
    return redirect(url_for('editor', quote_id=new_quote_id))

@app.route('/editor/<int:quote_id>')
def editor(quote_id):
    if 'user_id' not in session: return redirect(url_for('auth'))
    
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM quotations WHERE id = %s', (quote_id,))
    quote = cursor.fetchone()
    
    if not quote:
        return redirect(url_for('dashboard'))
        
    # Determine authorization and view mode
    is_owner = (quote['user_id'] == user_id)
    is_recipient = (quote['recipient_id'] == user_id)
    
    if not is_owner and not is_recipient:
        return redirect(url_for('dashboard'))
        
    cursor.execute('SELECT id, name FROM catalogs WHERE user_id = %s ORDER BY name ASC', (quote['user_id'],))
    catalogs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('editor.html', quote=quote, catalogs=catalogs, is_owner=is_owner, is_recipient=is_recipient)

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

# ==========================================
# ECOSYSTEM: DIRECTORY, SENDING & SIGNING
# ==========================================

@app.route('/search_users')
def search_users():
    if 'user_id' not in session: return jsonify([])
    query = request.args.get('q', '').lower()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get history first
    if not query:
        cursor.execute('''
            SELECT u.id, u.username, u.email, u.company_name 
            FROM client_history ch
            JOIN users u ON ch.recipient_id = u.id
            WHERE ch.sender_id = %s
            ORDER BY ch.last_sent DESC LIMIT 5
        ''', (session['user_id'],))
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
    
    # Update quote
    cursor.execute(
        "UPDATE quotations SET recipient_id = %s, status = 'sent' WHERE id = %s AND user_id = %s",
        (recipient_id, quote_id, sender_id)
    )
    
    # Update ecosystem history
    cursor.execute('''
        INSERT INTO client_history (sender_id, recipient_id) 
        VALUES (%s, %s) 
        ON CONFLICT (sender_id, recipient_id) 
        DO UPDATE SET last_sent = CURRENT_TIMESTAMP
    ''', (sender_id, recipient_id))
    
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/accept_quote/<int:quote_id>', methods=['POST'])
def accept_quote(quote_id):
    if 'user_id' not in session: return jsonify({'status': 'error'}), 401
    
    signature = request.json.get('signature')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE quotations SET status = 'accepted', signature_data = %s WHERE id = %s AND recipient_id = %s",
        (signature, quote_id, session['user_id'])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'success'})

# ==========================================
# INVENTORY ROUTES
# ==========================================

@app.route('/upload_catalog', methods=['POST'])
def upload_catalog():
    if 'user_id' not in session: return redirect(url_for('auth'))
    catalog_name = request.form.get('catalog_name')
    file = request.files.get('csv_file')
    if file and file.filename.endswith('.csv'):
        data = list(csv.reader(StringIO(file.stream.read().decode("UTF8"), newline=None)))
        if len(data) > 0:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO catalogs (user_id, name, headers, rows) VALUES (%s, %s, %s, %s)',
                (session['user_id'], catalog_name, json.dumps(data[0]), json.dumps(data[1:]))
            )
            conn.commit()
            cursor.close()
            conn.close()
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)