import os
import threading
import sqlite3
import pandas as pd
from flask import Flask, request, jsonify
try:
    from flask_cors import CORS
    cors_available = True
except ImportError:
    cors_available = False
import requests
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
import datetime
import time
import random
import uuid

# --- Load environment variables ---
load_dotenv()

# --- Flask app setup ---
app = Flask(__name__)
if cors_available:
    CORS(app)

# --- Config ---
DB_FILE = 'backend/email_log.db'
UPLOAD_FOLDER = 'backend/uploads'
OLLAMA_URL = 'http://localhost:11434/api/generate'
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT', 465))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
LLAMA3_MODEL = 'llama3'

PROMPT_TEMPLATE = '''
You are helping me generate a catchy, concise, and visually appealing cold email for my digital agency, PixelSolve.

You will receive rows of business data from an Excel file. Each row contains the following columns:
- Business Name
- Type
- LOCATION (City, Country)  # This is a single field, e.g., 'Austin, USA'.
- Email
- WhatsApp
- Has Website (Yes/No)
- Instagram Presence (Yes/No)
- Personalized Hook / Observation

Your task is to generate an email using the following template. Replace [BUSINESS NAME] with the actual business name and [LOCATION] with the provided LOCATION field. Never output [City] or [Country] placeholders—always use the LOCATION field as provided.

---
Subject: [Write a subject line that instantly grabs attention and curiosity, e.g., "Boost [BUSINESS NAME]'s Online Reach with a Loyalty App & More ☕️🚀"]

Hi [BUSINESS NAME] Team,

[Write an opening line that immediately makes the reader interested and curious about the opportunity.]

I recently came across your café in [LOCATION] and was impressed by your vibe and strong Instagram presence. Your customers clearly love what you do!

[Optionally, add a personalized hook/observation here.]

At PixelSolve, we help coffee shops like yours grow with:
• Branded Loyalty Apps – Reward loyal customers and boost repeat visits 🎉  
• Mobile Ordering – Make it easy for customers to order and pay 📱  
• Local Influencer Marketing – Get your brand noticed by more people 🚀

Many cafés have seen 30–50% more engagement with these solutions.

Open to a quick demo? Even a short reply is welcome.

Best regards,  
The PixelSolve Team  
www.pixelsolve.co  
---

Rules:
- Output ONLY the email, starting from the Subject line and ending at www.pixelsolve.co.
- Do NOT write any extra words, commentary, or explanation before or after the email.
- The output must start with the subject and end with www.pixelsolve.co, nothing else.
- Use 2–3 relevant, friendly emojis (e.g., ☕️, 🚀, 📱, 🎉) in the subject or bullet points only.
- Do NOT use bold or markdown formatting.
- Make the subject and opening lines as attention-grabbing and curiosity-inducing as possible for a business owner.
- Keep the email concise (max 120 words), direct, and catchy. Focus on benefits and a friendly, energetic tone.
- Use [LOCATION] exactly as provided in the data block. Never output [City] or [Country] placeholders—always use the LOCATION field as provided.

Now, using the data below, generate the email as specified above. Output only the email, nothing else.
'''

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- SQLite Setup ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        business_type TEXT,
        status TEXT,
        model_output TEXT,
        error TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        session_id TEXT
    )''')
    # New table for sent log
    c.execute('''CREATE TABLE IF NOT EXISTS sent_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        subject TEXT,
        body TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()
init_db()

# --- In-memory progress cache ---
progress_cache = {
    'total': 0,
    'done': 0,
    'emails': {},  # email: {name, business, model_output, status, error}
    'status': 'idle',
    'error': '',
    'filename': '',
    'message': '',
    'batch_total': 0,
    'batch_current': 0,
    'wait_time': 0,
    'current_session_id': None
}

# --- Helper: Extract email from contact field ---
def extract_email(contact):
    if not isinstance(contact, str):
        return ''
    import re
    match = re.search(r'[\w\.-]+@[\w\.-]+', contact)
    return match.group(0) if match else ''

# --- Helper: Generate prompt for a recipient ---
def build_prompt(recipient):
    # Build the data block with LOCATION as a single field
    location = f"{recipient.get('City', '').strip()}, {recipient.get('Country', '').strip()}".strip(', ')
    data_block = f"""
Business Name: {recipient.get('Business Name', '')}
Type: {recipient.get('Type', '')}
LOCATION: {location}
Email: {recipient.get('Email', '')}
WhatsApp: {recipient.get('WhatsApp', '')}
Has Website: {recipient.get('Has Website', '')}
Instagram Presence: {recipient.get('Instagram Presence', '')}
Personalized Hook / Observation: {recipient.get('Personalized Hook / Observation', '')}
"""
    return PROMPT_TEMPLATE + data_block

