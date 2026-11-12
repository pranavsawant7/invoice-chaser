"""Invoice Chaser: Claude creates invoices over MCP; this app hosts, edits, tracks and chases them. No AI inside."""
import os, json, hmac, hashlib, secrets, html, datetime as dt, urllib.request
import psycopg2, psycopg2.extras
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response

DBURL = os.getenv("DATABASE_URL")
SECRET = os.getenv("SECRET", "dev-secret-change-me")
BASE_URL = os.getenv("BASE_URL", "")
app = FastAPI()
e = html.escape

class Conn:
    def __init__(s):
        s.c = psycopg2.connect(DBURL); s.cur = s.c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    def execute(s, q, a=()): s.cur.execute(q.replace("?", "%s"), a); return s.cur
    def executescript(s, q): s.cur.execute(q)
    def commit(s): s.c.commit()
    def close(s): s.c.close()

def db(): return Conn()

def hpw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000).hex()

def mkuser(c, email, pw):
    c.execute("insert into users(email,pw,token) values(?,?,?)", (email.lower().strip(), hpw(pw), secrets.token_urlsafe(24)))

def init():
    c = db()
    c.executescript("""create table if not exists users(id serial primary key, email text unique, pw text, token text unique);
create table if not exists invoices(id serial primary key, user_id integer, public_id text unique, client_name text, client_email text,
 items text, currency text, due_date text, notes text, status text default 'sent', created text, viewed_at text, paid_at text, last_reminder text);""")
    if not c.execute("select 1 from users").fetchone():
        mkuser(c, "demo@invoicechaser.app", "demo1234")
    c.commit(); c.close()
init()

def sign(uid): return f"{uid}.{hmac.new(SECRET.encode(), str(uid).encode(), 'sha256').hexdigest()}"
def user_of(req):
    v = req.cookies.get("s", "")
    uid, _, sig = v.partition(".")
    if uid.isdigit() and hmac.compare_digest(sign(uid), v):
        c = db(); u = c.execute("select * from users where id=?", (uid,)).fetchone(); c.close(); return u

def base(req): return (BASE_URL or str(req.base_url)).rstrip("/")
def total(items): return sum(float(i["quantity"]) * float(i["unit_price"]) for i in items)
def money(cur, n): return f"{cur} {n:,.2f}"
def today(): return dt.date.today().isoformat()
def now(): return dt.datetime.utcnow().isoformat(timespec="seconds")

