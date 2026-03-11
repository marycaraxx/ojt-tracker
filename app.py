from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import csv
import io
from functools import wraps

app = Flask(__name__)
app.secret_key = 'ojt_secret_key_123'

# --- CONFIGURATION ---
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'ojt_tracker.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'profile_pics')

# Ensure the upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    student_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), default="Intern")
    email = db.Column(db.String(120), default="")
    phone = db.Column(db.String(20), default="")
    department = db.Column(db.String(100), default="") 
    profile_pic = db.Column(db.String(200), default="default.png")
    target_hours = db.Column(db.Float, default=480.0) 
    logs = db.relationship('Attendance', backref='user', lazy=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(50))      
    location = db.Column(db.String(100))
    m_in = db.Column(db.String(20))
    m_out = db.Column(db.String(20))
    a_in = db.Column(db.String(20))
    a_out = db.Column(db.String(20))
    description = db.Column(db.Text)
    hours = db.Column(db.Float, default=0.0)

with app.app_context():
    db.create_all()

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

    # Calculate total hours rendered for 2026
    logs_2026 = Attendance.query.filter(Attendance.user_id == user.id, Attendance.date.like('%2026%')).all()
    total_hours = sum(log.hours for log in logs_2026)
    
    target = user.target_hours or 480.0
    remaining_hours = max(0, target - total_hours)
    
    hours_per_day = 8.0
    remaining_days = remaining_hours / hours_per_day

    user.total_hours = round(total_hours, 2)
    user.remaining_hours = round(remaining_hours, 2)
    user.remaining_days = int(remaining_days) if remaining_days % 1 == 0 else round(remaining_days, 1)
    
    return render_template('dashboard.html', user=user)

@app.route('/attendance')
@login_required
def attendance_page():
    user = User.query.get(session.get('user_id'))
    if not user:
        session.clear()
        return redirect(url_for('login_page'))
    return render_template('attendance.html', user=user)

@app.route('/log')
@login_required
def history():
    user = User.query.get(session.get('user_id'))
    if not user:
        session.clear()
        return redirect(url_for('login_page'))
    
    # Updated: Now returns ALL logs for 2026 without the limit of 5
    logs = Attendance.query.filter(
        Attendance.user_id == user.id, 
        Attendance.date.like('%2026%')
    ).order_by(Attendance.date.desc()).all()
        
    total_hours = sum(log.hours for log in logs)
    user.total_hours = round(total_hours, 2)
    
    return render_template('history.html', user=user, logs=logs, total_hours=user.total_hours)

@app.route('/profile')
@login_required
def profile_page():
    user = User.query.get(session.get('user_id'))
    if not user:
        session.clear()
        return redirect(url_for('login_page'))
    return render_template('profile.html', user=user)

@app.route('/reports')
@login_required
def reports():
    user = User.query.get(session.get('user_id'))
    if not user:
        session.clear()
        return redirect(url_for('login_page'))
        
    return render_template('reports.html', user=user)

# --- API & ACTION ROUTES ---

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password')
    student_id = data.get('student_id', '').strip()
    
    if not username or not password or not student_id:
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"success": False, "message": "Username already exists"}), 400
    if User.query.filter_by(student_id=student_id).first():
        return jsonify({"success": False, "message": "Student ID already registered"}), 400
    
    new_user = User(username=username, password=password, student_id=student_id, name=username, target_hours=480.0)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"success": True, "message": "Account created!"})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get('username'), password=data.get('password')).first()
    
    if user:
        session['user_id'] = user.id
        return jsonify({"success": True}), 200
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

@app.route('/api/log-past', methods=['POST'])
@login_required
def log_past():
    data = request.json
    try:
        raw_date = data.get('date')
        if not raw_date or not raw_date.startswith('2026'):
            return jsonify({"success": False, "message": "Only 2026 logs are allowed"}), 400

        new_log = Attendance(
            user_id=session['user_id'],
            date=raw_date,
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
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 400

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    if not user:
        return redirect(url_for('login_page'))
    
    user.name = request.form.get('name', user.name)
    user.email = request.form.get('email', user.email)
    user.phone = request.form.get('phone', user.phone)
    user.department = request.form.get('department', user.department)
    
    if 'profile_pic' in request.files:
        file = request.files['profile_pic']
        if file and file.filename != '':
            if user.profile_pic != 'default.png':
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_pic)
                if os.path.exists(old_path):
                    try: os.remove(old_path)
                    except: pass

            filename = secure_filename(f"user_{user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            user.profile_pic = filename

    db.session.commit()
    return redirect(url_for('profile_page'))

@app.route('/export/csv')
@login_required
def export_attendance_csv():
    user_id = session.get('user_id')
    start_date = request.args.get('start')
    end_date = request.args.get('end')

    query = Attendance.query.filter_by(user_id=user_id)
    if start_date:
        query = query.filter(Attendance.date >= start_date)
    if end_date:
        query = query.filter(Attendance.date <= end_date)

    logs = query.order_by(Attendance.date.asc()).all()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Date', 'Location', 'Morning In', 'Morning Out', 'Afternoon In', 'Afternoon Out', 'Total Hours', 'Accomplishments'])
    
    for log in logs:
        cw.writerow([log.date, log.location, log.m_in, log.m_out, log.a_in, log.a_out, log.hours, log.description])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=Attendance_Log_{datetime.now().strftime('%Y%m%d')}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/export/pdf')
@login_required
def export_attendance_pdf():
    user = User.query.get(session.get('user_id'))
    start_date = request.args.get('start')
    end_date = request.args.get('end')

    query = Attendance.query.filter_by(user_id=user.id)
    if start_date:
        query = query.filter(Attendance.date >= start_date)
    if end_date:
        query = query.filter(Attendance.date <= end_date)

    logs = query.order_by(Attendance.date.asc()).all()
    
    # CALCULATE TOTAL HERE
    calculated_total = round(sum(log.hours for log in logs), 2)
    
    return render_template('report_print.html', 
                           user=user, 
                           logs=logs, 
                           start=start_date, 
                           end=end_date, 
                           # ENSURE THIS NAME MATCHES YOUR HTML
                           total_period_hours=calculated_total,
                           now=datetime.now())

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

        fmt = '%H:%M'
        try:
            tdelta1 = datetime.strptime(log_entry.m_out, fmt) - datetime.strptime(log_entry.m_in, fmt)
            tdelta2 = datetime.strptime(log_entry.a_out, fmt) - datetime.strptime(log_entry.a_in, fmt)
            total_hrs = (tdelta1.total_seconds() + tdelta2.total_seconds()) / 3600
            log_entry.hours = round(max(0, total_hrs), 2)
        except Exception as e:
            print(f"Calculation Error: {e}")
        
        db.session.commit()
    return redirect(url_for('history'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

if __name__ == '__main__':
    # Render provides a PORT environment variable. This line is mandatory for hosting.
    port = int(os.environ.get("PORT", 8081))
    app.run(host='0.0.0.0', port=port)