# --- AI Email Generation ---
def generate_email_with_llama3(recipient):
    def contains_placeholder(text):
        import re
        # Check for [Location], [LOCATION], [City], [Country] (case-insensitive)
        return bool(re.search(r'\[(location|city|country)\]', text, re.IGNORECASE))

    prompt = build_prompt(recipient)
    max_attempts = 3
    attempt = 0
    extra_instruction = ("\nIMPORTANT: If you are about to use a placeholder like [Location], [LOCATION], [City], or [Country], instead use the real location provided in the data, or omit the location if not available. Never output any placeholder in the email. Regenerate the email accordingly.\n")
    last_result = ''
    last_error = None
    while attempt < max_attempts:
        try:
            this_prompt = prompt
            if attempt > 0:
                # Add extra instruction for subsequent attempts
                this_prompt = PROMPT_TEMPLATE + "\n" + extra_instruction + build_prompt(recipient).split(PROMPT_TEMPLATE, 1)[-1]
            response = requests.post(
                OLLAMA_URL,
                json={'model': LLAMA3_MODEL, 'prompt': this_prompt, 'stream': False},
                timeout=90
            )
            result = response.json().get('response', '')
            last_result = result
            last_error = None
            if not contains_placeholder(result):
                return result, None
        except Exception as e:
            last_result = ''
            last_error = f"[AI GENERATION ERROR: {e}]"
            break
        attempt += 1
    # If we reach here, either error or still contains placeholder after max attempts
    if last_result and contains_placeholder(last_result):
        last_error = '[AI GENERATION ERROR: Placeholder like [Location] still present after retries.]'
    return last_result, last_error

# --- Helper: Generate a new session ID ---
def generate_session_id():
    return str(uuid.uuid4())

# --- API Endpoints ---
@app.route('/api/upload', methods=['POST'])
def upload_excel():
    file = request.files.get('file')
    if not file or not file.filename.endswith('.xlsx'):
        return jsonify({'error': 'Invalid file type'}), 400
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)
    df = pd.read_excel(filepath, engine='openpyxl')
    recipients = []
    seen_emails = set()
    session_id = generate_session_id()
    # Connect to DB to check for already sent/ready emails
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT email FROM emails WHERE status IN ("SENT", "Ready")')
    already_in_db = set(row[0].lower() for row in c.fetchall() if row[0])
    conn.close()
    for _, row in df.iterrows():
        r = {k.strip(): str(row.get(k, '')).strip() for k in df.columns}
        r['Email'] = r.get('Email', extract_email(r.get('Contact', '')))
        email = r['Email'].lower()
        # Skip if email is missing, empty, nan, duplicate in file, or already in db
        if not email or email == 'nan' or email in seen_emails or email in already_in_db:
            continue
        seen_emails.add(email)
        r['session_id'] = session_id
        recipients.append(r)
    progress_cache['filename'] = file.filename
    progress_cache['message'] = f"File '{file.filename}' uploaded. {len(recipients)} unique, valid emails will be generated and sent."
    progress_cache['current_session_id'] = session_id
    thread = threading.Thread(target=background_generate_emails, args=(recipients, session_id), daemon=True)
    thread.start()
    return jsonify({'status': 'started', 'total': len(recipients), 'filename': file.filename, 'message': progress_cache['message'], 'session_id': session_id})

@app.route('/api/progress', methods=['GET'])
def get_progress():
    try:
        return jsonify(progress_cache)
    except Exception as e:
        return jsonify({'total': 0, 'done': 0, 'emails': {}, 'status': 'error', 'error': str(e)})

# --- Background Thread for AI Generation ---
def background_generate_emails(recipients, session_id):
    progress_cache['status'] = 'generating'
    progress_cache['done'] = 0
    progress_cache['total'] = len(recipients)
    progress_cache['emails'] = {}
    progress_cache['error'] = ''
    for r in recipients:
        email = r['Email']
        name = r.get('Business Name', '')
        business = r.get('Type', '')
        model_output, error = generate_email_with_llama3(r)
        status = 'Ready' if not error else 'FAILED'
        progress_cache['emails'][email] = {
            'name': name,
            'business': business,
            'model_output': model_output,
            'status': status,
            'error': error or ''
        }
        # Save to DB with session_id
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''INSERT INTO emails (name, email, business_type, status, model_output, error, session_id) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (name, email, business, status, model_output, error or '', session_id))
        conn.commit()
        conn.close()
        progress_cache['done'] += 1
    progress_cache['status'] = 'done'