CSS = """body{font:16px system-ui;max-width:860px;margin:2rem auto;padding:0 1rem;color:#16181d}a{color:#4a4af4}
table{width:100%;border-collapse:collapse}td,th{padding:.55rem;border-bottom:1px solid #e6e8ee;text-align:left}
input,textarea,select{width:100%;padding:.55rem;margin:.25rem 0 .9rem;border:1px solid #cfd3dc;border-radius:8px;font:inherit;box-sizing:border-box}
button{background:#4a4af4;color:#fff;border:0;padding:.6rem 1.1rem;border-radius:8px;font:inherit;cursor:pointer}
.b{padding:.15rem .6rem;border-radius:99px;font-size:.8rem;background:#eef;}.paid{background:#d9f7e4}.overdue{background:#fde0e0}
.box{background:#f4f5f9;padding:1rem;border-radius:12px;margin:1rem 0;word-break:break-all}"""
def page(title, body): return HTMLResponse(f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>{e(title)}</title><style>{CSS}</style>{body}")

def status_of(r):
    if r["status"] == "paid": return "paid"
    return "overdue" if r["due_date"] and r["due_date"] < today() else r["status"]

@app.get("/", response_class=HTMLResponse)
def home(req: Request, err: str = ""):
    u = user_of(req)
    if not u:
        return page("Invoice Chaser", f"""<h1>Invoice Chaser</h1><p>Tell Claude to invoice a client. We host the invoice, track when it's viewed, and chase payment.</p>
<p style=color:#c00>{e(err)}</p><h3>Log in</h3><form method=post action=/login>Email<input name=email>Password<input name=password type=password><button>Log in</button></form>
<h3>Sign up</h3><form method=post action=/signup>Email<input name=email>Password<input name=password type=password><button>Create account</button></form>
<p>Test login: demo@invoicechaser.app / demo1234</p>""")
    c = db(); rows = c.execute("select * from invoices where user_id=? order by id desc", (u["id"],)).fetchall(); c.close()
    tr = "".join(f"<tr><td><a href=/invoice/{r['id']}>#{r['id']}</a></td><td>{e(r['client_name'])}</td><td>{money(r['currency'], total(json.loads(r['items'])))}</td>"
                 f"<td>{e(r['due_date'] or '')}</td><td><span class='b {status_of(r)}'>{status_of(r)}</span>{' · viewed' if r['viewed_at'] else ''}</td></tr>" for r in rows)
    return page("Dashboard", f"""<h1>Invoices</h1><p>{e(u['email'])} · <a href=/logout>Log out</a></p>
<div class=box><b>Connect to Claude</b><br>Settings → Connectors → Add custom connector → paste:<br><code>{base(req)}/mcp/{u['token']}</code></div>
<table><tr><th>#<th>Client<th>Amount<th>Due<th>Status</tr>{tr or '<tr><td colspan=5>No invoices yet. Ask Claude to create one.'}</table>""")

@app.post("/signup")
def signup(email: str = Form(...), password: str = Form(...)):
    c = db()
    try: mkuser(c, email, password); c.commit()
    except psycopg2.IntegrityError: return RedirectResponse("/?err=Email+already+registered", 303)
    uid = c.execute("select id from users where email=?", (email.lower().strip(),)).fetchone()["id"]; c.close()
    r = RedirectResponse("/", 303); r.set_cookie("s", sign(uid), httponly=True, max_age=86400 * 30); return r

@app.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    c = db(); u = c.execute("select * from users where email=?", (email.lower().strip(),)).fetchone(); c.close()
    if not u or not hmac.compare_digest(hpw(password, u["pw"].split("$")[0]), u["pw"]): return RedirectResponse("/?err=Wrong+email+or+password", 303)
    r = RedirectResponse("/", 303); r.set_cookie("s", sign(u["id"]), httponly=True, max_age=86400 * 30); return r

@app.get("/logout")
def logout():
    r = RedirectResponse("/", 303); r.delete_cookie("s"); return r

def parse_items(text):
    out = []
    for line in text.strip().splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) == 3 and p[0]: out.append({"description": p[0], "quantity": float(p[1]), "unit_price": float(p[2])})
    return out

@app.get("/invoice/{iid}", response_class=HTMLResponse)
def edit_form(req: Request, iid: int):
    u = user_of(req)
    if not u: return RedirectResponse("/", 303)
    c = db(); r = c.execute("select * from invoices where id=? and user_id=?", (iid, u["id"])).fetchone(); c.close()
    if not r: return HTMLResponse("Not found", 404)
    items = "\n".join(f"{i['description']} | {i['quantity']:g} | {i['unit_price']:g}" for i in json.loads(r["items"]))
    link = f"{base(req)}/i/{r['public_id']}"
    return page(f"Invoice #{iid}", f"""<p><a href=/>← Back</a></p><h1>Invoice #{iid}</h1>
<div class=box>Client link: <a href="{link}">{link}</a><br>Viewed: {e(r['viewed_at'] or 'not yet')} · Paid: {e(r['paid_at'] or 'no')}</div>
<form method=post>Client name<input name=client_name value="{e(r['client_name'])}">Client email<input name=client_email value="{e(r['client_email'] or '')}">
Line items (description | qty | unit price)<textarea name=items rows=5>{e(items)}</textarea>
Currency<input name=currency value="{e(r['currency'])}">Due date (YYYY-MM-DD)<input name=due_date value="{e(r['due_date'] or '')}">
Notes<textarea name=notes rows=3>{e(r['notes'] or '')}</textarea><button>Save changes</button></form>
<form method=post action=/invoice/{iid}/paid style=margin-top:1rem><button style=background:#1f9d55>Mark as paid</button></form>""")

