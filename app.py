from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.utils import secure_filename
from datetime import datetime
import cloudinary
import cloudinary.uploader
import os
import csv
import io
import pytz
from functools import wraps

app = Flask(__name__)
app.secret_key = 'ojt_secret_key_123'

# --- CLOUDINARY CONFIGURATION ---
cloudinary.config( 
    cloud_name = "dubnko427", 
    api_key = "611318728434917", 
    api_secret = "-QIoOqnmGjvM5LcawvFo_SmD9MU" 
)

# --- CONFIGURATION (POSTGRESQL & SQLITE) ---
basedir = os.path.abspath(os.path.dirname(__file__))

# 1. First, try to get the URL from Render's environment variables
database_url = os.environ.get('DATABASE_URL')

# 2. If Render hasn't set the variable yet, use your specific link as a backup
if not database_url:
    database_url = "postgresql://ojt_db_1rjk_user:gCvGKVRPrwcVR3vC7QxQJqNO4uIk3R8J@dpg-d6of7jua2pns738csv8g-a/ojt_db_1rjk"

# 3. Ensure it starts with postgresql:// (Required for SQLAlchemy 2.0+)
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'profile_pics')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --- TIMEZONE HELPER ---
def get_ph_time():
    """Returns the current time in Philippine Standard Time (PHT)."""
    ph_timezone = pytz.timezone('Asia/Manila')
    return datetime.now(pytz.utc).astimezone(ph_timezone)

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    student_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), default="Intern")
    program = db.Column(db.String(100), default="Program") 
    email = db.Column(db.String(120), default="")
    phone = db.Column(db.String(20), default="")
    department = db.Column(db.String(100), default="") 
    profile_pic = db.Column(db.String(500), default="default.png")
    target_hours = db.Column(db.Float, default=480.0) 
    logs = db.relationship('Attendance', backref='user', lazy=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(50))      
    location = db.Column(db.String(100), default="Office")
    m_in = db.Column(db.String(20), default="--:--")
    m_out = db.Column(db.String(20), default="--:--")
    a_in = db.Column(db.String(20), default="--:--")
    a_out = db.Column(db.String(20), default="--:--")
    description = db.Column(db.Text, default="")
    hours = db.Column(db.Float, default=0.0)

# --- AUTO-MIGRATION LOGIC ---
with app.app_context():
    db.create_all()
    # This block manually checks if the 'program' column exists and adds it if missing
    try:
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS program VARCHAR(100) DEFAULT \'Program\''))
            conn.commit()
    except Exception as e:
        print(f"Migration skip/error: {e}")

# --- AUTH DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# --- PAGE ROUTES ---

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session.get('user_id'))
    if not user:
        session.clear()
        return redirect(url_for('login_page'))

    logs_2026 = Attendance.query.filter(Attendance.user_id == user.id, Attendance.date.like('%2026%')).all()
    total_hours = sum(log.hours for log in logs_2026)
    
    target = user.target_hours or 480.0
    remaining_hours = max(0, target - total_hours)
    
    hours_per_day = 8.0
    remaining_days = remaining_hours / hours_per_day

    user.total_hours = round(total_hours, 2)
    user.remaining_hours = round(remaining_hours, 2)
    user.remaining_days = int(remaining_days) if remaining_days % 1 == 0 else round(remaining_days, 1)
    
    today_str = get_ph_time().strftime('%Y-%m-%d')
    today_log = Attendance.query.filter_by(user_id=user.id, date=today_str).first()
    today_task = today_log.description if today_log else ""

    return render_template('dashboard.html', user=user, today_task=today_task)

@app.route('/attendance')
@login_required
def attendance_page():
    user = User.query.get(session.get('user_id'))
    return render_template('attendance.html', user=user, user_location=user.department)

@app.route('/log')
@login_required
def history():
    user = User.query.get(session.get('user_id'))
    logs = Attendance.query.filter(
        Attendance.user_id == user.id, 
        Attendance.date.like('%2026%')
    ).order_by(Attendance.date.desc()).all()
        
    total_hours = sum(log.hours for log in logs)
    return render_template('history.html', user=user, logs=logs, total_hours=round(total_hours, 2))

@app.route('/profile')
@login_required
def profile_page():
    user = User.query.get(session.get('user_id'))
    return render_template('profile.html', user=user)

@app.route('/reports')
@login_required
def reports():
    user = User.query.get(session.get('user_id'))
    return render_template('reports.html', user=user)

# --- API & ACTION ROUTES ---

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    student_id = data.get('student_id', '').strip()
    department = data.get('department', '').strip()
    
    if not username or not password or not student_id:
        return jsonify({"success": False, "message": "All fields are required"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"success": False, "message": "Username already exists"}), 400
    
    new_user = User(username=username, password=password, student_id=student_id, name=username, department=department)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get('username'), password=data.get('password')).first()
    if user:
        session['user_id'] = user.id
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

