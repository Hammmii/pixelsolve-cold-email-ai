from flask import Flask, render_template_string, request, redirect, url_for, jsonify, flash, get_flashed_messages
import sqlite3
import pandas as pd
import os
import threading
import time
import random
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from jinja2 import Template
import smtplib
from dotenv import load_dotenv
import re
import requests

load_dotenv()

app = Flask(__name__)
app.secret_key = 'pixelsolve_secret_key'  # Needed for flash messages
DB_FILE = 'sent_log.db'
RECIPIENTS_FILE = 'recipients.xlsx'
TEMPLATE_FILE = 'templates/email.txt'

SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT'))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')

sending = False
retrying = False
next_send_time = 0
cooldown_until = 0

# AI-powered email generation using Ollama
ollama_url = 'http://localhost:11434/api/generate'
def generate_email_with_ollama(recipient):
    prompt = f"""
You are an expert cold email copywriter. Write a personalized, persuasive cold email for the following business:

Business Name: {recipient.get('Business Name', '')}
Type: {recipient.get('Type', '')}
Location: {recipient.get('Location', '')}
Contact Info: {recipient.get('Contact', '')}
Notes: {recipient.get('Notes', '')}
Opportunity: {recipient.get('Opportunity / Cold Email Pitch', '')}
Potential Client Info: {recipient.get('Potential Client or not', '')}

Instructions:
- The email should be warm, professional, and tailored to the business.
- Start with a compelling, value-driven subject line (not generic).
- Use a friendly greeting.
- Reference something specific about their business (location, social presence, etc.).
- Clearly state the opportunity or value you can offer.
- Use bullet points for key benefits, and bold the most important words or phrases using **double asterisks**.
- Add a line of social proof if possible (e.g., “Many cafés we’ve worked with have seen 30–50% growth…”).
- End with a clear, low-pressure call to action (e.g., “Would you be open to a quick call or demo?”).
- Use this signature:
Best regards,
PixelSolve Team
www.pixelsolve.co

Output format:
Subject: [subject line]
Body:
[email body]
"""
    try:
        response = requests.post(
            ollama_url,
            json={'model': 'llama2', 'prompt': prompt, 'stream': False},
            timeout=60
        )
        result = response.json().get('response', '')
        subject = ""
        body = ""
        if "Subject:" in result and "Body:" in result:
            subject = result.split("Subject:")[1].split("Body:")[0].strip()
            body = result.split("Body:")[1].strip()
        else:
            body = result.strip()
        return subject, body
    except Exception as e:
        # Fallback: simple template with warning
        subject = "[AI ERROR] Cold Email"
        body = f"[AI GENERATION ERROR: {e}]\n\nHi {{name}},\n\nWe help businesses like yours grow online. Would you like to see how?\n\nBest,\nPixelSolve Team"
        return subject, body

def extract_email(contact):
    if not isinstance(contact, str):
        return ''
    match = re.search(r'[\w\.-]+@[\w\.-]+', contact)
    return match.group(0) if match else ''

# --- Message Generation Logic (shared by dashboard and sender) ---
def generate_subject(recipient):
    business_name = recipient.get('Business Name', recipient.get('name', 'Your Business'))
    business_type = recipient.get('Type', recipient.get('business', '')).lower()
    pitch = recipient.get('Opportunity / Cold Email Pitch', '')
    # Pick the most relevant solution for subject
    if 'coffee' in business_type or 'cafe' in business_type:
        solution = 'Loyalty App & More'
        return f"Boost {business_name}’s Online Reach with a {solution}"
    elif 'gym' in business_type or 'fitness' in business_type:
        solution = 'Digital Membership & Booking'
        return f"Grow {business_name} with {solution} Solutions"
    elif 'e-commerce' in business_type or 'ecommerce' in business_type or 'shop' in business_type:
        solution = 'Online Store & Social Sales'
        return f"Scale {business_name} Sales with {solution}"
    elif 'restaurant' in business_type:
        solution = 'Online Menu & Reservations'
        return f"Modernize {business_name} with {solution}"
    else:
        solution = 'Digital Growth'
        return f"Boost {business_name}’s Online Presence with {solution}"

