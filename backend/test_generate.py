import os
from jinja2 import Template
import requests
import re

def remove_emojis(text):
    return re.sub(r'[^ -~]+', '', text)

def contains_emoji_or_unicode(text):
    return any(ord(c) > 127 for c in text)

def extract_subject_body(result, recipient=None):
    result = remove_emojis(result)
    business_name = recipient.get('name', 'there') if recipient else 'there'
    if '**Subject:**' in result:
        after_subject = result.split('**Subject:**', 1)[1].strip()
        subject = ''
        body = ''
        if '\n\n' in after_subject:
            subject, body = after_subject.split('\n\n', 1)
        elif '\n' in after_subject:
            subject, body = after_subject.split('\n', 1)
        else:
            subject = after_subject
            body = ''
        subject_raw = subject.strip()
        subject_clean = subject_raw.replace('**', '').replace(':', '', 1).strip()
        body_clean = re.sub(r'\*\*', '', body)
        if '**' in body:
            body_clean = body_clean.replace('**', '')
        greeting = f"Hi {business_name} Team,"
        greeting_idx = body_clean.find(greeting)
        if greeting_idx != -1:
            after_greeting = body_clean[greeting_idx + len(greeting):].lstrip('\n ,')
            body_clean = f"{greeting}\n\n{after_greeting}"
        else:
            for alt_greeting in ["Hi ", "Hello "]:
                idx = body_clean.find(alt_greeting)
                if idx != -1:
                    after_greeting = body_clean[idx + len(alt_greeting):].lstrip('\n ,')
                    body_clean = f"{alt_greeting}\n\n{after_greeting}"
                    break
        if not body_clean.strip():
            for greeting in [f"Hi {business_name} Team,", "Hi ", "Hello "]:
                idx = subject_clean.find(greeting)
                if idx != -1:
                    subj = subject_clean[:idx].strip()
                    bod = subject_clean[idx:].strip()
                    return subj, bod
        return subject_clean, body_clean.strip()
    lines = result.strip().splitlines()
    subject = lines[0] if lines else ""
    body = "\n".join(lines[1:]) if len(lines) > 1 else ""
    subject_clean = subject.replace('**', '').replace(':', '', 1).strip()
    body_clean = re.sub(r'\*\*', '', body)
    return subject_clean, body_clean

def format_email_body(body, recipient=None):
    business_name = recipient.get('name', 'there') if recipient else 'there'
    body = re.sub(r'^Hi [^\n,]+,', f'Hi {business_name} Team,', body, flags=re.MULTILINE)
    body = re.sub(r'(Hi [^\n,]+,)(?!\n\n)', r'\1\n\n', body)
    body = body.replace('**', '')
    body = body.replace('3050%', '30–50%')
    body = body.replace('Wed ', "We’d ")
    body = body.replace('Wed\n', "We’d\n")
    body = re.sub(r'(\s*[•\-]\s*)', '\n\1', body)
    lines = body.splitlines()
    new_lines = []
    for line in lines:
        l = line.strip()
        if l.startswith('•') or l.startswith('-') or not l or l.startswith('Hi ') or l.startswith('Best regards,') or l.startswith('Team PixelSolve') or l.startswith('www.pixelsolve.co'):
            new_lines.append(l)
        else:
            if new_lines and new_lines[-1] and not new_lines[-1].endswith(('.', '!', '?', ':')):
                new_lines[-1] += ' ' + l
            else:
                new_lines.append(l)
    formatted = []
    for i, l in enumerate(new_lines):
        if l.startswith('•') or l.startswith('-'):
            if i > 0 and new_lines[i-1]:
                formatted.append('')
        formatted.append(l)
        if l in ['Best regards,', 'Team PixelSolve', 'www.pixelsolve.co']:
            formatted.append('')
    result = '\n'.join(formatted)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()

# Improved prompt for Llama 3
PROMPT_TEMPLATE_STR = '''
You are helping me generate personalized cold email bodies for my digital agency, PixelSolve.

You will receive rows of business data from an Excel file. Each row contains the following columns:
- Business Name
- Type
- City
- Country
- Email
- WhatsApp
- Has Website (Yes/No)
- Instagram Presence (Yes/No)
- Personalized Hook / Observation

Your task is to generate an email body using the following template. Replace [BUSINESS NAME] with the actual business name and [LOCATION] with "City, Country" from the data.

---  
**Subject:** Boost [BUSINESS NAME]'s Online Reach with a Loyalty App & More

Hi [BUSINESS NAME] Team,

I recently came across your café in [LOCATION] and was genuinely impressed by your atmosphere and strong Instagram presence. It’s clear your customers love what you’re doing!

I also noticed that you don’t currently have a website — which presents a great opportunity to attract even more customers online.

At **PixelSolve**, we help coffee shops like yours grow their digital presence through:

**• Branded Loyalty Apps** – Reward loyal customers and boost repeat visits  
**• Mobile Ordering** – Increase convenience and drive more sales  
**• Local Influencer Marketing** – Amplify your brand and reach new audiences

Many cafés we've worked with have seen 30–50% growth in customer engagement using these solutions.

Would you be open to a quick demo? Even a short reply would be appreciated.

Best regards,  
**The PixelSolve Team**  
www.pixelsolve.co  
---

Rules:
- Keep the tone professional and friendly.
- Do **not** use emojis.
- Use **bold** for "PixelSolve" and the three main services.
- Sign off as “The PixelSolve Team” — do not use any personal names.
- Replace [BUSINESS NAME] and [LOCATION] from the Excel data.
- Optionally, if there's a value in "Personalized Hook / Observation", you may include it as a sentence after the second paragraph to make the email more relevant.
- Output only the email, no extra commentary or explanation.

Now, using the data below, generate the email as specified above. Output only the email, nothing else.

Business Name: Brew Haven
Type: Coffee Shop
City: Chicago
Country: USA
Email: brew@example.com
WhatsApp: 
Has Website: No
Instagram Presence: Yes
Personalized Hook / Observation: Your latte art posts are getting great engagement!
'''

OLLAMA_URL = 'http://localhost:11434/api/generate'

model = 'llama3'
try:
    response = requests.post(
        OLLAMA_URL,
        json={'model': model, 'prompt': PROMPT_TEMPLATE_STR, 'stream': False},
        timeout=60
    )
    result = response.json().get('response', '')
    print("\n--- RAW MODEL OUTPUT (LLAMA 3) ---\n")
    print(result)
    print("\n--- END RAW OUTPUT ---\n")
except Exception as e:
    print(f"[ERROR] {e}") 