# --- Email Sending Logic ---
@app.route('/api/send', methods=['POST'])
def send_emails():
    data = request.get_json(silent=True) or {}
    batch_size = int(data.get('batch_size', 10))
    delay_min = int(data.get('delay_min', 8))
    delay_max = int(data.get('delay_max', 15))
    session_id = data.get('session_id') or progress_cache.get('current_session_id')
    if not session_id:
        return jsonify({'error': 'No session_id provided or found.'}), 400
    thread = threading.Thread(target=send_all_emails, args=(batch_size, (delay_min, delay_max), session_id), daemon=True)
    thread.start()
    return jsonify({'status': 'sending', 'batch_size': batch_size, 'delay_range': [delay_min, delay_max], 'session_id': session_id})

def send_all_emails(batch_size=10, delay_range=(8, 15), session_id=None):
    progress_cache['status'] = 'sending'
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if session_id:
        c.execute('SELECT name, email, business_type, model_output FROM emails WHERE status = "Ready" AND session_id = ?', (session_id,))
    else:
        c.execute('SELECT name, email, business_type, model_output FROM emails WHERE status = "Ready"')
    rows = c.fetchall()
    total = len(rows)
    batches = [rows[i:i+batch_size] for i in range(0, total, batch_size)]
    progress_cache['batch_total'] = len(batches)
    progress_cache['batch_current'] = 0
    import re  # For post-processing
    sent_emails = set()
    for batch_num, batch in enumerate(batches, 1):
        progress_cache['batch_current'] = batch_num
        for row in batch:
            name, email, business, model_output = row
            if email in sent_emails:
                continue  # Deduplicate within session
            sent_emails.add(email)
            try:
                lines = model_output.splitlines()
                subject_line = next((l for l in lines if l.strip().lower().startswith('subject:')), lines[0] if lines else 'PixelSolve Cold Email')
                subject = subject_line.replace('**', '').replace('Subject:', '').strip()
                body_start = next((i for i, l in enumerate(lines) if l.strip().lower().startswith('hi') or l.strip().lower().startswith('hello')), 1)
                body = '\n'.join(lines[body_start:]).lstrip('\n')
                # Post-process: remove 'in ,' or 'in  ' (with nothing after 'in')
                body = re.sub(r'\bin\s*,', '', body)
                body = re.sub(r'\bin\s+$', '', body)
                # Post-process: ensure 'with:' is always followed by a newline
                body = re.sub(r'(with:)\s*', r'\1\n', body)
                msg = MIMEText(body, 'plain')
                msg['Subject'] = subject
                msg['From'] = formataddr(("The PixelSolve Team", SMTP_USER))
                msg['To'] = email
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                    server.sendmail(SMTP_USER, [email], msg.as_string())
                status, error = 'SENT', ''
                # Log sent email after successful send
                c.execute('''INSERT INTO sent_log (name, email, subject, body) VALUES (?, ?, ?, ?)''', (name, email, subject, body))
                conn.commit()
            except Exception as e:
                if 'rate' in str(e).lower() or 'limit' in str(e).lower():
                    progress_cache['status'] = 'rate_limited_waiting'
                    time.sleep(60)
                    continue
                status, error = 'FAILED', str(e)
            c.execute('UPDATE emails SET status=?, error=? WHERE email=? AND model_output=?', (status, error, email, model_output))
            conn.commit()
            if email in progress_cache['emails']:
                progress_cache['emails'][email]['status'] = status
                progress_cache['emails'][email]['error'] = error
        if batch_num < len(batches):
            progress_cache['status'] = f'waiting_batch_{batch_num}'
            wait_time = random.randint(*delay_range)
            progress_cache['wait_time'] = wait_time
            time.sleep(wait_time)
            progress_cache['status'] = 'sending'
    conn.close()
    progress_cache['status'] = 'done'
    progress_cache['batch_current'] = progress_cache['batch_total']
    progress_cache['wait_time'] = 0