@app.post("/invoice/{iid}")
def save(req: Request, iid: int, client_name: str = Form(...), client_email: str = Form(""), items: str = Form(...),
         currency: str = Form("INR"), due_date: str = Form(""), notes: str = Form("")):
    u = user_of(req)
    if not u: return RedirectResponse("/", 303)
    c = db()
    c.execute("update invoices set client_name=?,client_email=?,items=?,currency=?,due_date=?,notes=? where id=? and user_id=?",
              (client_name, client_email, json.dumps(parse_items(items)), currency, due_date, notes, iid, u["id"])); c.commit(); c.close()
    return RedirectResponse(f"/invoice/{iid}", 303)

@app.post("/invoice/{iid}/paid")
def paid(req: Request, iid: int):
    u = user_of(req)
    if u:
        c = db(); c.execute("update invoices set status='paid', paid_at=? where id=? and user_id=?", (now(), iid, u["id"])); c.commit(); c.close()
    return RedirectResponse(f"/invoice/{iid}", 303)

@app.get("/i/{pid}", response_class=HTMLResponse)
def public(pid: str):
    c = db(); r = c.execute("select * from invoices where public_id=?", (pid,)).fetchone()
    if not r: return HTMLResponse("Not found", 404)
    if not r["viewed_at"]: c.execute("update invoices set viewed_at=? where id=?", (now(), r["id"])); c.commit()
    c.close()
    items = json.loads(r["items"])
    rows = "".join(f"<tr><td>{e(i['description'])}<td>{i['quantity']:g}<td>{money(r['currency'], i['unit_price'])}<td>{money(r['currency'], i['quantity']*i['unit_price'])}</tr>" for i in items)
    st = status_of(r)
    return page(f"Invoice #{r['id']}", f"""<h1>Invoice #{r['id']} <span class='b {st}'>{st}</span></h1><p>Billed to <b>{e(r['client_name'])}</b> · Due {e(r['due_date'] or 'on receipt')}</p>
<table><tr><th>Description<th>Qty<th>Rate<th>Amount</tr>{rows}</table><h2>Total: {money(r['currency'], total(items))}</h2><p>{e(r['notes'] or '')}</p>""")

