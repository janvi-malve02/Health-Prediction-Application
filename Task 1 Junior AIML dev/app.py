from flask import Flask, request, jsonify
import sqlite3, os, re
from datetime import datetime, date
import anthropic

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patients.db")

# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL, dob TEXT NOT NULL, email TEXT NOT NULL,
        glucose REAL NOT NULL, haemoglobin REAL NOT NULL, cholesterol REAL NOT NULL,
        remarks TEXT, created_at TEXT DEFAULT (datetime('now')))""")
    conn.commit(); conn.close()

init_db()

# ── AI ────────────────────────────────────────────────────────────────────────
def get_ai_prediction(dob, glucose, haemoglobin, cholesterol):
    # ---- PUT YOUR NEW API KEY HERE ----
    api_key = "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"
    # -----------------------------------
    if not api_key or api_key == "PASTE_YOUR_NEW_API_KEY_HERE":
        return predict_locally(glucose, haemoglobin, cholesterol)
    try:
        client = anthropic.Anthropic(api_key=api_key)
        age = (date.today() - datetime.strptime(dob, "%Y-%m-%d").date()).days // 365
        prompt = f"""You are a clinical assistant. Analyse these blood values and give a 2-sentence health risk assessment with a recommended action.
Age: {age} | Glucose: {glucose} mg/dL (normal 70-99) | Haemoglobin: {haemoglobin} g/dL (normal 12-17.5) | Cholesterol: {cholesterol} mg/dL (desirable <200)
Respond with plain text only, no headings or bullets."""
        msg = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=200,
                                     messages=[{"role":"user","content":prompt}])
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"AI error: {e}")
        return predict_locally(glucose, haemoglobin, cholesterol)

def predict_locally(glucose, haemoglobin, cholesterol):
    flags = []
    if glucose > 125: flags.append("elevated glucose suggestive of diabetes")
    elif glucose > 99: flags.append("borderline glucose (pre-diabetic range)")
    if haemoglobin < 12: flags.append("low haemoglobin indicating possible anaemia")
    if cholesterol > 240: flags.append("high cholesterol posing cardiovascular risk")
    elif cholesterol > 200: flags.append("borderline-high cholesterol")
    if not flags:
        return "Blood test values are within normal reference ranges. No immediate risk flags detected. Routine annual check-up is advised."
    return f"Assessment indicates: {'; '.join(flags)}. Clinical consultation is recommended for further evaluation and management."

# ── Validation ────────────────────────────────────────────────────────────────
def validate(data):
    errors = []
    if not data.get("full_name","").strip(): errors.append("Full name is required.")
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", data.get("email","")): errors.append("Invalid email address.")
    try:
        if datetime.strptime(data["dob"],"%Y-%m-%d").date() >= date.today():
            errors.append("Date of birth cannot be today or a future date.")
    except: errors.append("Invalid date of birth.")
    for f in ("glucose","haemoglobin","cholesterol"):
        try:
            if float(data.get(f,"")) <= 0: errors.append(f"{f.capitalize()} must be positive.")
        except: errors.append(f"{f.capitalize()} must be numeric.")
    return errors

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return HTML_PAGE

@app.route("/api/patients", methods=["GET"])
def list_patients():
    q = request.args.get("q","").strip()
    conn = get_db()
    try:
        if q:
            rows = conn.execute("SELECT * FROM patients WHERE full_name LIKE ? OR email LIKE ? ORDER BY created_at DESC",(f"%{q}%",f"%{q}%")).fetchall()
        else:
            rows = conn.execute("SELECT * FROM patients ORDER BY created_at DESC").fetchall()
        return jsonify([dict(r) for r in rows])
    finally: conn.close()

@app.route("/api/patients/<int:pid>", methods=["GET"])
def get_patient(pid):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM patients WHERE id=?",(pid,)).fetchone()
        return jsonify(dict(row)) if row else (jsonify({"error":"Not found"}),404)
    finally: conn.close()

@app.route("/api/patients", methods=["POST"])
def create_patient():
    data = request.get_json()
    errors = validate(data)
    if errors: return jsonify({"errors":errors}),400
    remarks = get_ai_prediction(data["dob"],float(data["glucose"]),float(data["haemoglobin"]),float(data["cholesterol"]))
    conn = get_db()
    try:
        cur = conn.execute("INSERT INTO patients (full_name,dob,email,glucose,haemoglobin,cholesterol,remarks) VALUES (?,?,?,?,?,?,?)",
            (data["full_name"].strip(),data["dob"],data["email"].strip(),
             float(data["glucose"]),float(data["haemoglobin"]),float(data["cholesterol"]),remarks))
        conn.commit()
        row = conn.execute("SELECT * FROM patients WHERE id=?",(cur.lastrowid,)).fetchone()
        return jsonify(dict(row)),201
    finally: conn.close()

@app.route("/api/patients/<int:pid>", methods=["PUT"])
def update_patient(pid):
    data = request.get_json()
    errors = validate(data)
    if errors: return jsonify({"errors":errors}),400
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM patients WHERE id=?",(pid,)).fetchone():
            return jsonify({"error":"Not found"}),404
        remarks = get_ai_prediction(data["dob"],float(data["glucose"]),float(data["haemoglobin"]),float(data["cholesterol"]))
        conn.execute("UPDATE patients SET full_name=?,dob=?,email=?,glucose=?,haemoglobin=?,cholesterol=?,remarks=? WHERE id=?",
            (data["full_name"].strip(),data["dob"],data["email"].strip(),
             float(data["glucose"]),float(data["haemoglobin"]),float(data["cholesterol"]),remarks,pid))
        conn.commit()
        row = conn.execute("SELECT * FROM patients WHERE id=?",(pid,)).fetchone()
        return jsonify(dict(row))
    finally: conn.close()

@app.route("/api/patients/<int:pid>", methods=["DELETE"])
def delete_patient(pid):
    print(f">>> DELETE called for id={pid}")
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM patients WHERE id=?",(pid,)).fetchone()
        if not row:
            print(f">>> id={pid} not found")
            return jsonify({"error":"Not found"}),404
        conn.execute("DELETE FROM patients WHERE id=?",(pid,))
        conn.commit()
        print(f">>> id={pid} deleted OK")
        return jsonify({"message":"Deleted successfully"})
    except Exception as e:
        print(f">>> DELETE error: {e}")
        return jsonify({"error":str(e)}),500
    finally: conn.close()

# ── Embedded HTML ─────────────────────────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>MIRA – Health Prediction System</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0b0f1a;--surface:#111827;--card:#161f30;--border:#1e2d45;--accent:#3b82f6;--accent2:#06b6d4;--green:#10b981;--red:#ef4444;--amber:#f59e0b;--text:#e2e8f0;--muted:#64748b;--serif:'DM Serif Display',serif;--sans:'DM Sans',sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh}
body::before{content:'';position:fixed;inset:0;z-index:0;background:radial-gradient(ellipse 80% 60% at 10% 0%,rgba(59,130,246,.12) 0%,transparent 60%),radial-gradient(ellipse 60% 50% at 90% 100%,rgba(6,182,212,.10) 0%,transparent 55%);pointer-events:none}
header{position:relative;z-index:10;display:flex;align-items:center;gap:1.2rem;padding:1.4rem 2.5rem;border-bottom:1px solid var(--border);background:rgba(11,15,26,.85);backdrop-filter:blur(12px)}
.logo-mark{width:42px;height:42px;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--accent2));display:grid;place-items:center;font-size:1.3rem;flex-shrink:0}
.brand h1{font-family:var(--serif);font-size:1.45rem;letter-spacing:.02em}
.brand p{font-size:.72rem;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;margin-top:1px}
.header-stats{margin-left:auto}
.stat-val{font-size:1.35rem;font-weight:600;color:var(--accent)}
.stat-label{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
main{position:relative;z-index:1;max-width:1400px;margin:0 auto;padding:2rem 2rem 4rem;display:grid;grid-template-columns:420px 1fr;gap:1.8rem;align-items:start}
.panel{background:var(--card);border:1px solid var(--border);border-radius:16px;overflow:hidden}
.panel-header{padding:1.2rem 1.5rem;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.panel-title{font-family:var(--serif);font-size:1.05rem;font-style:italic;display:flex;align-items:center;gap:.5rem}
.panel-body{padding:1.5rem}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
.field{margin-bottom:.9rem}
label{display:block;font-size:.72rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.35rem}
input{width:100%;padding:.6rem .85rem;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:var(--sans);font-size:.88rem;transition:border-color .2s,box-shadow .2s;outline:none}
input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(59,130,246,.18)}
.blood-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.8rem;margin-bottom:.9rem}
.blood-grid label{color:var(--accent2)}
.error-list{margin-bottom:1rem;padding:.7rem .9rem;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:8px;font-size:.8rem;color:#fca5a5}
.error-list li{margin-left:1rem;margin-top:.2rem}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:.45rem;padding:.65rem 1.3rem;border-radius:9px;font-family:var(--sans);font-size:.85rem;font-weight:600;cursor:pointer;border:none;transition:all .2s;letter-spacing:.02em}
.btn-primary{background:linear-gradient(135deg,var(--accent),#2563eb);color:#fff;width:100%;padding:.75rem;box-shadow:0 4px 15px rgba(59,130,246,.35)}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(59,130,246,.45)}
.btn-primary:disabled{opacity:.55;cursor:not-allowed;transform:none}
.btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border);font-size:.78rem;padding:.4rem .85rem}
.btn-ghost:hover{background:var(--surface);color:var(--text)}
.btn-danger{background:rgba(239,68,68,.12);color:#fca5a5;border:1px solid rgba(239,68,68,.25)}
.btn-danger:hover{background:rgba(239,68,68,.2)}
.btn-edit{background:rgba(59,130,246,.12);color:#93c5fd;border:1px solid rgba(59,130,246,.25)}
.btn-edit:hover{background:rgba(59,130,246,.22)}
.search-bar{position:relative;margin-bottom:1.2rem}
.search-bar input{padding-left:2.5rem}
.search-icon{position:absolute;left:.85rem;top:50%;transform:translateY(-50%);color:var(--muted)}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.83rem}
th{padding:.7rem 1rem;text-align:left;font-size:.67rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid var(--border);background:var(--surface)}
td{padding:.75rem 1rem;border-bottom:1px solid rgba(30,45,69,.5);vertical-align:top}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(59,130,246,.04)}
.name-cell{font-weight:600}.email-cell{color:var(--muted);font-size:.78rem}
.badge{display:inline-block;padding:.2rem .6rem;border-radius:99px;font-size:.68rem;font-weight:700;letter-spacing:.04em}
.badge-green{background:rgba(16,185,129,.15);color:#6ee7b7;border:1px solid rgba(16,185,129,.2)}
.badge-amber{background:rgba(245,158,11,.12);color:#fcd34d;border:1px solid rgba(245,158,11,.2)}
.badge-red{background:rgba(239,68,68,.12);color:#fca5a5;border:1px solid rgba(239,68,68,.2)}
.remarks-cell{max-width:260px;color:var(--muted);font-size:.78rem;line-height:1.5}
.actions-cell{display:flex;gap:.4rem}
.empty-state{text-align:center;padding:4rem 1rem;color:var(--muted)}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.25);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
#toast{position:fixed;bottom:2rem;left:50%;transform:translateX(-50%) translateY(20px);background:var(--surface);border:1px solid var(--border);padding:.75rem 1.5rem;border-radius:10px;font-size:.85rem;opacity:0;transition:all .3s;z-index:999;pointer-events:none;box-shadow:0 8px 30px rgba(0,0,0,.4)}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
#toast.success{border-color:var(--green);color:#6ee7b7}
#toast.error{border-color:var(--red);color:#fca5a5}
.modal-overlay{display:none;position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.65);backdrop-filter:blur(4px);place-items:center}
.modal-overlay.active{display:grid}
.modal{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:2rem;width:90%;max-width:500px;animation:modalIn .25s ease}
@keyframes modalIn{from{transform:scale(.95);opacity:0}}
.modal h2{font-family:var(--serif);margin-bottom:.5rem;font-size:1.2rem}
.modal p{color:var(--muted);font-size:.9rem;margin-bottom:1.5rem}
.modal-actions{display:flex;gap:.8rem;justify-content:flex-end}
@media(max-width:900px){main{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <div class="logo-mark">🏥</div>
  <div class="brand"><h1>MIRA</h1><p>Medical Intelligence · Health Prediction</p></div>
  <div class="header-stats">
    <div class="stat-val" id="stat-total">0</div>
    <div class="stat-label">Patients</div>
  </div>
</header>
<main>
  <div class="panel" style="position:sticky;top:1.5rem">
    <div class="panel-header">
      <div class="panel-title"><span id="form-icon">✦</span><span id="form-title">New Patient Record</span></div>
      <button class="btn btn-ghost" id="btn-cancel" style="display:none" onclick="resetForm()">Cancel</button>
    </div>
    <div class="panel-body">
      <div id="error-list" class="error-list" style="display:none"><ul></ul></div>
      <div class="field"><label>Full Name</label><input type="text" id="f-name" placeholder="e.g. Janvi Malve"/></div>
      <div class="form-row">
        <div class="field"><label>Date of Birth</label><input type="date" id="f-dob"/></div>
        <div class="field"><label>Email Address</label><input type="email" id="f-email" placeholder="name@email.com"/></div>
      </div>
      <div style="margin:.4rem 0 .6rem;font-size:.72rem;font-weight:700;color:var(--accent2);text-transform:uppercase;letter-spacing:.08em">Blood Test Values</div>
      <div class="blood-grid">
        <div><label>Glucose <span style="color:var(--muted);font-size:.65rem">(mg/dL)</span></label><input type="number" id="f-glucose" placeholder="85" step="0.1" min="0"/></div>
        <div><label>Haemoglobin <span style="color:var(--muted);font-size:.65rem">(g/dL)</span></label><input type="number" id="f-haemoglobin" placeholder="13.5" step="0.1" min="0"/></div>
        <div><label>Cholesterol <span style="color:var(--muted);font-size:.65rem">(mg/dL)</span></label><input type="number" id="f-cholesterol" placeholder="190" step="0.1" min="0"/></div>
      </div>
      <button class="btn btn-primary" id="btn-submit" onclick="submitForm()">
        <span id="btn-text">✦ Generate AI Prediction & Save</span>
        <span id="btn-spinner" class="spinner" style="display:none"></span>
      </button>
    </div>
  </div>
  <div class="panel">
    <div class="panel-header"><div class="panel-title">📋 Patient Records</div></div>
    <div class="panel-body" style="padding-bottom:.5rem">
      <div class="search-bar">
        <span class="search-icon">🔍</span>
        <input type="text" id="search" placeholder="Search by name or email…" oninput="loadPatients(this.value)"/>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Patient</th><th>DOB</th><th>Blood Values</th><th>AI Remarks</th><th>Actions</th></tr></thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
    </div>
  </div>
</main>
<div class="modal-overlay" id="del-modal">
  <div class="modal">
    <h2>Delete Patient Record?</h2>
    <p>This action cannot be undone.</p>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn btn-danger" onclick="confirmDelete()">Delete</button>
    </div>
  </div>
</div>
<div id="toast"></div>
<script>
var editId = null;
var delId  = null;

function toast(msg, type) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + (type||'success');
  setTimeout(function(){ t.className=''; }, 3000);
}
function setLoading(on) {
  document.getElementById('btn-submit').disabled = on;
  document.getElementById('btn-text').style.display    = on ? 'none'         : 'inline';
  document.getElementById('btn-spinner').style.display = on ? 'inline-block' : 'none';
}
function badge(remarks) {
  var r = (remarks||'').toLowerCase();
  if (r.indexOf('normal')>=0||r.indexOf('within')>=0||r.indexOf('no immediate')>=0) return '<span class="badge badge-green">✓ Normal</span>';
  if (r.indexOf('diabetes')>=0||r.indexOf('anaemia')>=0||r.indexOf('cardiovascular')>=0||r.indexOf('high cholesterol')>=0) return '<span class="badge badge-red">⚠ High Risk</span>';
  return '<span class="badge badge-amber">⚡ Review</span>';
}
function fmtDate(s) {
  if (!s) return '—';
  var p = s.split('-'); return p[2]+'/'+p[1]+'/'+p[0];
}
function esc(s) {
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderTable(rows) {
  document.getElementById('stat-total').textContent = rows.length;
  var tb = document.getElementById('tbody');
  if (!rows.length) {
    tb.innerHTML = '<tr><td colspan="5" class="empty-state"><div>🩺</div><div>No patient records found.</div></td></tr>';
    return;
  }
  var html = '';
  for (var i=0; i<rows.length; i++) {
    var p = rows[i];
    var pid = Number(p.id);
    html += '<tr>';
    html += '<td><div class="name-cell">'+esc(p.full_name)+'</div><div class="email-cell">'+esc(p.email)+'</div></td>';
    html += '<td>'+fmtDate(p.dob)+'</td>';
    html += '<td style="font-size:.78rem;line-height:1.8">🩸 Glucose: <strong>'+p.glucose+'</strong><br>💉 Hb: <strong>'+p.haemoglobin+'</strong><br>🫀 Chol: <strong>'+p.cholesterol+'</strong></td>';
    html += '<td>'+badge(p.remarks)+'<div class="remarks-cell" style="margin-top:.3rem">'+esc(p.remarks||'Pending…')+'</div></td>';
    html += '<td><div class="actions-cell">';
    html += '<button class="btn btn-edit"   onclick="editPatient('+pid+')">✏ Edit</button>';
    html += '<button class="btn btn-danger" onclick="openModal('+pid+')">🗑</button>';
    html += '</div></td></tr>';
  }
  tb.innerHTML = html;
}

function loadPatients(q) {
  fetch('/api/patients?q='+encodeURIComponent(q||''))
    .then(function(r){ return r.json(); })
    .then(renderTable);
}

function getForm() {
  return {
    full_name:   document.getElementById('f-name').value.trim(),
    dob:         document.getElementById('f-dob').value,
    email:       document.getElementById('f-email').value.trim(),
    glucose:     document.getElementById('f-glucose').value,
    haemoglobin: document.getElementById('f-haemoglobin').value,
    cholesterol: document.getElementById('f-cholesterol').value
  };
}
function showErrors(errs) {
  var el = document.getElementById('error-list');
  el.style.display = 'block';
  el.querySelector('ul').innerHTML = errs.map(function(e){ return '<li>'+e+'</li>'; }).join('');
}
function clearErrors() { document.getElementById('error-list').style.display='none'; }

function resetForm() {
  editId = null;
  ['f-name','f-dob','f-email','f-glucose','f-haemoglobin','f-cholesterol'].forEach(function(id){ document.getElementById(id).value=''; });
  clearErrors();
  document.getElementById('form-title').textContent = 'New Patient Record';
  document.getElementById('form-icon').textContent  = '✦';
  document.getElementById('btn-text').textContent   = '✦ Generate AI Prediction & Save';
  document.getElementById('btn-cancel').style.display = 'none';
}

function submitForm() {
  clearErrors();
  setLoading(true);
  var data = getForm();
  var url    = editId ? '/api/patients/'+editId : '/api/patients';
  var method = editId ? 'PUT' : 'POST';
  fetch(url, {method:method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)})
    .then(function(r){ return r.json().then(function(j){ return {ok:r.ok,j:j}; }); })
    .then(function(res) {
      if (!res.ok) { showErrors(res.j.errors||[res.j.error]); return; }
      toast(editId ? '✓ Record updated' : '✓ Saved with AI prediction');
      resetForm(); loadPatients('');
    })
    .catch(function(){ toast('Network error','error'); })
    .finally(function(){ setLoading(false); });
}

function editPatient(pid) {
  fetch('/api/patients/'+pid)
    .then(function(r){ return r.json(); })
    .then(function(p) {
      editId = pid;
      document.getElementById('f-name').value        = p.full_name;
      document.getElementById('f-dob').value          = p.dob;
      document.getElementById('f-email').value        = p.email;
      document.getElementById('f-glucose').value      = p.glucose;
      document.getElementById('f-haemoglobin').value  = p.haemoglobin;
      document.getElementById('f-cholesterol').value  = p.cholesterol;
      document.getElementById('form-title').textContent = 'Edit Record';
      document.getElementById('form-icon').textContent  = '✏';
      document.getElementById('btn-text').textContent   = '✦ Update & Re-run AI Prediction';
      document.getElementById('btn-cancel').style.display = 'inline-flex';
      window.scrollTo({top:0,behavior:'smooth'});
    });
}

function openModal(pid) {
  console.log('openModal called with pid='+pid);
  delId = pid;
  document.getElementById('del-modal').classList.add('active');
}
function closeModal() {
  delId = null;
  document.getElementById('del-modal').classList.remove('active');
}
function confirmDelete() {
  console.log('confirmDelete called, delId='+delId);
  if (!delId) { toast('No patient selected','error'); return; }
  var pid = delId;
  closeModal();
  fetch('/api/patients/'+pid, {method:'DELETE'})
    .then(function(r){ return r.json().then(function(j){ return {ok:r.ok,j:j}; }); })
    .then(function(res) {
      if (res.ok) { toast('✓ Record deleted'); loadPatients(''); }
      else { toast('Delete failed: '+res.j.error,'error'); }
    })
    .catch(function(e){ toast('Network error','error'); console.error(e); });
}

loadPatients('');
</script>
</body>
</html>"""

if __name__ == "__main__":
    app.run(debug=True, port=5000)