def retry_failed_emails(batch_size=10, delay_range=(8, 15)):
    progress_cache['status'] = 'retrying'
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT name, email, business_type, model_output FROM emails WHERE status = "FAILED"')
    rows = c.fetchall()
    total = len(rows)
    batches = [rows[i:i+batch_size] for i in range(0, total, batch_size)]
    progress_cache['batch_total'] = len(batches)
    progress_cache['batch_current'] = 0
    retried = []
    import re  # For post-processing
    for batch_num, batch in enumerate(batches, 1):
        progress_cache['batch_current'] = batch_num
        for row in batch:
            name, email, business, model_output = row
            try:
                lines = model_output.splitlines()
                subject_line = next((l for l in lines if l.strip().lower().startswith('subject:')), lines[0] if lines else 'PixelSolve Cold Email')
                subject = subject_line.replace('**', '').replace('Subject:', '').strip()
                body_start = next((i for i, l in enumerate(lines) if l.strip().lower().startswith('hi') or l.strip().lower().startswith('hello')), 1)
                body = '\n'.join(lines[body_start:]).lstrip('\n')
                # Post-process: remove 'in ,' or 'in  ' (with nothing after 'in')
                body = re.sub(r'\bin\s*,', '', body)
                body = re.sub(r'\bin\s+$', '', body)
                # Post-process: ensure 'with:' is always followed by a newline
                body = re.sub(r'(with:)\s*', r'\1\n', body)
                msg = MIMEText(body, 'plain')
                msg['Subject'] = subject
                msg['From'] = formataddr(("The PixelSolve Team", SMTP_USER))
                msg['To'] = email
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                    server.sendmail(SMTP_USER, [email], msg.as_string())
                status, error = 'SENT', ''
            except Exception as e:
                if 'rate' in str(e).lower() or 'limit' in str(e).lower():
                    progress_cache['status'] = 'rate_limited_waiting'
                    time.sleep(60)
                    continue
                status, error = 'FAILED', str(e)
            c.execute('UPDATE emails SET status=?, error=? WHERE email=? AND model_output=?', (status, error, email, model_output))
            conn.commit()
            if email in progress_cache['emails']:
                progress_cache['emails'][email]['status'] = status
                progress_cache['emails'][email]['error'] = error
        if batch_num < len(batches):
            progress_cache['status'] = f'waiting_batch_{batch_num}'
            wait_time = random.randint(*delay_range)
            progress_cache['wait_time'] = wait_time
            time.sleep(wait_time)
            progress_cache['status'] = 'retrying'
    conn.close()
    progress_cache['status'] = 'done'
    progress_cache['batch_current'] = progress_cache['batch_total']
    progress_cache['wait_time'] = 0
    return retried

# --- Resend Endpoint ---
@app.route('/api/resend', methods=['POST'])
def resend_emails():
    data = request.get_json(silent=True) or {}
    batch_size = int(data.get('batch_size', 10))
    delay_min = int(data.get('delay_min', 8))
    delay_max = int(data.get('delay_max', 15))
    resend_to = data.get('emails')  # List of emails to resend to
    if not resend_to:
        return jsonify({'error': 'No emails provided for resend.'}), 400
    thread = threading.Thread(target=send_resend_emails, args=(batch_size, (delay_min, delay_max), resend_to), daemon=True)
    thread.start()
    return jsonify({'status': 'resending', 'batch_size': batch_size, 'delay_range': [delay_min, delay_max], 'emails': resend_to})

def send_resend_emails(batch_size, delay_range, resend_to):
    progress_cache['status'] = 'resending'
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    placeholders = ','.join('?' for _ in resend_to)
    c.execute(f'SELECT name, email, business_type, model_output FROM emails WHERE email IN ({placeholders}) AND status = "SENT"', tuple(resend_to))
    rows = c.fetchall()
    total = len(rows)
    batches = [rows[i:i+batch_size] for i in range(0, total, batch_size)]
    progress_cache['batch_total'] = len(batches)
    progress_cache['batch_current'] = 0
    import re
    for batch_num, batch in enumerate(batches, 1):
        progress_cache['batch_current'] = batch_num
        for row in batch:
            name, email, business, model_output = row
            try:
                lines = model_output.splitlines()
                subject_line = next((l for l in lines if l.strip().lower().startswith('subject:')), lines[0] if lines else 'PixelSolve Cold Email')
                subject = subject_line.replace('**', '').replace('Subject:', '').strip()
                body_start = next((i for i, l in enumerate(lines) if l.strip().lower().startswith('hi') or l.strip().lower().startswith('hello')), 1)
                body = '\n'.join(lines[body_start:]).lstrip('\n')
                body = re.sub(r'\bin\s*,', '', body)
                body = re.sub(r'\bin\s+$', '', body)
                body = re.sub(r'(with:)\s*', r'\1\n', body)
                msg = MIMEText(body, 'plain')
                msg['Subject'] = subject
                msg['From'] = formataddr(("The PixelSolve Team", SMTP_USER))
                msg['To'] = email
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                    server.sendmail(SMTP_USER, [email], msg.as_string())
                status, error = 'RESENT', ''
            except Exception as e:
                status, error = 'FAILED', str(e)
            c.execute('UPDATE emails SET status=?, error=? WHERE email=? AND model_output=?', (status, error, email, model_output))
            conn.commit()
        if batch_num < len(batches):
            progress_cache['status'] = f'waiting_batch_{batch_num}'
            wait_time = random.randint(*delay_range)
            progress_cache['wait_time'] = wait_time
            time.sleep(wait_time)
            progress_cache['status'] = 'resending'
    conn.close()
    progress_cache['status'] = 'done'
    progress_cache['batch_current'] = progress_cache['batch_total']
    progress_cache['wait_time'] = 0

