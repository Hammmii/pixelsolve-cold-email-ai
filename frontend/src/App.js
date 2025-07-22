import React, { useState, useRef, useEffect } from 'react';
import './App.css';

const API_URL = 'http://localhost:5050/api';

function extractSubjectAndBody(email) {
  if (!email) return { subject: '', body: '' };
  const lines = email.split('\n');
  // Find the subject line (first line starting with 'Subject:')
  const subjectLine = lines.find(l => l.trim().toLowerCase().startsWith('subject:')) || lines[0] || '';
  const subject = subjectLine.replace(/\*\*/g, '').replace('Subject:', '').trim();
  // Find the first line that starts with 'Hi' or 'Hello' (case-insensitive)
  const bodyStart = lines.findIndex(l => l.trim().toLowerCase().startsWith('hi') || l.trim().toLowerCase().startsWith('hello'));
  const body = bodyStart !== -1 ? lines.slice(bodyStart).join('\n').replace(/^\n+/, '') : lines.slice(1).join('\n').replace(/^\n+/, '');
  return { subject, body };
}

function EmailSubject({ email }) {
  const { subject } = extractSubjectAndBody(email);
  return <span>{subject}</span>;
}

function EmailBody({ email }) {
  const { body } = extractSubjectAndBody(email);
  return (
    <pre style={{ margin: 0, background: 'none', color: 'inherit', fontFamily: 'inherit', fontSize: '1em', whiteSpace: 'pre-wrap' }}>
      {body}
    </pre>
  );
}