def generate_message(recipient):
    import re
    def safe_str(val):
        if pd.isna(val):
            return ''
        return str(val)

    business_name = safe_str(recipient.get('Business Name', recipient.get('name', 'there')))
    business_type = safe_str(recipient.get('Type', recipient.get('business', ''))).lower()
    location = safe_str(recipient.get('Location', ''))
    notes = safe_str(recipient.get('Notes', recipient.get('notes', '')))
    pitch = safe_str(recipient.get('Opportunity / Cold Email Pitch', ''))
    potential = safe_str(recipient.get('Potential Client or not', ''))

    # AI-style dynamic intro and value for each business type
    if 'coffee' in business_type or 'cafe' in business_type:
        intro = f"Hi {business_name} Team,\n\nI recently came across your café in {location} and was genuinely impressed by your atmosphere"
        if 'instagram' in notes.lower() or 'instagram' in pitch.lower():
            intro += " and strong Instagram presence."
        else:
            intro += "."
        intro += " It’s clear your customers love what you’re doing!\n\n"
        opportunity = "I also noticed that you don’t currently have a website — which presents a great opportunity to attract even more customers online.\n\n" if 'no website' in notes.lower() or 'no website' in pitch.lower() else ""
        bullets = [
            "• Branded Loyalty Apps – Reward loyal customers and boost repeat visits",
            "• Mobile Ordering – Increase convenience and drive more sales",
            "• Local Influencer Marketing – Amplify your brand and reach new audiences"
        ]
        value_block = "At PixelSolve, we help coffee shops like yours grow their digital presence through:\n\n" + '\n'.join(bullets) + '\n\n'
        social_proof = "Many cafés we’ve worked with have seen 30–50% growth in customer engagement using these solutions.\n\n"
    elif 'gym' in business_type or 'fitness' in business_type:
        intro = f"Hi {business_name} Team,\n\nI recently discovered your gym in {location} and was impressed by your community and focus on fitness."
        if 'instagram' in notes.lower() or 'instagram' in pitch.lower():
            intro += " Your Instagram presence is inspiring!"
        intro += "\n\n"
        opportunity = "I noticed you don’t have a digital membership or booking system yet — this could help you attract and retain more members.\n\n" if 'no website' in notes.lower() or 'no website' in pitch.lower() else ""
        bullets = [
            "• Digital Membership Portals – Make signups and renewals easy",
            "• Online Class Booking – Let members reserve spots instantly",
            "• Fitness App Integration – Keep your community engaged"
        ]
        value_block = "At PixelSolve, we help gyms like yours grow with:\n\n" + '\n'.join(bullets) + '\n\n'
        social_proof = "Gyms using these tools have seen 20–40% more bookings and higher member retention.\n\n"
    elif 'e-commerce' in business_type or 'ecommerce' in business_type or 'shop' in business_type:
        intro = f"Hi {business_name} Team,\n\nI recently found your shop in {location} and was impressed by your product range and social media activity."
        intro += "\n\n"
        opportunity = "I noticed you don’t have a full online store yet — this is a great chance to scale your sales beyond DMs.\n\n" if 'no website' in notes.lower() or 'no website' in pitch.lower() else ""
        bullets = [
            "• Custom Online Stores – Showcase and sell your products 24/7",
            "• Social Sales Integration – Convert Instagram followers into buyers",
            "• Order Management Tools – Streamline fulfillment and support"
        ]
        value_block = "At PixelSolve, we help brands like yours grow with:\n\n" + '\n'.join(bullets) + '\n\n'
        social_proof = "Our clients have seen 2x–3x sales growth after launching their online stores.\n\n"
    elif 'restaurant' in business_type:
        intro = f"Hi {business_name} Team,\n\nI recently came across your restaurant in {location} and was impressed by your menu and customer reviews."
        intro += "\n\n"
        opportunity = "I noticed you don’t have an online menu or reservation system — this could help you attract more diners and manage bookings easily.\n\n" if 'no website' in notes.lower() or 'no website' in pitch.lower() else ""
        bullets = [
            "• Online Menus – Let customers browse and order with ease",
            "• Reservation Systems – Fill more tables, reduce no-shows",
            "• Event Booking Pages – Promote special nights and private events"
        ]
        value_block = "At PixelSolve, we help restaurants like yours grow with:\n\n" + '\n'.join(bullets) + '\n\n'
        social_proof = "Restaurants using these tools have seen 25–50% more bookings and higher customer satisfaction.\n\n"
    else:
        intro = f"Hi {business_name} Team,\n\nI recently came across your business in {location} and was impressed by your work.\n\n"
        opportunity = ""
        bullets = [
            "• Custom Websites & Apps – Grow your brand online",
            "• Social Media Tools – Reach and engage more customers",
            "• Booking & CRM Solutions – Streamline your operations"
        ]
        value_block = "At PixelSolve, we help businesses like yours grow with:\n\n" + '\n'.join(bullets) + '\n\n'
        social_proof = "Our clients have seen measurable growth in leads and engagement.\n\n"
    cta = "Would you be open to a quick call or demo? Even a short reply would be appreciated."
    signature = "\n\nBest regards,\nHammad Sikandar\nCo-Founder, PixelSolve\nwww.pixelsolve.co"
    email_body = f"{intro}{opportunity}{value_block}{social_proof}{cta}{signature}"
    return email_body

