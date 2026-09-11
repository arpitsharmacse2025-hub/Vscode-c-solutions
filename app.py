import os, re, sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-key')
DB = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'lost_found.db'))


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, roll_no TEXT UNIQUE NOT NULL,
      email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT DEFAULT 'student');
    CREATE TABLE IF NOT EXISTS items (
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      item_type TEXT NOT NULL CHECK(item_type IN ('LOST','FOUND')), item_name TEXT NOT NULL,
      category TEXT NOT NULL, brand TEXT, color TEXT, location TEXT NOT NULL,
      item_date TEXT NOT NULL, description TEXT, status TEXT DEFAULT 'UNRESOLVED',
      FOREIGN KEY(user_id) REFERENCES users(id));
    CREATE TABLE IF NOT EXISTS claims (
      id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, claimant_id INTEGER NOT NULL,
      claim_text TEXT NOT NULL, proof TEXT, status TEXT DEFAULT 'PENDING', created_at TEXT NOT NULL,
      FOREIGN KEY(item_id) REFERENCES items(id), FOREIGN KEY(claimant_id) REFERENCES users(id));
    CREATE TABLE IF NOT EXISTS matches (
      id INTEGER PRIMARY KEY AUTOINCREMENT, lost_item_id INTEGER NOT NULL, found_item_id INTEGER NOT NULL,
      score INTEGER NOT NULL, UNIQUE(lost_item_id, found_item_id));
    ''')
    admin = con.execute('SELECT id FROM users WHERE email=?', ('admin@campus.local',)).fetchone()
    if not admin:
        con.execute('INSERT INTO users(name,roll_no,email,password,role) VALUES(?,?,?,?,?)',
                     ('Campus Admin','ADMIN','admin@campus.local',generate_password_hash('admin123'),'admin'))
    con.commit(); con.close()


def norm(s): return re.sub(r'\s+', ' ', (s or '').strip().lower())

def keyword_score(a,b):
    wa=set(re.findall(r'[a-z0-9]+',norm(a))); wb=set(re.findall(r'[a-z0-9]+',norm(b)))
    return min(10, round(10*len(wa&wb)/max(1,min(len(wa),len(wb))))) if wa and wb else 0

def date_close(a,b):
    try:
        days=abs((datetime.strptime(a,'%Y-%m-%d')-datetime.strptime(b,'%Y-%m-%d')).days)
        return 10 if days==0 else 7 if days<=1 else 4 if days<=3 else 0
    except: return 0

def match_score(lost,found):
    score=0
    if norm(lost['category'])==norm(found['category']): score+=25
    if lost['brand'] and found['brand'] and norm(lost['brand'])==norm(found['brand']): score+=20
    if lost['color'] and found['color'] and norm(lost['color'])==norm(found['color']): score+=15
    if norm(lost['location'])==norm(found['location']): score+=20
    score+=date_close(lost['item_date'],found['item_date'])
    score+=keyword_score(lost['description'],found['description'])
    score+=min(10,keyword_score(lost['item_name'],found['item_name']))
    return min(100,score)

def generate_matches():
    con=db(); lost=con.execute("SELECT * FROM items WHERE item_type='LOST' AND status='UNRESOLVED'").fetchall(); found=con.execute("SELECT * FROM items WHERE item_type='FOUND' AND status='UNRESOLVED'").fetchall()
    for l in lost:
        for f in found:
            s=match_score(l,f)
            if s>=50:
                con.execute('INSERT INTO matches(lost_item_id,found_item_id,score) VALUES(?,?,?) ON CONFLICT(lost_item_id,found_item_id) DO UPDATE SET score=excluded.score',(l['id'],f['id'],s))
    con.commit(); con.close()


def current_user():
    uid=session.get('user_id')
    if not uid: return None
    con=db(); u=con.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); con.close(); return u

def login_required(fn):
    @wraps(fn)
    def wrapper(*a,**kw):
        if not current_user(): return redirect(url_for('login'))
        return fn(*a,**kw)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a,**kw):
        u=current_user()
        if not u or u['role']!='admin': abort(403)
        return fn(*a,**kw)
    return wrapper

@app.context_processor
def inject(): return {'user': current_user()}

@app.route('/')
def index(): return redirect(url_for('dashboard')) if current_user() else redirect(url_for('login'))

@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=request.form['name'].strip(); roll=request.form['roll_no'].strip(); email=request.form['email'].strip().lower(); pw=request.form['password']
        if not all([name,roll,email,pw]): flash('Please fill every field.','error')
        else:
            try:
                con=db(); con.execute('INSERT INTO users(name,roll_no,email,password) VALUES(?,?,?,?)',(name,roll,email,generate_password_hash(pw))); con.commit(); con.close()
                flash('Account created. Please log in.','success'); return redirect(url_for('login'))
            except sqlite3.IntegrityError: flash('Roll number or email already exists.','error')
    return render_template('register.html')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        email=request.form['email'].strip().lower(); pw=request.form['password']; con=db(); u=con.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone(); con.close()
        if u and check_password_hash(u['password'],pw): session['user_id']=u['id']; return redirect(url_for('dashboard'))
        flash('Invalid email or password.','error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    con=db();
    if current_user()['role']=='admin':
        stats={k:con.execute(q).fetchone()['n'] for k,q in {
          'total':'SELECT COUNT(*) n FROM items','lost':"SELECT COUNT(*) n FROM items WHERE item_type='LOST'",
          'found':"SELECT COUNT(*) n FROM items WHERE item_type='FOUND'",'claims':"SELECT COUNT(*) n FROM claims WHERE status='PENDING'",
          'returned':"SELECT COUNT(*) n FROM items WHERE status='RETURNED'"}.items()}; con.close(); return render_template('admin.html',stats=stats)
    con.close(); return render_template('dashboard.html')

@app.route('/report/<item_type>',methods=['GET','POST'])
@login_required
def report(item_type):
    if item_type not in ('LOST','FOUND'): abort(404)
    if request.method=='POST':
        fields=['item_name','category','brand','color','location','item_date','description']; vals=[request.form.get(x,'').strip() for x in fields]
        if not vals[0] or not vals[1] or not vals[4] or not vals[5]: flash('Item name, category, location and date are required.','error')
        else:
            con=db(); con.execute('INSERT INTO items(user_id,item_type,item_name,category,brand,color,location,item_date,description) VALUES(?,?,?,?,?,?,?,?,?)',(session['user_id'],item_type,*vals)); con.commit(); con.close(); generate_matches(); flash(f'{item_type.title()} report submitted.','success'); return redirect(url_for('dashboard'))
    return render_template('report.html',item_type=item_type)

@app.route('/search')
@login_required
def search():
    q=norm(request.args.get('q','')); con=db(); term=f'%{q}%'
    rows=con.execute("""SELECT i.*,u.name AS reporter FROM items i JOIN users u ON u.id=i.user_id
      WHERE i.status!='RETURNED' AND (lower(i.item_name) LIKE ? OR lower(i.category) LIKE ? OR lower(i.brand) LIKE ? OR lower(i.color) LIKE ? OR lower(i.location) LIKE ? OR lower(i.description) LIKE ?)
      ORDER BY i.id DESC""",(term,)*6).fetchall(); con.close(); return render_template('search.html',rows=rows,q=q)

@app.route('/claim/<int:item_id>',methods=['GET','POST'])
@login_required
def claim(item_id):
    con=db(); item=con.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone(); con.close()
    if not item or item['item_type']!='FOUND' or item['status']=='RETURNED': abort(404)
    if request.method=='POST':
        text=request.form.get('claim_text','').strip(); proof=request.form.get('proof','').strip()
        if not text: flash('Please provide a reason.','error')
        else:
            con=db(); con.execute('INSERT INTO claims(item_id,claimant_id,claim_text,proof,created_at) VALUES(?,?,?,?,?)',(item_id,session['user_id'],text,proof,datetime.now().isoformat(timespec='seconds'))); con.commit(); con.close(); flash('Claim sent to the admin.','success'); return redirect(url_for('my_claims'))
    return render_template('claim.html',item=item)

@app.route('/reports')
@login_required
def reports():
    con=db(); rows=con.execute('SELECT * FROM items WHERE user_id=? ORDER BY id DESC',(session['user_id'],)).fetchall(); con.close(); return render_template('reports.html',rows=rows)

@app.route('/claims')
@login_required
def my_claims():
    con=db(); rows=con.execute('SELECT c.*,i.item_name FROM claims c JOIN items i ON i.id=c.item_id WHERE c.claimant_id=? ORDER BY c.id DESC',(session['user_id'],)).fetchall(); con.close(); return render_template('claims.html',rows=rows)

@app.route('/matches')
@login_required
def matches():
    generate_matches(); con=db(); rows=con.execute('SELECT m.*,l.item_name lost_name,f.item_name found_name FROM matches m JOIN items l ON l.id=m.lost_item_id JOIN items f ON f.id=m.found_item_id WHERE l.user_id=? OR f.user_id=? ORDER BY m.score DESC',(session['user_id'],session['user_id'])).fetchall(); con.close(); return render_template('matches.html',rows=rows)

@app.route('/admin/claims')
@admin_required
def admin_claims():
    con=db(); rows=con.execute('SELECT c.*,i.item_name,u.name claimant,u.email FROM claims c JOIN items i ON i.id=c.item_id JOIN users u ON u.id=c.claimant_id ORDER BY c.id DESC').fetchall(); con.close(); return render_template('admin_claims.html',rows=rows)

@app.post('/admin/claims/<int:claim_id>/<action>')
@admin_required
def decide_claim(claim_id,action):
    if action not in ('approve','reject'): abort(404)
    con=db(); claim=con.execute('SELECT * FROM claims WHERE id=?',(claim_id,)).fetchone()
    if not claim: con.close(); abort(404)
    if action=='approve':
        con.execute("UPDATE claims SET status='APPROVED' WHERE id=?",(claim_id,)); con.execute("UPDATE claims SET status='REJECTED' WHERE id!=? AND item_id=? AND status='PENDING'",(claim_id,claim['item_id'])); con.execute("UPDATE items SET status='RETURNED' WHERE id=?",(claim['item_id'],))
    else: con.execute("UPDATE claims SET status='REJECTED' WHERE id=?",(claim_id,))
    con.commit(); con.close(); flash('Claim updated.','success'); return redirect(url_for('admin_claims'))

@app.route('/admin/reports')
@admin_required
def admin_reports():
    con=db(); rows=con.execute('SELECT i.*,u.name student,u.email FROM items i JOIN users u ON u.id=i.user_id ORDER BY i.id DESC').fetchall(); con.close(); return render_template('admin_reports.html',rows=rows)

@app.errorhandler(403)
def forbidden(e): return render_template('error.html',code=403,message='You do not have permission to access this page.'),403

@app.errorhandler(404)
def not_found(e): return render_template('error.html',code=404,message='Page not found.'),404

init_db()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