def send_email(to, subject, body):
    key = os.getenv("RESEND_API_KEY")
    if not (key and to): return False
    req = urllib.request.Request("https://api.resend.com/emails", method="POST",
        data=json.dumps({"from": os.getenv("MAIL_FROM", "onboarding@resend.dev"), "to": [to], "subject": subject, "text": body}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try: urllib.request.urlopen(req, timeout=10); return True
    except Exception: return False

@app.post("/cron/remind")
def remind(req: Request, key: str = ""):
    """Hit daily from a cron service: /cron/remind?key=CRON_KEY. Emails clients of overdue unpaid invoices (needs RESEND_API_KEY)."""
    if key != os.getenv("CRON_KEY", "change-me"): return JSONResponse({"error": "forbidden"}, 403)
    c = db(); n = 0
    for r in c.execute("select * from invoices where status!='paid' and due_date<? and (last_reminder is null or last_reminder<?)", (today(), today())).fetchall():
        link = f"{base(req)}/i/{r['public_id']}"
        if send_email(r["client_email"], f"Reminder: invoice #{r['id']} is overdue", f"Hi {r['client_name']}, invoice #{r['id']} was due {r['due_date']}. View it here: {link}"):
            c.execute("update invoices set last_reminder=? where id=?", (today(), r["id"])); n += 1
    c.commit(); c.close(); return {"reminders_sent": n}

# ---------------- MCP (streamable HTTP, JSON-RPC, stateless) ----------------
ITEM = {"type": "object", "properties": {"description": {"type": "string"}, "quantity": {"type": "number"}, "unit_price": {"type": "number"}},
        "required": ["description", "quantity", "unit_price"]}
TOOLS = [
 {"name": "create_invoice", "description": "Create an invoice for a client. Returns the invoice id and a shareable client link.",
  "inputSchema": {"type": "object", "properties": {"client_name": {"type": "string"}, "client_email": {"type": "string"},
   "items": {"type": "array", "items": ITEM}, "currency": {"type": "string", "description": "e.g. INR, USD"},
   "due_in_days": {"type": "integer"}, "notes": {"type": "string"}}, "required": ["client_name", "items"]}},
 {"name": "list_invoices", "description": "List invoices with status (sent/paid/overdue) and whether the client viewed them.",
  "inputSchema": {"type": "object", "properties": {"status": {"type": "string", "description": "optional: sent, paid or overdue"}}}},
 {"name": "update_invoice", "description": "Edit an invoice by id. Only provided fields change.",
  "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}, "client_name": {"type": "string"}, "client_email": {"type": "string"},
   "items": {"type": "array", "items": ITEM}, "currency": {"type": "string"}, "due_date": {"type": "string", "description": "YYYY-MM-DD"}, "notes": {"type": "string"}}, "required": ["id"]}},
 {"name": "mark_paid", "description": "Mark an invoice as paid.", "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
]

def run_tool(uid, name, a, root):
    c = db()
    try:
        if name == "create_invoice":
            pid = secrets.token_urlsafe(8); due = (dt.date.today() + dt.timedelta(days=int(a.get("due_in_days", 15)))).isoformat()
            cur = c.execute("insert into invoices(user_id,public_id,client_name,client_email,items,currency,due_date,notes,created) values(?,?,?,?,?,?,?,?,?) returning id",
                (uid, pid, a["client_name"], a.get("client_email", ""), json.dumps(a["items"]), a.get("currency", "INR"), due, a.get("notes", ""), now()))
            new_id = cur.fetchone()["id"]; c.commit()
            return {"id": new_id, "total": money(a.get("currency", "INR"), total(a["items"])), "due_date": due,
                    "client_link": f"{root}/i/{pid}", "edit_in_dashboard": f"{root}/invoice/{new_id}"}
        if name == "list_invoices":
            out = []
            for r in c.execute("select * from invoices where user_id=? order by id desc", (uid,)).fetchall():
                s = status_of(r)
                if a.get("status") and a["status"] != s: continue
                out.append({"id": r["id"], "client": r["client_name"], "total": money(r["currency"], total(json.loads(r["items"]))),
                            "due": r["due_date"], "status": s, "viewed_by_client": bool(r["viewed_at"])})
            return out
        if name == "update_invoice":
            r = c.execute("select * from invoices where id=? and user_id=?", (a["id"], uid)).fetchone()
            if not r: return {"error": "invoice not found"}
            for k in ("client_name", "client_email", "currency", "due_date", "notes"):
                if k in a: c.execute(f"update invoices set {k}=? where id=?", (a[k], a["id"]))
            if "items" in a: c.execute("update invoices set items=? where id=?", (json.dumps(a["items"]), a["id"]))
            c.commit(); return {"ok": True, "id": a["id"]}
        if name == "mark_paid":
            c.execute("update invoices set status='paid', paid_at=? where id=? and user_id=?", (now(), a["id"], uid)); c.commit(); return {"ok": True}
        return {"error": "unknown tool"}
    finally: c.close()

@app.post("/mcp/{token}")
async def mcp(token: str, req: Request):
    c = db(); u = c.execute("select id from users where token=?", (token,)).fetchone(); c.close()
    if not u: return JSONResponse({"error": "bad token"}, 401)
    msg = await req.json(); m = msg.get("method", ""); rid = msg.get("id")
    if rid is None: return Response(status_code=202)
    ok = lambda r: JSONResponse({"jsonrpc": "2.0", "id": rid, "result": r})
    if m == "initialize":
        return ok({"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-03-26"), "capabilities": {"tools": {}},
                   "serverInfo": {"name": "invoice-chaser", "version": "1.0"}})
    if m == "ping": return ok({})
    if m == "tools/list": return ok({"tools": TOOLS})
    if m == "tools/call":
        p = msg["params"]
        try: res = run_tool(u["id"], p["name"], p.get("arguments", {}), base(req)); err = False
        except Exception as ex: res = {"error": str(ex)}; err = True
        return ok({"content": [{"type": "text", "text": json.dumps(res, indent=2)}], "isError": err})
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}})

@app.get("/mcp/{token}")
def mcp_get(token: str): return Response(status_code=405)