# --- Email Sending Logic ---
def send_emails_thread(retry_failed=False):
    global sending, retrying, next_send_time, cooldown_until
    sending = True
    df = pd.read_excel(RECIPIENTS_FILE, engine='openpyxl')
    recipients = []
    for _, row in df.iterrows():
        r = row.to_dict()
        # Extract email from Contact
        r['email'] = extract_email(r.get('Contact', ''))
        r['name'] = r.get('Business Name', r.get('name', ''))
        r['business'] = r.get('Type', r.get('business', ''))
        r['notes'] = r.get('Notes', r.get('notes', ''))
        r['Opportunity / Cold Email Pitch'] = r.get('Opportunity / Cold Email Pitch', '')
        r['Potential Client or not'] = r.get('Potential Client or not', '')
        recipients.append(r)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    burst_size = 100
    burst_pause = 720  # 12 minutes
    sent_in_burst = 0
    for idx, r in enumerate(recipients):
        if not sending:
            break
        if not r['email']:
            c.execute('INSERT INTO sent_emails (name, email, status, error) VALUES (?, ?, ?, ?)',
                      (r['name'], '', 'No email', 'No email found in Contact'))
            conn.commit()
            continue
        c.execute('SELECT status FROM sent_emails WHERE email=? ORDER BY sent_at DESC LIMIT 1', (r['email'],))
        row = c.fetchone()
        if retry_failed:
            if not row or row[0] != 'FAILED':
                continue
        else:
            if row and row[0] == 'SENT':
                continue
        msg = MIMEText(generate_message(r))
        msg['Subject'] = generate_subject(r)
        msg['From'] = formataddr(("Hammad from PixelSolve", SMTP_USER))
        msg['To'] = r['email']
        msg['Reply-To'] = SMTP_USER
        msg['X-Priority'] = '1'
        msg['Importance'] = 'High'
        msg['Message-ID'] = make_msgid(domain=SMTP_USER.split('@')[-1])
        msg['List-Unsubscribe'] = f"<mailto:{SMTP_USER}?subject=unsubscribe>"
        try:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, [r['email']], msg.as_string())
            status, error = 'SENT', ''
        except Exception as e:
            status, error = 'FAILED', str(e)
        c.execute('INSERT INTO sent_emails (name, email, status, error) VALUES (?, ?, ?, ?)',
                  (r['name'], r['email'], status, error))
        conn.commit()
        sent_in_burst += 1
        delay = random.randint(8, 30)
        next_send_time = int(time.time()) + delay
        if sent_in_burst >= burst_size:
            sent_in_burst = 0
            cooldown_until = int(time.time()) + burst_pause
            for i in range(burst_pause, 0, -1):
                if not sending:
                    break
                next_send_time = cooldown_until
                time.sleep(1)
        else:
            for i in range(delay, 0, -1):
                if not sending:
                    break
                next_send_time = int(time.time()) + i
                time.sleep(1)
    conn.close()
    sending = False
    retrying = False
    next_send_time = 0
    cooldown_until = 0