@app.route('/api/submit_task', methods=['POST'])
@login_required
def submit_task():
    data = request.json
    description = data.get('description', '').strip()
    today_str = get_ph_time().strftime('%Y-%m-%d')
    user_id = session['user_id']

    log = Attendance.query.filter_by(user_id=user_id, date=today_str).first()
    if not log:
        log = Attendance(user_id=user_id, date=today_str, description=description)
        db.session.add(log)
    else:
        log.description = description
    
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/attendance/action', methods=['POST'])
@login_required
def attendance_action():
    data = request.json
    action_type = data.get('type') 
    
    ph_now = get_ph_time()
    today_str = ph_now.strftime('%Y-%m-%d')
    time_str = ph_now.strftime('%H:%M')
    user_id = session['user_id']

    log = Attendance.query.filter_by(user_id=user_id, date=today_str).first()
    if not log:
        user = User.query.get(user_id)
        log = Attendance(user_id=user_id, date=today_str, location=user.department)
        db.session.add(log)

    setattr(log, action_type, time_str)

    if action_type in ['m_out', 'a_out']:
        fmt = '%H:%M'
        try:
            m_hrs = 0
            if log.m_in != '--:--' and log.m_out != '--:--':
                m_hrs = (datetime.strptime(log.m_out, fmt) - datetime.strptime(log.m_in, fmt)).total_seconds() / 3600
            
            a_hrs = 0
            if log.a_in != '--:--' and log.a_out != '--:--':
                a_hrs = (datetime.strptime(log.a_out, fmt) - datetime.strptime(log.a_in, fmt)).total_seconds() / 3600
            
            log.hours = round(max(0, m_hrs + a_hrs), 2)
        except:
            pass

    db.session.commit()
    return jsonify({"success": True, "time": time_str})

@app.route('/api/log-past', methods=['POST'])
@login_required
def log_past():
    data = request.json
    try:
        new_log = Attendance(
            user_id=session['user_id'],
            date=data.get('date'),
            location=data.get('location', 'Office'),
            m_in=data.get('m_in', '--:--'), 
            m_out=data.get('m_out', '--:--'),
            a_in=data.get('a_in', '--:--'), 
            a_out=data.get('a_out', '--:--'),
            hours=round(float(data.get('hours', 0)), 2),
            description=data.get('description', '')
        )
        db.session.add(new_log)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    user.name = request.form.get('name', user.name)
    user.program = request.form.get('program', user.program)
    user.email = request.form.get('email', user.email)
    user.phone = request.form.get('phone', user.phone)
    user.department = request.form.get('department', user.department)
    
    if request.form.get('password'):
        user.password = request.form.get('password')

    if 'profile_pic' in request.files:
        file = request.files['profile_pic']
        if file and file.filename != '':
            upload_result = cloudinary.uploader.upload(file)
            user.profile_pic = upload_result['secure_url']

    db.session.commit()
    return redirect(url_for('profile_page'))

@app.route('/export/pdf')
@login_required
def export_pdf():
    user_id = session.get('user_id') 
    user = User.query.get(user_id)
    
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    query = Attendance.query.filter_by(user_id=user_id)
    if start_date:
        query = query.filter(Attendance.date >= start_date)
    if end_date:
        query = query.filter(Attendance.date <= end_date)
        
    logs = query.order_by(Attendance.date.asc()).all()
    total_period_hours = round(sum(log.hours for log in logs), 2)
    
    return render_template('report_print.html', 
                           user=user, 
                           logs=logs, 
                           start=start_date, 
                           end=end_date, 
                           total_period_hours=total_period_hours,
                           now=get_ph_time())

@app.route('/update_log', methods=['POST'])
@login_required
def update_log():
    log_id = request.form.get('log_id')
    log_entry = Attendance.query.filter_by(id=log_id, user_id=session['user_id']).first()
    if log_entry:
        log_entry.date = request.form.get('date')
        log_entry.m_in = request.form.get('m_in')
        log_entry.m_out = request.form.get('m_out')
        log_entry.a_in = request.form.get('a_in')
        log_entry.a_out = request.form.get('a_out')
        log_entry.description = request.form.get('description')
        try:
            fmt = '%H:%M'
            m = (datetime.strptime(log_entry.m_out, fmt) - datetime.strptime(log_entry.m_in, fmt)).total_seconds() / 3600
            a = (datetime.strptime(log_entry.a_out, fmt) - datetime.strptime(log_entry.a_in, fmt)).total_seconds() / 3600
            log_entry.hours = round(max(0, m + a), 2)
        except: pass
        db.session.commit()
    return redirect(url_for('history'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)