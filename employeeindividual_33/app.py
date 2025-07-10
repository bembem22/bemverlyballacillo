from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_mysqldb import MySQL
import MySQLdb.cursors
import re
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
import pandas as pd
from fpdf import FPDF
import os
from io import BytesIO

app = Flask(__name__)

# Configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''  # Enter your MySQL password here
app.config['MYSQL_DB'] = 'kate33'
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['UPLOAD_FOLDER'] = 'static/reports'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['REPORT_TYPES'] = {
    'daily': 'Daily Attendance Report',
    'weekly': 'Weekly Attendance Summary',
    'monthly': 'Monthly Attendance Report'
}

mysql = MySQL(app)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/')
def home():
    if 'loggedin' in session:
        if session['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

# Authentication Routes
@app.route('/login/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form:
        username = request.form['username']
        password = request.form['password']
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        account = cursor.fetchone()
        
        if account and check_password_hash(account['password'], password):
            session['loggedin'] = True
            session['id'] = account['id']
            session['username'] = account['username']
            session['role'] = account['role']
            
            # Get employee details if exists
            cursor.execute('SELECT * FROM employees WHERE user_id = %s', (account['id'],))
            employee = cursor.fetchone()
            if employee:
                session['employee_id'] = employee['employee_id']
                session['full_name'] = employee['full_name']
            
            flash('Logged in successfully!', 'success')
            
            if account['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        else:
            flash('Incorrect username/password!', 'danger')
    
    return render_template('login.html')

@app.route('/favicon.ico')
def favicon():
    return send_file(os.path.join(app.root_path, 'static', 'favicon.ico'))


@app.route('/register/', methods=['GET', 'POST'])
def register():
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form and 'email' in request.form:
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        full_name = request.form['full_name']
        employee_id = request.form['employee_id']
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        account = cursor.fetchone()
        
        if account:
            flash('Account already exists!', 'danger')
        elif not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            flash('Invalid email address!', 'danger')
        elif not re.match(r'[A-Za-z0-9]+', username):
            flash('Username must contain only characters and numbers!', 'danger')
        elif not username or not password or not email:
            flash('Please fill out the form!', 'danger')
        else:
            hashed_password = generate_password_hash(password)
            cursor.execute('INSERT INTO users (username, email, password) VALUES (%s, %s, %s)', 
                          (username, email, hashed_password))
            user_id = cursor.lastrowid
            
            # Add employee details
            cursor.execute('''
                INSERT INTO employees (user_id, employee_id, full_name)
                VALUES (%s, %s, %s)
            ''', (user_id, employee_id, full_name))
            
            mysql.connection.commit()
            flash('You have successfully registered!', 'success')
            return redirect(url_for('login'))
    
    return render_template('register.html')

# Employee Dashboard
@app.route('/dashboard/')
def dashboard():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    if session['role'] == 'admin':
        return redirect(url_for('admin_dashboard'))
    
    # Get today's attendance status
    today = date.today()
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('''
        SELECT * FROM attendance 
        WHERE employee_id = (SELECT id FROM employees WHERE user_id = %s) 
        AND date = %s
    ''', (session['id'], today))
    today_attendance = cursor.fetchone()
    
    # Get attendance history (last 7 days)
    cursor.execute('''
        SELECT * FROM attendance 
        WHERE employee_id = (SELECT id FROM employees WHERE user_id = %s)
        ORDER BY date DESC LIMIT 7
    ''', (session['id'],))
    attendance_history = cursor.fetchall()
    
    return render_template('dashboard.html', 
                         today_attendance=today_attendance,
                         attendance_history=attendance_history)

@app.route('/time_in_out/', methods=['POST'])
def time_in_out():
    if 'loggedin' not in session or session['role'] == 'admin':
        return redirect(url_for('login'))
    
    current_time = datetime.now().time()
    today = date.today()
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Check if attendance record exists for today
    cursor.execute('''
        SELECT * FROM attendance 
        WHERE employee_id = (SELECT id FROM employees WHERE user_id = %s) 
        AND date = %s
    ''', (session['id'], today))
    attendance = cursor.fetchone()
    
    if attendance:
        # Time out if already timed in
        if attendance['time_out'] is None:
            cursor.execute('''
                UPDATE attendance SET time_out = %s 
                WHERE id = %s
            ''', (current_time, attendance['id']))
            flash('Successfully timed out!', 'success')
        else:
            flash('You have already timed out for today!', 'warning')
    else:
        # Time in for the first time today
        # Check if late (after 9:00 AM)
        status = 'present'
        if current_time > datetime.strptime('09:00:00', '%H:%M:%S').time():
            status = 'late'
        
        cursor.execute('''
            INSERT INTO attendance (employee_id, date, time_in, status)
            VALUES ((SELECT id FROM employees WHERE user_id = %s), %s, %s, %s)
        ''', (session['id'], today, current_time, status))
        flash('Successfully timed in!', 'success')
    
    mysql.connection.commit()
    return redirect(url_for('dashboard'))

# Admin Routes
@app.route('/admin/dashboard/')
def admin_dashboard():
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    today = date.today()
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Get today's attendance summary
    cursor.execute('''
        SELECT 
            COUNT(*) AS total_employees,
            SUM(CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END) AS present_count,
            SUM(CASE WHEN a.status = 'late' THEN 1 ELSE 0 END) AS late_count,
            SUM(CASE WHEN a.id IS NULL THEN 1 ELSE 0 END) AS absent_count
        FROM employees e
        LEFT JOIN attendance a ON e.id = a.employee_id AND a.date = %s
    ''', (today,))
    today_summary = cursor.fetchone()
    
    # Get recent attendance records
    cursor.execute('''
        SELECT e.employee_id, e.full_name, a.date, a.time_in, a.time_out, a.status
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        ORDER BY a.date DESC, a.time_in DESC
        LIMIT 10
    ''')
    recent_attendance = cursor.fetchall()
    
    return render_template('admin_dashboard.html',
                         today_summary=today_summary,
                         recent_attendance=recent_attendance)

# Employee CRUD
@app.route('/admin/employees')
def manage_employees():
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT * FROM employees ORDER BY full_name')
    employees = cursor.fetchall()
    return render_template('manage_employees.html', employees=employees)

@app.route('/admin/employees/add', methods=['GET', 'POST'])
def add_employee():
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        employee_id = request.form['employee_id']
        full_name = request.form['full_name']
        department = request.form['department']
        position = request.form['position']
        hire_date = request.form['hire_date']
        contact_number = request.form['contact_number']
        email = request.form['email']
        address = request.form['address']
        
        cursor = mysql.connection.cursor()
        cursor.execute('''
            INSERT INTO employees 
            (employee_id, full_name, department, position, hire_date, contact_number, email, address)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (employee_id, full_name, department, position, hire_date, contact_number, email, address))
        mysql.connection.commit()
        flash('Employee added successfully!', 'success')
        return redirect(url_for('manage_employees'))
    
    return render_template('add_employee.html')

@app.route('/admin/employees/edit/<int:id>', methods=['GET', 'POST'])
def edit_employee(id):
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    if request.method == 'POST':
        employee_id = request.form['employee_id']
        full_name = request.form['full_name']
        department = request.form['department']
        position = request.form['position']
        hire_date = request.form['hire_date']
        contact_number = request.form['contact_number']
        email = request.form['email']
        address = request.form['address']
        
        cursor.execute('''
            UPDATE employees SET
            employee_id = %s,
            full_name = %s,
            department = %s,
            position = %s,
            hire_date = %s,
            contact_number = %s,
            email = %s,
            address = %s
            WHERE id = %s
        ''', (employee_id, full_name, department, position, hire_date, contact_number, email, address, id))
        mysql.connection.commit()
        flash('Employee updated successfully!', 'success')
        return redirect(url_for('manage_employees'))
    
    cursor.execute('SELECT * FROM employees WHERE id = %s', (id,))
    employee = cursor.fetchone()
    return render_template('edit_employee.html', employee=employee)

@app.route('/admin/employees/delete/<int:id>', methods=['POST'])
def delete_employee(id):
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    cursor = mysql.connection.cursor()
    cursor.execute('DELETE FROM employees WHERE id = %s', (id,))
    mysql.connection.commit()
    flash('Employee deleted successfully!', 'success')
    return redirect(url_for('manage_employees'))

# Attendance CRUD (Admin)
@app.route('/admin/attendance')
def manage_attendance():
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('''
        SELECT a.*, e.employee_id, e.full_name 
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        ORDER BY a.date DESC, a.time_in DESC
    ''')
    attendance_records = cursor.fetchall()
    
    cursor.execute('SELECT id, employee_id, full_name FROM employees ORDER BY full_name')
    employees = cursor.fetchall()
    
    return render_template('manage_attendance.html', 
                         attendance_records=attendance_records,
                         employees=employees)

@app.route('/admin/attendance/add', methods=['POST'])
def add_attendance():
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    employee_id = request.form['employee_id']
    date = request.form['date']
    time_in = request.form['time_in']
    time_out = request.form['time_out']
    status = request.form['status']
    notes = request.form['notes']
    
    cursor = mysql.connection.cursor()
    try:
        cursor.execute('''
            INSERT INTO attendance 
            (employee_id, date, time_in, time_out, status, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (employee_id, date, time_in, time_out, status, notes))
        mysql.connection.commit()
        flash('Attendance record added successfully!', 'success')
    except MySQLdb.IntegrityError:
        flash('Attendance record for this employee and date already exists!', 'danger')
    
    return redirect(url_for('manage_attendance'))

@app.route('/admin/attendance/edit/<int:id>', methods=['POST'])
def edit_attendance(id):
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    date = request.form['date']
    time_in = request.form['time_in']
    time_out = request.form['time_out']
    status = request.form['status']
    notes = request.form['notes']
    
    cursor = mysql.connection.cursor()
    cursor.execute('''
        UPDATE attendance SET
        date = %s,
        time_in = %s,
        time_out = %s,
        status = %s,
        notes = %s
        WHERE id = %s
    ''', (date, time_in, time_out, status, notes, id))
    mysql.connection.commit()
    flash('Attendance record updated successfully!', 'success')
    return redirect(url_for('manage_attendance'))

@app.route('/admin/attendance/delete/<int:id>', methods=['POST'])
def delete_attendance(id):
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    cursor = mysql.connection.cursor()
    cursor.execute('DELETE FROM attendance WHERE id = %s', (id,))
    mysql.connection.commit()
    flash('Attendance record deleted successfully!', 'success')
    return redirect(url_for('manage_attendance'))

# Reports
@app.route('/admin/reports/')
def reports():
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    return render_template('reports.html', report_types=app.config['REPORT_TYPES'])

@app.route('/admin/generate_report/', methods=['POST'])
def generate_report():
    if 'loggedin' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    report_type = request.form['report_type']
    format_type = request.form['format']
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Determine date range based on report type
    if report_type == 'daily':
        report_date = date.today()
        start_date = report_date
        end_date = report_date
    elif report_type == 'weekly':
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif report_type == 'monthly':
        today = date.today()
        start_date = date(today.year, today.month, 1)
        end_date = date(today.year, today.month + 1, 1) - timedelta(days=1)
    
    # Get attendance data
    cursor.execute('''
        SELECT e.employee_id, e.full_name, e.department, 
               a.date, a.time_in, a.time_out, a.status
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        WHERE a.date BETWEEN %s AND %s
        ORDER BY e.full_name, a.date
    ''', (start_date, end_date))
    attendance_data = cursor.fetchall()
    
    # Get summary data
    cursor.execute('''
        SELECT 
            COUNT(DISTINCT e.id) AS total_employees,
            COUNT(DISTINCT a.employee_id) AS present_employees,
            SUM(CASE WHEN a.status = 'late' THEN 1 ELSE 0 END) AS late_count,
            SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) AS absent_count,
            SUM(CASE WHEN a.status = 'half-day' THEN 1 ELSE 0 END) AS half_day_count
        FROM employees e
        LEFT JOIN attendance a ON e.id = a.employee_id AND a.date BETWEEN %s AND %s
    ''', (start_date, end_date))
    summary_data = cursor.fetchone()
    
    # Generate report based on format
    if format_type == 'excel':
        # Create DataFrame
        df = pd.DataFrame(attendance_data)
        
        # Create summary DataFrame
        summary_df = pd.DataFrame([summary_data])
        
        # Create Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Attendance Details', index=False)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
        
        output.seek(0)
        
        # Save report record
        filename = f"attendance_report_{report_type}_{date.today()}.xlsx"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(filepath, 'wb') as f:
            f.write(output.getbuffer())
        
        cursor.execute('''
            INSERT INTO reports (report_type, generated_by, file_path)
            VALUES (%s, %s, %s)
        ''', (report_type, session['id'], filepath))
        mysql.connection.commit()
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
    
    elif format_type == 'pdf':
        # Create PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        
        # Report title
        pdf.cell(200, 10, txt=app.config['REPORT_TYPES'][report_type], ln=1, align='C')
        pdf.cell(200, 10, txt=f"Date Range: {start_date} to {end_date}", ln=1, align='C')
        pdf.ln(10)
        
        # Summary section
        pdf.set_font("Arial", 'B', size=12)
        pdf.cell(200, 10, txt="Summary", ln=1)
        pdf.set_font("Arial", size=10)
        
        pdf.cell(100, 10, txt=f"Total Employees: {summary_data['total_employees']}", ln=1)
        pdf.cell(100, 10, txt=f"Present Employees: {summary_data['present_employees']}", ln=1)
        pdf.cell(100, 10, txt=f"Late Count: {summary_data['late_count']}", ln=1)
        pdf.cell(100, 10, txt=f"Absent Count: {summary_data['absent_count']}", ln=1)
        pdf.cell(100, 10, txt=f"Half-Day Count: {summary_data['half_day_count']}", ln=1)
        pdf.ln(10)
        
        # Details section
        pdf.set_font("Arial", 'B', size=12)
        pdf.cell(200, 10, txt="Attendance Details", ln=1)
        pdf.set_font("Arial", size=10)
        
        # Table header
        pdf.cell(30, 10, txt="Employee ID", border=1)
        pdf.cell(40, 10, txt="Name", border=1)
        pdf.cell(30, 10, txt="Date", border=1)
        pdf.cell(30, 10, txt="Time In", border=1)
        pdf.cell(30, 10, txt="Time Out", border=1)
        pdf.cell(30, 10, txt="Status", border=1, ln=1)
        
        # Table rows
        for row in attendance_data:
            pdf.cell(30, 10, txt=row['employee_id'], border=1)
            pdf.cell(40, 10, txt=row['full_name'], border=1)
            pdf.cell(30, 10, txt=str(row['date']), border=1)
            pdf.cell(30, 10, txt=str(row['time_in'] or ''), border=1)
            pdf.cell(30, 10, txt=str(row['time_out'] or ''), border=1)
            pdf.cell(30, 10, txt=row['status'], border=1, ln=1)
        
        # Save PDF to file
        filename = f"attendance_report_{report_type}_{date.today()}.pdf"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        pdf.output(filepath)
        
        # Save report record
        cursor.execute('''
            INSERT INTO reports (report_type, generated_by, file_path)
            VALUES (%s, %s, %s)
        ''', (report_type, session['id'], filepath))
        mysql.connection.commit()
        
        return send_file(
            filepath,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    
    flash('Report generated successfully!', 'success')
    return redirect(url_for('reports'))

@app.route('/logout/')
def logout():
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('username', None)
    session.pop('role', None)
    session.pop('employee_id', None)
    session.pop('full_name', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)