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
    'message': ''
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
    prompt = build_prompt(recipient)
    try:
        response = requests.post(
            OLLAMA_URL,
            json={'model': LLAMA3_MODEL, 'prompt': prompt, 'stream': False},
            timeout=90
        )
        result = response.json().get('response', '')
        return result, None
    except Exception as e:
        return '', f"[AI GENERATION ERROR: {e}]"

# --- Background Thread for AI Generation ---
def background_generate_emails(recipients):
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
        # Save to DB
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''INSERT INTO emails (name, email, business_type, status, model_output, error) VALUES (?, ?, ?, ?, ?, ?)''',
                  (name, email, business, status, model_output, error or ''))
        conn.commit()
        conn.close()
        progress_cache['done'] += 1
    progress_cache['status'] = 'done'

# --- Email Sending Logic ---
def send_all_emails():
    progress_cache['status'] = 'sending'
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT name, email, business_type, model_output FROM emails WHERE status = "Ready"')
    rows = c.fetchall()
    for row in rows:
        name, email, business, model_output = row
        try:
            lines = model_output.splitlines()
            # Find the subject line (first line starting with 'Subject:')
            subject_line = next((l for l in lines if l.strip().lower().startswith('subject:')), lines[0] if lines else 'PixelSolve Cold Email')
            subject = subject_line.replace('**', '').replace('Subject:', '').strip()
            # Find the first line that starts with 'Hi' or 'Hello' (case-insensitive)
            body_start = next((i for i, l in enumerate(lines) if l.strip().lower().startswith('hi') or l.strip().lower().startswith('hello')), 1)
            body = '\n'.join(lines[body_start:]).lstrip('\n')
            msg = MIMEText(body, 'plain')
            msg['Subject'] = subject
            msg['From'] = formataddr(("The PixelSolve Team", SMTP_USER))
            msg['To'] = email
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, [email], msg.as_string())
            status, error = 'SENT', ''
        except Exception as e:
            status, error = 'FAILED', str(e)
        c.execute('UPDATE emails SET status=?, error=? WHERE email=? AND model_output=?', (status, error, email, model_output))
        conn.commit()
        # Update in-memory cache
        if email in progress_cache['emails']:
            progress_cache['emails'][email]['status'] = status
            progress_cache['emails'][email]['error'] = error
    conn.close()
    progress_cache['status'] = 'done'

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
    for _, row in df.iterrows():
        r = {k.strip(): str(row.get(k, '')).strip() for k in df.columns}
        # Standardize keys for downstream logic
        r['Email'] = r.get('Email', extract_email(r.get('Contact', '')))
        recipients.append(r)
    progress_cache['filename'] = file.filename
    progress_cache['message'] = f"File '{file.filename}' uploaded. Generating emails..."
    thread = threading.Thread(target=background_generate_emails, args=(recipients,), daemon=True)
    thread.start()
    return jsonify({'status': 'started', 'total': len(recipients), 'filename': file.filename, 'message': progress_cache['message']})

@app.route('/api/progress', methods=['GET'])
def get_progress():
    try:
        return jsonify(progress_cache)
    except Exception as e:
        return jsonify({'total': 0, 'done': 0, 'emails': {}, 'status': 'error', 'error': str(e)})

@app.route('/api/send', methods=['POST'])
def send_emails():
    thread = threading.Thread(target=send_all_emails, daemon=True)
    thread.start()
    return jsonify({'status': 'sending'})

@app.route('/api/logs', methods=['GET'])
def get_logs():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT name, email, business_type, status, model_output, error, sent_at FROM emails ORDER BY sent_at DESC LIMIT 100')
    rows = c.fetchall()
    conn.close()
    logs = [dict(zip(['name','email','business_type','status','model_output','error','sent_at'], row)) for row in rows]
    return jsonify({'logs': logs})

@app.route('/api/retry_failed', methods=['POST'])
def retry_failed_emails():
    progress_cache['status'] = 'retrying'
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT name, email, business_type, model_output FROM emails WHERE status = "FAILED"')
    rows = c.fetchall()
    retried = []
    for row in rows:
        name, email, business, model_output = row
        try:
            lines = model_output.splitlines()
            subject_line = next((l for l in lines if l.strip().lower().startswith('subject:')), lines[0] if lines else 'PixelSolve Cold Email')
            subject = subject_line.replace('**', '').replace('Subject:', '').strip()
            body_start = next((i for i, l in enumerate(lines) if l.strip().lower().startswith('hi') or l.strip().lower().startswith('hello')), 1)
            body = '\n'.join(lines[body_start:]).lstrip('\n')
            msg = MIMEText(body, 'plain')
            msg['Subject'] = subject
            msg['From'] = formataddr(("The PixelSolve Team", SMTP_USER))
            msg['To'] = email
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, [email], msg.as_string())
            status, error = 'SENT', ''
        except Exception as e:
            status, error = 'FAILED', str(e)
        c.execute('UPDATE emails SET status=?, error=? WHERE email=? AND model_output=?', (status, error, email, model_output))
        conn.commit()
        retried.append(email)
        if email in progress_cache['emails']:
            progress_cache['emails'][email]['status'] = status
            progress_cache['emails'][email]['error'] = error
    conn.close()
    progress_cache['status'] = 'done'
    return jsonify({'retried': len(retried), 'emails': retried})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Total sent today
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    c.execute("SELECT COUNT(*) FROM emails WHERE status='SENT' AND DATE(sent_at)=?", (today,))
    total_sent_today = c.fetchone()[0]
    # Total sent all time
    c.execute("SELECT COUNT(*) FROM emails WHERE status='SENT'")
    total_sent_all = c.fetchone()[0]
    # Breakdown by country (top 5)
    c.execute("SELECT model_output FROM emails WHERE status='SENT'")
    country_counts = {}
    business_type_counts = {}
    top_recipients_by_country = []
    for row in c.fetchall():
        model_output = row[0]
        # Try to extract country and business type from model_output (fallback: unknown)
        country = 'Unknown'
        business_type = 'Unknown'
        lines = model_output.split('\n')
        for l in lines:
            if 'café in' in l or 'coffee shop in' in l:
                # e.g., 'I recently came across your café in Austin, USA ...'
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
    c.execute("SELECT email, model_output FROM emails WHERE status='SENT'")
    seen = set()
    for email, model_output in c.fetchall():
        country = 'Unknown'
        lines = model_output.split('\n')
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