@app.route('/', methods=['GET', 'POST'])
def dashboard():
    upload_success = False
    if request.method == 'POST':
        if 'recipients' in request.files:
            file = request.files['recipients']
            filename = file.filename
            if filename.endswith('.xlsx'):
                file.save('recipients.xlsx')
                flash('Recipients file uploaded!')
                upload_success = True
            else:
                flash('Invalid file type. Please upload a .xlsx file.', 'danger')
                return redirect(url_for('dashboard'))
            global RECIPIENTS_FILE
            RECIPIENTS_FILE = 'recipients.xlsx'
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('DELETE FROM sent_emails')
            conn.commit()
            conn.close()
            return redirect(url_for('dashboard'))
    if os.path.exists('recipients.xlsx'):
        df = pd.read_excel('recipients.xlsx', engine='openpyxl')
        recipients = []
        for _, row in df.iterrows():
            r = row.to_dict()
            r['email'] = extract_email(r.get('Contact', ''))
            r['name'] = r.get('Business Name', r.get('name', ''))
            r['business'] = r.get('Type', r.get('business', ''))
            r['notes'] = r.get('Notes', r.get('notes', ''))
            r['Opportunity / Cold Email Pitch'] = r.get('Opportunity / Cold Email Pitch', '')
            r['Potential Client or not'] = r.get('Potential Client or not', '')
            recipients.append(r)
    else:
        recipients = []
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT email, status, error, sent_at FROM sent_emails ORDER BY sent_at DESC')
    status_map = {}
    for email, status, error, sent_at in c.fetchall():
        status_map[email] = (status, error, sent_at)
    conn.close()
    for r in recipients:
        s = status_map.get(r['email'], ('PENDING', '', ''))
        r['status'] = s[0]
        r['error'] = s[1]
        r['sent_at'] = s[2]
        # Use Ollama for subject/body
        subj, body = generate_email_with_ollama(r)
        r['preview_subject'] = subj
        r['preview_body'] = body
    # Get flash messages for upload success
    flash_messages = get_flashed_messages(with_categories=True)
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PixelSolve Cold Email Automation</title>
        <!-- Modern font -->
        <link href="https://fonts.googleapis.com/css?family=Inter:400,500,700&display=swap" rel="stylesheet">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css"/>
        <style>
            body {
                font-family: 'Inter', 'Roboto', Arial, sans-serif;
                min-height: 100vh;
                background: radial-gradient(ellipse at 50% 30%, #232946 0%, #151a2e 100%);
                color: #f3f6fa;
                position: relative;
                overflow-x: hidden;
            }
            /* Galaxy stars background */
            body::before {
                content: '';
                position: fixed;
                top: 0; left: 0; width: 100vw; height: 100vh;
                z-index: 0;
                pointer-events: none;
                background: url('data:image/svg+xml;utf8,<svg width="100%25" height="100%25" xmlns="http://www.w3.org/2000/svg"><circle cx="10" cy="10" r="1.5" fill="white" opacity="0.7"/><circle cx="80" cy="40" r="1" fill="white" opacity="0.5"/><circle cx="200" cy="120" r="1.2" fill="white" opacity="0.6"/><circle cx="400" cy="300" r="1.7" fill="white" opacity="0.7"/><circle cx="700" cy="100" r="1.1" fill="white" opacity="0.5"/><circle cx="900" cy="500" r="1.3" fill="white" opacity="0.6"/><circle cx="1200" cy="200" r="1.4" fill="white" opacity="0.5"/></svg>');
                background-repeat: repeat;
                background-size: 400px 400px;
                opacity: 0.25;
            }
            .sticky-header {
                position: sticky;
                top: 0;
                z-index: 100;
                background: rgba(30, 34, 54, 0.98);
                box-shadow: 0 2px 24px rgba(0,0,0,0.18);
                padding: 32px 0 18px 0;
                margin-bottom: 0;
                text-align: center;
            }
            .hero-logo {
                font-size: 2.5rem;
                font-weight: bold;
                letter-spacing: 2px;
                margin-bottom: 6px;
                color: #fff;
                text-shadow: 0 0 8px #3a4a7a, 0 0 2px #fff;
            }
            .hero-tagline {
                font-size: 1.2rem;
                font-weight: 400;
                opacity: 0.92;
                color: #a3bffa;
                text-shadow: 0 0 4px #232946;
            }
            .dashboard-card {
                background: rgba(36, 41, 66, 0.98);
                border-radius: 28px;
                box-shadow: 0 4px 32px rgba(30,34,54,0.25);
                margin-top: 40px;
                padding: 36px 28px 28px 28px;
                max-width: 1200px;
                margin-left: auto;
                margin-right: auto;
                animation: fadeInUp 1s;
            }
            @keyframes fadeInUp {
                from { opacity: 0; transform: translateY(40px); }
                to { opacity: 1; transform: translateY(0); }
            }
            .table thead { background: #232946; color: #fff; }
            .table-striped > tbody > tr:nth-of-type(odd) { background-color: #232946; }
            .table-striped > tbody > tr:nth-of-type(even) { background-color: #1a1e33; }
            .status-badge { font-size: 0.95em; }
            .btn-pixelsolve { background: linear-gradient(90deg, #7f5fff 0%, #3a4a7a 100%); color: #fff; border: none; border-radius: 22px; padding: 12px 32px; font-weight: 700; font-size: 1.13em; transition: background 0.2s, box-shadow 0.2s; box-shadow: 0 2px 12px rgba(127,95,255,0.10); letter-spacing: 0.5px; }
            .btn-pixelsolve:hover { background: linear-gradient(90deg, #3a4a7a 0%, #7f5fff 100%); color: #fff; box-shadow: 0 4px 24px rgba(127,95,255,0.18); }
            .btn-send {
                background: linear-gradient(90deg, #7f5fff 0%, #3a4a7a 100%);
                color: #fff;
                border: none;
                border-radius: 22px;
                padding: 12px 32px;
                font-weight: 700;
                font-size: 1.13em;
                letter-spacing: 0.5px;
                box-shadow: 0 2px 12px rgba(127,95,255,0.10);
                transition: background 0.2s, box-shadow 0.2s;
            }
            .btn-send:hover {
                background: linear-gradient(90deg, #3a4a7a 0%, #7f5fff 100%);
                color: #fff;
                box-shadow: 0 4px 24px rgba(127,95,255,0.18);
            }
            .btn-retry {
                background: linear-gradient(90deg, #ff7fbb 0%, #ffb347 100%);
                color: #fff;
                border: none;
                border-radius: 22px;
                padding: 12px 32px;
                font-weight: 700;
                font-size: 1.13em;
                letter-spacing: 0.5px;
                box-shadow: 0 2px 12px rgba(255,127,187,0.10);
                transition: background 0.2s, box-shadow 0.2s;
            }
            .btn-retry:hover {
                background: linear-gradient(90deg, #ffb347 0%, #ff7fbb 100%);
                color: #fff;
                box-shadow: 0 4px 24px rgba(255,127,187,0.18);
            }
            .btn-preview { 
                background: #2e3657; color: #e0e6ff; border: 1.5px solid #a3bffa; border-radius: 16px; padding: 7px 22px; font-weight: 600; font-size: 1.04em; transition: background 0.2s, color 0.2s, border 0.2s; box-shadow: 0 1px 8px rgba(127,95,255,0.10); 
            }
            .btn-preview:hover { background: #a3bffa; color: #232946; border: 1.5px solid #fff; }
            .upload-success {
                background: linear-gradient(90deg, #7f5fff 0%, #3a4a7a 100%);
                color: #fff;
                border-radius: 16px;
                padding: 10px 24px;
                font-weight: 600;
                font-size: 1.08em;
                margin-bottom: 18px;
                box-shadow: 0 2px 12px rgba(127,95,255,0.10);
                text-align: center;
                letter-spacing: 0.5px;
            }
            .dashboard-card {
                /* Add subtle glow and more padding */
                box-shadow: 0 4px 32px 0 #232946, 0 0 16px 2px #7f5fff33;
                padding: 44px 36px 32px 36px;
            }
            .table th, .table td {
                padding-top: 18px !important;
                padding-bottom: 18px !important;
            }
            .table th {
                font-size: 1.08em;
                letter-spacing: 0.5px;
            }
            .table td {
                font-size: 1.04em;
            }
            .fab {
                display: none !important; /* Remove floating Options button */
            }
            .modal-content { border-radius: 24px; }
            .modal-content { background: #232946; color: #f3f6fa; border: 1.5px solid #7f5fff; box-shadow: 0 4px 32px #151a2e; }
            .modal-body { font-size: 1.11em; }
            .copy-btn { float: right; margin-left: 10px; font-size: 0.95em; }
            tr:hover { background: #2d3250 !important; }
            .table td, .table th { vertical-align: middle; }
            .table th { font-weight: 600; }
            .status-icon { font-size: 1.1em; margin-right: 4px; }
            @media (max-width: 900px) {
                .dashboard-card { padding: 10px 2px 8px 2px; }
                .modal-dialog { max-width: 98vw; }
            }
            @media (max-width: 600px) {
                .dashboard-card { padding: 4px 0 4px 0; }
                .sticky-header { padding: 8px 0 4px 0; }
                .hero-logo { font-size: 1.3rem; }
                .modal-dialog { max-width: 99vw; }
            }
        </style>
        <script>
        function formatTimeLeft(ts) {
            if (!ts || ts <= 0) return '--';
            let now = Math.floor(Date.now() / 1000);
            let diff = ts - now;
            if (diff <= 0) return 'Ready';
            let m = Math.floor(diff / 60);
            let s = diff % 60;
            return (m > 0 ? m + 'm ' : '') + s + 's';
        }
        function updateTimers() {
            fetch('/timers').then(r=>r.json()).then(data => {
                document.getElementById('next-send-timer').innerText = formatTimeLeft(data.next_send_time);
                document.getElementById('cooldown-timer').innerText = formatTimeLeft(data.cooldown_until);
            });
        }
        setInterval(updateTimers, 1000);
        window.onload = updateTimers;

        // --- FIX: Only auto-refresh table if no modal is open ---
        let autoRefreshInterval = null;
        function startAutoRefresh() {
          if (autoRefreshInterval) return;
          autoRefreshInterval = setInterval(function() {
            // If any modal is open, skip refresh
            if (document.querySelector('.modal.show')) return;
            fetch(window.location.href, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
                .then(resp => resp.text())
                .then(html => {
                    let parser = new DOMParser();
                    let doc = parser.parseFromString(html, 'text/html');
                    let newTable = doc.querySelector('#recipients-table');
                    let oldTable = document.querySelector('#recipients-table');
                    if (newTable && oldTable) oldTable.innerHTML = newTable.innerHTML;
                    let spinner = doc.querySelector('#sending-spinner');
                    let oldSpinner = document.querySelector('#sending-spinner');
                    if (spinner && oldSpinner) oldSpinner.innerHTML = spinner.innerHTML;
                });
          }, 5000);
        }
        function stopAutoRefresh() {
          if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
          }
        }
        // Listen for modal open/close events to pause/resume auto-refresh
        document.addEventListener('DOMContentLoaded', function() {
          startAutoRefresh();
          // Bootstrap 5 modal events
          document.body.addEventListener('show.bs.modal', function() { stopAutoRefresh(); });
          document.body.addEventListener('hidden.bs.modal', function() { startAutoRefresh(); });
        });
        </script>
    </head>
    <body>
    <div class="sticky-header animate__animated animate__fadeInDown">
        <div class="hero-logo"><i class="fa-solid fa-envelope-circle-check me-2"></i>PixelSolve</div>
        <div class="hero-tagline">AI-Powered Cold Email Automation Platform</div>
    </div>
    <div class="dashboard-card animate__animated animate__fadeInUp">
      {% for category, message in flash_messages %}
        <div class="upload-success animate__animated animate__fadeInDown">{{ message }}</div>
      {% endfor %}
      <div class="d-flex flex-column align-items-center mb-4 gap-2">
        <h2 class="mb-0" style="color: #fff; letter-spacing: 1px;"><i class="fa-solid fa-gauge-high me-2"></i>Dashboard</h2>
        <button class="btn btn-pixelsolve mt-2" data-bs-toggle="modal" data-bs-target="#uploadModal"><i class="fa-solid fa-upload"></i> Upload Recipients</button>
      </div>
      <div class="timers-row">
        <div class="timer-box"><i class="fa-solid fa-clock"></i> Next Email In: <span id="next-send-timer">--</span></div>
        <div class="timer-box"><i class="fa-solid fa-hourglass-half"></i> Burst Cooldown: <span id="cooldown-timer">--</span></div>
      </div>
      <form action="/start" method="post" class="mb-4 d-inline">
        <button type="submit" class="btn btn-send px-4" {{'disabled' if sending}}><i class="fa-solid fa-paper-plane"></i> Start Sending Emails</button>
      </form>
      <form action="/retry_failed" method="post" class="mb-4 d-inline">
        <button type="submit" class="btn btn-retry px-4" {{'disabled' if sending}}><i class="fa-solid fa-rotate-right"></i> Retry Failed</button>
      </form>
      <button class="fab animate__animated animate__bounceIn" onclick="showModal('logModal')" title="View Logs"><i class="fa-solid fa-list"></i></button>
      <div id="sending-spinner" class="mb-3">
        {% if sending %}
        <div class="progress-spinner"><div class="spinner-border text-primary" role="status"></div> <span class="fw-bold">Sending in progress...</span></div>
        {% endif %}
      </div>
      <div class="table-responsive animate__animated animate__fadeIn">
        <table class="table table-bordered table-striped align-middle" id="recipients-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Status</th>
              <th>Error</th>
              <th>Sent At</th>
              <th>Email Preview</th>
            </tr>
          </thead>
          <tbody>
            {% for r in recipients %}
            <tr class="animate__animated animate__fadeInUp">
              <td>{{r['name']}}</td>
              <td>{{r['email']}}</td>
              <td>
                {% if r['status'] == 'SENT' %}
                  <span class="badge bg-success status-badge"><i class="fa-solid fa-check status-icon"></i> SENT</span>
                {% elif r['status'] == 'FAILED' %}
                  <span class="badge bg-danger status-badge"><i class="fa-solid fa-xmark status-icon"></i> FAILED</span>
                {% elif r['status'] == 'No email' %}
                  <span class="badge bg-warning text-dark status-badge"><i class="fa-solid fa-envelope-open-text status-icon"></i> NO EMAIL</span>
                {% elif r['status'] == 'PENDING' %}
                  <span class="badge bg-secondary status-badge"><i class="fa-solid fa-hourglass-half status-icon"></i> PENDING</span>
                {% else %}
                  <span class="badge bg-warning text-dark status-badge">{{r['status']}}</span>
                {% endif %}
              </td>
              <td style="max-width: 300px; word-break: break-all;">{{r['error']}}</td>
              <td>{{r['sent_at'][:19] if r['sent_at'] else ''}}</td>
              <td>
                <button class="btn btn-preview" data-bs-toggle="modal" data-bs-target="#previewModal{{ loop.index }}">
                  <i class="fa-solid fa-eye"></i> Email Preview
                </button>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      <!-- Render all modals outside the table so they are not affected by table refresh -->
      {% for r in recipients %}
      <div class="modal fade" id="previewModal{{ loop.index }}" tabindex="-1" aria-labelledby="previewModalLabel{{ loop.index }}" aria-hidden="true">
        <div class="modal-dialog modal-lg modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" id="previewModalLabel{{ loop.index }}">Email Preview for {{r['name']}}</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body" style="white-space: pre-wrap; font-family: monospace;">
              <div class="mb-2">
                <strong>Subject:</strong> {{r['preview_subject']}}
                <button class="btn btn-outline-secondary btn-sm copy-btn" onclick="navigator.clipboard.writeText('{{r['preview_subject']}}')">Copy Subject</button>
              </div>
              <div class="mb-2">
                <strong>Body:</strong>
                <button class="btn btn-outline-secondary btn-sm copy-btn" onclick="navigator.clipboard.writeText(`{{r['preview_body'] | replace('`', '\`')}}`)">Copy Body</button>
              </div>
              <div style="white-space: pre-wrap; font-family: inherit; font-size: 1.08em;">
                {{r['preview_body'] | replace('**', '<strong>') | replace('**', '</strong>') | safe}}
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
            </div>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
    <!-- Upload Modal -->
    <div class="modal fade" id="uploadModal" tabindex="-1" aria-labelledby="uploadModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content animate__animated animate__zoomIn">
          <div class="modal-header">
            <h5 class="modal-title" id="uploadModalLabel"><i class="fa-solid fa-upload"></i> Upload Recipients (.xlsx only)</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <form method="post" enctype="multipart/form-data">
            <div class="modal-body">
              <input type="file" name="recipients" accept=".xlsx" class="form-control" required>
            </div>
            <div class="modal-footer">
              <button type="submit" class="btn btn-pixelsolve">Upload</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    <!-- Log Modal -->
    <div class="modal fade" id="logModal" tabindex="-1" aria-labelledby="logModalLabel" aria-hidden="true">
      <div class="modal-dialog modal-lg">
        <div class="modal-content animate__animated animate__zoomIn">
          <div class="modal-header">
            <h5 class="modal-title" id="logModalLabel"><i class="fa-solid fa-list"></i> Email Send Log</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="table-responsive">
              <table class="table table-sm table-striped">
                <thead><tr><th>Name</th><th>Email</th><th>Status</th><th>Error</th><th>Sent At</th><th>Potential Client</th><th>Subject Preview</th><th>Body Preview</th></tr></thead>
                <tbody>
                {% for r in recipients %}
                  <tr>
                    <td>{{r['name']}}</td>
                    <td>{{r['email']}}</td>
                    <td>{{r['status']}}</td>
                    <td style="max-width: 200px; word-break: break-all;">{{r['error']}}</td>
                    <td>{{r['sent_at'][:19] if r['sent_at'] else ''}}</td>
                    <td>{{r['Potential Client or not']}}</td>
                    <td class="preview-cell">{{r['preview_subject']}}</td>
                    <td class="preview-cell">{{r['preview_body']}}</td>
                  </tr>
                {% endfor %}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    ''', recipients=recipients, sending=sending, flash_messages=flash_messages)

@app.route('/timers')
def timers():
    global next_send_time, cooldown_until
    return jsonify({
        'next_send_time': next_send_time,
        'cooldown_until': cooldown_until
    })

@app.route('/start', methods=['POST'])
def start():
    global sending
    if not sending:
        thread = threading.Thread(target=send_emails_thread)
        thread.start()
    return redirect(url_for('dashboard'))

@app.route('/retry_failed', methods=['POST'])
def retry_failed():
    global sending, retrying
    if not sending and not retrying:
        retrying = True
        thread = threading.Thread(target=send_emails_thread, kwargs={'retry_failed': True})
        thread.start()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True, port=5050) 