# PixelSolve AI-Powered Cold Email Automation

This project automates sending highly personalized, business-specific cold emails using a beautiful web dashboard and local AI (Ollama LLM) for your startup or agency.

## Features
- **AI-generated, business-specific cold emails** (using Ollama LLM on your Mac/PC)
- **Modern, galaxy-themed dashboard** (Flask web app)
- **Upload Excel (.xlsx) of leads** (with all business details)
- **Preview every email** (see subject/body with bold, bullets, and personalization)
- **Send emails in bulk** (with status tracking and retry for failed)
- **No per-email cost, no cloud AI required** (runs locally)
- **Responsive, beautiful UI**

## Setup

### 1. Clone the Repo
```bash
git clone <your-repo-url>
cd <repo-folder>
```

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 3. Install Ollama (Local LLM)
- [Download and install Ollama](https://ollama.com/) for Mac/Windows/Linux:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```
- Download a model (recommended: llama2 or mistral):
```bash
ollama pull llama2
```

### 4. Start Ollama
```bash
ollama run llama2
```
(Leave this terminal open while using the app)

### 5. Configure Your Email Credentials
- Create a `.env` file in the project root:
```
SMTP_SERVER=your.smtp.server
SMTP_PORT=465
SMTP_USER=your@email.com
SMTP_PASSWORD=yourpassword
```

### 6. Run the Flask App
```bash
python app.py
```

### 7. Open the Dashboard
- Go to [http://localhost:5050](http://localhost:5050) in your browser.
- Upload your Excel file of leads (see below for format).
- Preview, send, and track emails!

## Excel File Format
Your `.xlsx` file should have columns like:
- Business Name
- Type
- Location
- Contact
- Notes
- Opportunity / Cold Email Pitch
- Potential Client or not

Each row = one lead. The more info you provide, the better the AI emails!

## Usage
- **Upload Recipients:** Click 'Upload Recipients' and select your Excel file.
- **Preview Emails:** Click 'Email Preview' for any lead to see the AI-generated email.
- **Send Emails:** Click 'Start Sending Emails' to send to all with valid emails.
- **Retry Failed:** Click 'Retry Failed' to retry any failed sends.
- **Track Status:** See status (sent, failed, pending) in the dashboard.

## Contributing
Pull requests and suggestions welcome! Please open an issue or PR.

## License
MIT License

---

**Made with ❤️ by the PixelSolve Team** 