# --- API Endpoints ---
@app.route('/api/retry_failed', methods=['POST'])
def retry_failed_emails_api():
    data = request.get_json(silent=True) or {}
    batch_size = int(data.get('batch_size', 10))
    delay_min = int(data.get('delay_min', 8))
    delay_max = int(data.get('delay_max', 15))
    def run():
        retried = retry_failed_emails(batch_size, (delay_min, delay_max))
        return retried
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return jsonify({'status': 'retrying', 'batch_size': batch_size, 'delay_range': [delay_min, delay_max]})

@app.route('/api/logs', methods=['GET'])
def get_logs():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT name, email, business_type, status, model_output, error, sent_at FROM emails ORDER BY sent_at DESC LIMIT 100')
    rows = c.fetchall()
    conn.close()
    logs = [dict(zip(['name','email','business_type','status','model_output','error','sent_at'], row)) for row in rows]
    return jsonify({'logs': logs})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Total sent today
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    c.execute("SELECT COUNT(*) FROM sent_log WHERE DATE(sent_at)=?", (today,))
    total_sent_today = c.fetchone()[0]
    # Total sent all time
    c.execute("SELECT COUNT(*) FROM sent_log")
    total_sent_all = c.fetchone()[0]
    # Breakdown by country (top 5)
    c.execute("SELECT body FROM sent_log")
    country_counts = {}
    business_type_counts = {}
    top_recipients_by_country = []
    for row in c.fetchall():
        body = row[0]
        # Try to extract country and business type from body (fallback: unknown)
        country = 'Unknown'
        business_type = 'Unknown'
        lines = body.split('\n')
        for l in lines:
            if 'café in' in l or 'coffee shop in' in l:
                parts = l.split(' in ')
                if len(parts) > 1:
                    loc = parts[1].split(' and')[0].split(',')
                    if len(loc) > 1:
                        country = loc[-1].strip()
                    else:
                        country = loc[0].strip()
            if 'help coffee shops like yours' in l or 'help businesses like yours' in l:
                if 'coffee shop' in l:
                    business_type = 'Coffee Shop'
                elif 'café' in l:
                    business_type = 'Café'
                elif 'restaurant' in l:
                    business_type = 'Restaurant'
        country_counts[country] = country_counts.get(country, 0) + 1
        business_type_counts[business_type] = business_type_counts.get(business_type, 0) + 1
    # Top 5 countries and business types
    countries = sorted(country_counts.items(), key=lambda x: -x[1])[:5]
    business_types = sorted(business_type_counts.items(), key=lambda x: -x[1])[:5]
    # Top recipients by country (first 5 unique)
    c.execute("SELECT email, body FROM sent_log")
    seen = set()
    for email, body in c.fetchall():
        country = 'Unknown'
        lines = body.split('\n')
        for l in lines:
            if 'café in' in l or 'coffee shop in' in l:
                parts = l.split(' in ')
                if len(parts) > 1:
                    loc = parts[1].split(' and')[0].split(',')
                    if len(loc) > 1:
                        country = loc[-1].strip()
                    else:
                        country = loc[0].strip()
        if (email, country) not in seen:
            top_recipients_by_country.append((email, country))
            seen.add((email, country))
        if len(top_recipients_by_country) >= 5:
            break
    conn.close()
    return jsonify({
        'total_sent_today': total_sent_today,
        'total_sent_all': total_sent_all,
        'countries': countries,
        'business_types': business_types,
        'top_recipients_by_country': top_recipients_by_country
    })

if __name__ == '__main__':
    app.run(debug=True, port=5050) 