function StatsPage({ onBack }) {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    fetch('http://localhost:5050/api/stats')
      .then(res => res.json())
      .then(setStats);
  }, []);
  if (!stats) return <div className="stats-card">Loading stats...</div>;
  return (
    <div className="stats-bg">
      <div className="stats-card">
        <button className="btn-secondary" style={{ float: 'right', marginBottom: 12 }} onClick={onBack}>Back</button>
        <h2>Email Insights & Stats</h2>
        <div className="stats-row">
          <div className="stats-block">
            <div className="stats-label">Total Sent Today</div>
            <div className="stats-value">{stats.total_sent_today}</div>
          </div>
          <div className="stats-block">
            <div className="stats-label">Total Sent (All Time)</div>
            <div className="stats-value">{stats.total_sent_all}</div>
          </div>
        </div>
        <div className="stats-row">
          <div className="stats-block">
            <div className="stats-label">Top Countries</div>
            <ul className="stats-list">
              {stats.countries.map(([country, count]) => <li key={country}>{country}: {count}</li>)}
            </ul>
          </div>
          <div className="stats-block">
            <div className="stats-label">Top Business Types</div>
            <ul className="stats-list">
              {stats.business_types.map(([type, count]) => <li key={type}>{type}: {count}</li>)}
            </ul>
          </div>
        </div>
        <div className="stats-row">
          <div className="stats-block">
            <div className="stats-label">Top Recipients by Country</div>
            <ul className="stats-list">
              {stats.top_recipients_by_country.map(([email, country]) => <li key={email}>{email} ({country})</li>)}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState({ total: 0, done: 0, emails: {}, status: 'idle', filename: '', message: '', error: '' });
  const [logs, setLogs] = useState([]);
  const [showLogs, setShowLogs] = useState(false);
  const [sending, setSending] = useState(false);
  const intervalRef = useRef();
  const [uploadMsg, setUploadMsg] = useState('');
  const [showStats, setShowStats] = useState(false);
  const [batchSize, setBatchSize] = useState(10);
  const [delayMin, setDelayMin] = useState(8);
  const [delayMax, setDelayMax] = useState(15);

  // Poll progress
  useEffect(() => {
    if (progress.status === 'generating' || progress.status === 'sending') {
      intervalRef.current = setInterval(fetchProgress, 2000);
    } else {
      clearInterval(intervalRef.current);
    }
    return () => clearInterval(intervalRef.current);
    // eslint-disable-next-line
  }, [progress.status]);

  function fetchProgress() {
    fetch(`${API_URL}/progress`)
      .then(res => res.json())
      .then(setProgress)
      .catch(() => {});
  }

  function handleFileChange(e) {
    setFile(e.target.files[0]);
    setUploadMsg('');
  }

  function handleUpload() {
    if (!file) return;
    setUploading(true);
    setUploadMsg('');
    const formData = new FormData();
    formData.append('file', file);
    fetch(`${API_URL}/upload`, {
      method: 'POST',
      body: formData,
    })
      .then(res => res.json())
      .then(data => {
        setUploading(false);
        setUploadMsg(data.message || 'File uploaded. Generating emails...');
        setProgress({ ...progress, status: 'generating', filename: data.filename, message: data.message });
        fetchProgress();
      })
      .catch(() => setUploading(false));
  }

  function handleCopy(email) {
    const { body } = extractSubjectAndBody(email);
    navigator.clipboard.writeText(body);
  }

  function handleSend() {
    setSending(true);
    fetch(`${API_URL}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_size: batchSize, delay_min: delayMin, delay_max: delayMax })
    })
      .then(res => res.json())
      .then(() => {
        setSending(false);
        setProgress({ ...progress, status: 'sending' });
        fetchProgress();
      })
      .catch(() => setSending(false));
  }

  function handleRetryFailed() {
    fetch(`${API_URL}/retry_failed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_size: batchSize, delay_min: delayMin, delay_max: delayMax })
    })
      .then(res => res.json())
      .then(() => {
        fetchProgress();
      });
  }

  function fetchLogs() {
    fetch(`${API_URL}/logs`)
      .then(res => res.json())
      .then(data => setLogs(data.logs || []));
  }

  useEffect(() => {
    if (showLogs) fetchLogs();
  }, [showLogs]);

  // Table rows
  const rows = Object.entries(progress.emails || {}).map(([email, data]) => ({
    email,
    ...data,
  }));

  const allReady = progress.total > 0 && progress.done === progress.total && rows.every(r => r.status === 'Ready');

  let statusMsg = '';
  if (progress.status === 'generating') statusMsg = 'Generating emails...';
  else if (progress.status === 'sending') statusMsg = 'Sending emails...';
  else if (progress.status === 'done') statusMsg = 'Done!';
  else if (progress.status === 'idle') statusMsg = 'Idle.';
  if (progress.error) statusMsg = `Error: ${progress.error}`;

  // Batch progress and status
  let batchMsg = '';
  if (progress.batch_total > 0) {
    batchMsg = `Batch ${progress.batch_current} of ${progress.batch_total}`;
    if (progress.wait_time > 0 && progress.status && progress.status.startsWith('waiting_batch_')) {
      batchMsg += ` — Waiting ${progress.wait_time}s to avoid spam/rate limits...`;
    }
  }
  let estTime = '';
  if (progress.batch_total > 0 && progress.batch_current < progress.batch_total) {
    const batchesLeft = progress.batch_total - progress.batch_current;
    const avgDelay = ((delayMin + delayMax) / 2) || 10;
    estTime = `Est. time left: ~${Math.ceil(batchesLeft * avgDelay)}s`;
  }

  if (showStats) return <StatsPage onBack={() => setShowStats(false)} />;

  return (
    <div className="app-bg">
      <div className="header">
        <h1>PixelSolve Cold Email Automation</h1>
        <p className="subtitle">AI-powered, professional cold emails for your business leads</p>
        <button className="btn-secondary" style={{ float: 'right', marginTop: -48, marginRight: 12 }} onClick={() => setShowStats(true)}>View Stats</button>
      </div>
      <div className="card">
        <div className="upload-row">
          <label htmlFor="file-upload" className="upload-label">
            {file ? 'Change File' : 'Choose File'}
          </label>
          <input
            id="file-upload"
            type="file"
            accept=".xlsx"
            onChange={handleFileChange}
          />
          <button onClick={handleUpload} disabled={uploading || !file} className="btn-main" title="Upload your Excel file">
            {uploading ? 'Uploading...' : 'Upload Excel'}
          </button>
          {file && <span className="upload-filename">{file.name}</span>}
          {progress.filename && !file && <span className="upload-filename">{progress.filename}</span>}
        </div>
        {uploadMsg && <div className="upload-msg">{uploadMsg}</div>}
        <div className="progress-row">
          <div className="progress-label">AI Email Generation Progress</div>
          <div className="progress-bar-outer">
            <div
              className="progress-bar-inner"
              style={{ width: progress.total ? `${Math.round((progress.done / progress.total) * 100)}%` : '0%' }}
            >
              {progress.total ? `${progress.done} / ${progress.total}` : '0 / 0'}
            </div>
          </div>
          <div className="status-msg">{statusMsg}</div>
          {batchMsg && <div className="batch-msg">{batchMsg} {estTime && <span style={{ color: '#a3bffa', marginLeft: 8 }}>{estTime}</span>}</div>}
        </div>
        <div className="batch-controls-row">
          <label style={{ color: '#a3bffa', marginRight: 8 }}>Batch size:</label>
          <input type="number" min={1} max={100} value={batchSize} onChange={e => setBatchSize(Number(e.target.value))} style={{ width: 60, marginRight: 16 }} />
          <label style={{ color: '#a3bffa', marginRight: 8 }}>Delay (sec):</label>
          <input type="number" min={1} max={60} value={delayMin} onChange={e => setDelayMin(Number(e.target.value))} style={{ width: 50, marginRight: 4 }} />
          <span style={{ color: '#a3bffa', marginRight: 4 }}>-</span>
          <input type="number" min={1} max={120} value={delayMax} onChange={e => setDelayMax(Number(e.target.value))} style={{ width: 50, marginRight: 8 }} />
          <span style={{ color: '#a3bffa' }}>(random per batch)</span>
        </div>
        <div className="table-responsive">
          <table className="main-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Business</th>
                <th>Status</th>
                <th>Subject</th>
                <th>Body</th>
                <th>Error</th>
                <th>Copy</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={8} style={{ textAlign: 'center', color: '#aaa' }}>No data yet. Upload a file to begin.</td></tr>
              )}
              {rows.map((row, i) => (
                <tr key={row.email} className={row.status === 'FAILED' ? 'row-failed' : ''}>
                  <td>{row.name || '-'}</td>
                  <td>{row.email}</td>
                  <td>{row.business || '-'}</td>
                  <td>
                    {row.status === 'Ready' && <span className="badge badge-ready">Ready</span>}
                    {row.status === 'SENT' && <span className="badge badge-ready">Sent</span>}
                    {row.status === 'FAILED' && <span className="badge badge-failed">Failed</span>}
                    {row.status !== 'Ready' && row.status !== 'FAILED' && row.status !== 'SENT' && <span className="badge badge-pending">{row.status}</span>}
                  </td>
                  <td style={{ maxWidth: 320, wordBreak: 'break-word', whiteSpace: 'pre-line', fontWeight: 700 }}>
                    {row.model_output ? <EmailSubject email={row.model_output} /> : <span style={{ color: '#aaa' }}>-</span>}
                  </td>
                  <td style={{ maxWidth: 520, wordBreak: 'break-word', whiteSpace: 'pre-line' }}>
                    {row.model_output ? <EmailBody email={row.model_output} /> : <span style={{ color: '#aaa' }}>-</span>}
                  </td>
                  <td style={{ color: '#f77', maxWidth: 180, wordBreak: 'break-word' }}>{row.error}</td>
                  <td>
                    <button className="btn-copy" title="Copy email body" onClick={() => handleCopy(row.model_output)}>
                      Copy
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="actions-row">
          <button className="btn-main" title="Send all ready emails" onClick={handleSend} disabled={!allReady || sending || rows.length === 0}>
            {sending || progress.status === 'sending' ? 'Sending...' : 'Send All Emails'}
          </button>
          <button className="btn-main" title="Retry failed emails" onClick={handleRetryFailed} disabled={rows.filter(r => r.status === 'FAILED').length === 0} style={{ background: 'linear-gradient(90deg, #ff4e50 0%, #7f5fff 100%)', marginLeft: 8 }}>
            Retry Failed
          </button>
          <button className="btn-secondary" onClick={() => setShowLogs(!showLogs)}>
            {showLogs ? 'Hide Logs' : 'Show Logs'}
          </button>
        </div>
        {showLogs && (
          <div className="logs-modal">
            <h3>Email Logs</h3>
            <table className="logs-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Business</th>
                  <th>Status</th>
                  <th>Subject</th>
                  <th>Body</th>
                  <th>Sent At</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 && <tr><td colSpan={8}>No logs yet.</td></tr>}
                {logs.map((log, i) => (
                  <tr key={i}>
                    <td>{log.name}</td>
                    <td>{log.email}</td>
                    <td>{log.business_type}</td>
                    <td>{log.status}</td>
                    <td style={{ maxWidth: 320, wordBreak: 'break-word', whiteSpace: 'pre-line', fontWeight: 700 }}>
                      {log.model_output ? <EmailSubject email={log.model_output} /> : <span style={{ color: '#aaa' }}>-</span>}
                    </td>
                    <td style={{ maxWidth: 520, wordBreak: 'break-word', whiteSpace: 'pre-line' }}>
                      {log.model_output ? <EmailBody email={log.model_output} /> : <span style={{ color: '#aaa' }}>-</span>}
                    </td>
                    <td>{log.sent_at}</td>
                    <td style={{ color: '#f77' }}>{log.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <footer className="footer">&copy; {new Date().getFullYear()} PixelSolve. All rights reserved.</footer>
    </div>
  );
}

export default App;
