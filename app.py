from flask import Flask, json, request, jsonify, session, send_from_directory, send_file
from flask_cors import CORS
from supabase import create_client
import config
from datetime import datetime, timedelta
from dateutil import parser
from flask_mail import Mail, Message
import random
import string
import time
import requests
from dateutil import parser
import pytz
from pytz import timezone, UTC
from nltk.sentiment import SentimentIntensityAnalyzer
from langdetect import detect, LangDetectException
import nltk
from nltk.corpus import words
import re
from werkzeug.utils import secure_filename
import mimetypes
from datetime import datetime
from pytz import timezone




app = Flask(__name__)
CORS(app)
app.secret_key = config.SECRET_KEY  # Needed for session management

# Initialize Supabase client
supabase = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

def format_date(dt_str):
    if not dt_str or str(dt_str).lower() == 'none':
        return ''
    try:
        dt = parser.parse(str(dt_str))
        dt_local = dt.astimezone(timezone('Asia/Manila'))
        return dt_local.isoformat()  # ISO format, always parseable by Dart
    except Exception:
        try:
            return str(dt_str)[:10]
        except Exception:
            return ''


app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'glamourgaze33@gmail.com'
app.config['MAIL_PASSWORD'] = 'dzjd ciep jexs tilj'         

mail = Mail(app)

pending_registrations = {}
otp_store = {}

UPLOAD_FOLDER = 'uploads/profile_pics'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# --- LOGIN ROUTE ---
@app.route('/login', methods=['POST'])
def login():
    """
    User login route.
    Accepts email and password, returns user info if valid and status is Active.
    Only allows Student and Teacher roles.
    Streak logic applies only to Student.
    Logs login activity to admin_activity_log with device and IP info.
    """
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        # Accept device_type from mobile/web, fallback to user agent
        device_type = data.get('device_type')
        if not device_type:
            user_agent = (request.user_agent.string or '').lower()
            if 'mobile' in user_agent or 'android' in user_agent or 'iphone' in user_agent:
                device_type = 'mobile'
            elif 'tablet' in user_agent or 'ipad' in user_agent:
                device_type = 'tablet'
            elif 'windows' in user_agent:
                device_type = 'Windows computer'
            elif 'mac' in user_agent or 'macos' in user_agent:
                device_type = 'Mac computer'
            elif 'linux' in user_agent:
                device_type = 'Linux computer'
            else:
                device_type = 'computer'

        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400

        # Query the user_info table
        response = safe_execute(supabase.table('user_info')
            .select('*')
            .eq('email', email)
            .eq('password', password))

        if not response.data or len(response.data) == 0:
            return jsonify({'error': 'Invalid email or password'}), 401

        user = response.data[0]
        status = user.get('status', 'Pending')
        role = user.get('role', '')
        if status.lower() != 'active':
            return jsonify({
                'error': f'Your account status is "{status}". Please wait for approval or contact your administrator.',
                'status': status
            }), 403

        # Only allow Student and Teacher roles
        if role not in ['Student', 'Teacher']:
            return jsonify({
                'error': f'Login is only allowed for Student and Teacher accounts.',
                'status': 'Denied'
            }), 403

        session['user_id'] = user['id']

        # --- Device and IP detection ---
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)

        # --- STREAK LOGIC (Student only) ---
        streak = None
        if role == 'Student':
            today = datetime.now().date()
            last_login_str = user.get('last_login_date')
            streak = user.get('streak', 0) or 0

            if last_login_str:
                try:
                    last_login_date = datetime.strptime(last_login_str, '%Y-%m-%d').date()
                except Exception:
                    last_login_date = None
            else:
                last_login_date = None

            if last_login_date == today:
                pass
            elif last_login_date == today - timedelta(days=1):
                streak += 1
            else:
                if streak > 0:
                    safe_execute(supabase.table('notifications').insert({
                        'user_id': user['id'],
                        'sender_id': user['id'],
                        'title': 'Streak Lost',
                        'message': 'You missed a day and lost your login streak. Start again!',
                        'notif_type': 'Streak',
                        'status': 'Unread',
                    }))
                streak = 0

            # Update last_login_date and streak in DB
            safe_execute(supabase.table('user_info').update({
                'last_login_date': today.isoformat(),
                'streak': streak
            }).eq('id', user['id']))

            # --- STREAK MILESTONE NOTIFICATION ---
            milestones = [7, 15, 22, 29, 36, 43, 50]
            if streak in milestones:
                notif_exists = safe_execute(
                    supabase.table('notifications')
                    .select('notif_id')
                    .eq('sender_id', user['id'])
                    .eq('notif_type', 'Streak')
                    .eq('title', 'Streak Milestone!')
                    .eq('message', f'Congratulations! You reached a {streak}-day login streak!')
                )
                if not notif_exists.data or len(notif_exists.data) == 0:
                    safe_execute(supabase.table('notifications').insert({
                        'sender_id': user['id'],
                        'title': 'Streak Milestone!',
                        'message': f'Congratulations! You reached a {streak}-day login streak!',
                        'notif_type': 'Streak',
                        'status': 'Unread',
                    }))

        # --- Log to admin_activity_log ---
        user_role = user.get('role', 'Student')
        user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        if role == 'Student':
            description = f"Student {user.get('last_name', '')} logged in from {device_type}"
            details = f"Email: {user.get('email', '')}\nIP Address: {ip_address.split(',')[0].strip()}\nStreak: {streak}"
        else:  # Teacher
            description = f"Teacher {user.get('last_name', '')} logged in from {device_type}"
            details = f"Email: {user.get('email', '')}\nIP Address: {ip_address.split(',')[0].strip()}"

        safe_execute(supabase.table('admin_activity_log').insert({
            'user_id': user['id'],
            'user_role': user_role,
            'action': 'Login',
            'activity': 'Authentication',
            'description': description,
            'details': details,
        }))

        # Prepare response
        resp_data = {
            'id': user['id'],
            'email': user['email'],
            'role': role,
        }
        if role == 'Student':
            resp_data['streak'] = streak
            resp_data['section'] = user.get('section', '')
        print(f'LOGIN RESPONSE: {resp_data}')
        return jsonify({
            'message': 'Login successful',
            'user': resp_data
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500




# --- FORGOT PASSWORD ROUTE ---
@app.route('/forgot_password', methods=['POST'])
def forgot_password():
    data = request.get_json()
    email = data.get('email')
    if not email:
        return jsonify({'error': 'Email is required'}), 400

    # Check if email exists
    user_resp = safe_execute(supabase.table('user_info').select('id', 'first_name').eq('email', email))
    if not user_resp.data or len(user_resp.data) == 0:
        return jsonify({'error': 'Email not found'}), 404

    # Generate OTP
    otp = random.randint(100000, 999999)
    otp_store[email] = otp  # Store OTP in global dict

    # Send OTP email
    send_otp_email(email, otp, for_reset=True)

    return jsonify({'message': 'OTP sent to email'}), 200


# --- FORGOT PASS VERIFY MUNA NG OTP ROUTE ---
@app.route('/verify_forgot_otp', methods=['POST'])
def verify_forgot_otp():
    data = request.get_json()
    email = data.get('email')
    otp = data.get('otp')

    print('OTP_STORE email:', email)
    print('OTP_STORE otp:', otp_store.get(email))
    print('Request email:', email)
    print('Request otp:', otp)

    if not email or not otp:
        return jsonify({'success': False, 'error': 'Missing email or OTP'}), 400

    # Check OTP from global dict
    if email in otp_store and str(otp_store[email]) == str(otp):
        return jsonify({'success': True}), 200
    else:
        return jsonify({'success': False, 'error': 'Invalid OTP'}), 400


# --- RESET PASSWORD & ENTER NEW PASS ROUTE ---
@app.route('/reset_password', methods=['POST'])
def reset_password():
    data = request.get_json()
    email = data.get('email')
    otp = data.get('otp')
    new_password = data.get('new_password')

    if not email or not otp or not new_password:
        return jsonify({'error': 'Missing fields'}), 400

    # Check OTP from global dict
    if email not in otp_store or str(otp_store[email]) != str(otp):
        return jsonify({'error': 'Invalid OTP'}), 400

    # Update password
    safe_execute(supabase.table('user_info').update({'password': new_password}).eq('email', email))

    # Log to admin_activity_log
    user_resp = safe_execute(supabase.table('user_info').select('id', 'role', 'first_name', 'last_name', 'section').eq('email', email))
    if user_resp.data and len(user_resp.data) > 0:
        user = user_resp.data[0]
        user_id = user.get('id')
        user_role = user.get('role', 'Student')
        user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        section = user.get('section', '')
        safe_execute(supabase.table('admin_activity_log').insert({
            'user_id': user_id,
            'user_role': user_role,
            'action': 'Reset Password',
            'activity': 'Password Reset',
            'description': f"{user_name} reset their password.",
            'details': f"Email: {email}, Section: {section}, Role: {user_role}",
        }))

    # Clear OTP
    otp_store.pop(email, None)

    return jsonify({'success': True, 'message': 'Password reset successful'}), 200



# --- Helper: Send OTP Email ---
def send_otp_email(recipient, otp, for_reset=False):
    if for_reset:
        msg = Message("Learn2Earn Password Reset", sender="Learn2Earn", recipients=[recipient])
        msg.body = f"""Dear Student,

We received a request to reset your Learn2Earn account password.

Your password reset code is: {otp}

Please enter this code in the app to set a new password.

If you did not request a password reset, please ignore this email.

Best regards,
Learn2Earn Team
"""
    else:
        msg = Message("Learn2Earn Account Verification", sender="Learn2Earn", recipients=[recipient])
        msg.body = f"""Dear Student,

Thank you for registering with Learn2Earn.

Your verification code is: {otp}

Please enter this code to complete your registration.

Best regards,
Learn2Earn Team
"""
    try:
        mail.send(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")




# --- Registration Route (Step 1: Send OTP, Don't Insert Yet) ---
@app.route('/register', methods=['POST'])
def register():
    """
    Step 1: Accept registration data, send OTP, do NOT insert yet.
    """
    try:
        data = request.get_json()
        required_fields = [
            'first_name', 'last_name', 'email', 'password', 'mobile_no',
            'year_level', 'section'
        ]
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400

        # Check if email already exists
        existing = safe_execute(supabase.table('user_info').select('id').eq('email', data['email']))
        if existing.data and len(existing.data) > 0:
            return jsonify({'error': 'Email already registered'}), 409

        # --- CHECK IF MOBILE NUMBER ALREADY EXISTS ---
        mobile_existing = safe_execute(supabase.table('user_info').select('id').eq('mobile_no', data['mobile_no']))
        if mobile_existing.data and len(mobile_existing.data) > 0:
            return jsonify({'error': 'Mobile number already registered'}), 409

        # Generate OTP and token
        otp = random.randint(100000, 999999)
        otp_token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))

        # Save registration data and OTP in memory
        pending_registrations[otp_token] = {
            'otp': otp,
            'registration_data': data
        }

        # Send OTP email
        send_otp_email(data['email'], otp)

        return jsonify({'message': 'OTP sent to email', 'otp_token': otp_token}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/check_mobile', methods=['POST'])
def check_mobile():
    data = request.get_json()
    mobile_no = data.get('mobile_no')
    if not mobile_no:
        return jsonify({'exists': False, 'error': 'Missing mobile_no'}), 400
    resp = safe_execute(supabase.table('user_info').select('id').eq('mobile_no', mobile_no))
    exists = bool(resp.data and len(resp.data) > 0)
    return jsonify({'exists': exists}), 200

# --- Verify OTP and Complete Registration Route ---
@app.route('/api/verify_otp', methods=['POST'])
def verify_otp():
    data = request.get_json()
    otp_token = data.get('otp_token')
    input_otp = data.get('otp')

    if not otp_token or otp_token not in pending_registrations:
        return jsonify({'status': 'error', 'message': 'Invalid or expired OTP token'}), 400

    pending = pending_registrations[otp_token]
    saved_otp = pending['otp']
    registration_data = pending['registration_data']

    if str(input_otp) == str(saved_otp):
        # Prepare insert data
        insert_data = {
            'first_name': registration_data['first_name'],
            'middle_name': registration_data.get('middle_name', ''),
            'last_name': registration_data['last_name'],
            'email': registration_data['email'],
            'password': registration_data['password'],
            'gender': registration_data.get('gender', ''),
            'mobile_no': registration_data['mobile_no'],
            'role': 'Student',
            'year_level': registration_data['year_level'],
            'section': registration_data['section'],
            'status': 'Pending'
        }
        resp = safe_execute(supabase.table('user_info').insert(insert_data))
        del pending_registrations[otp_token]
        if resp.data and len(resp.data) > 0:
            # Log registration to admin_activity_log
            user_id = resp.data[0].get('id')
            full_name = f"{insert_data['first_name']} {insert_data['last_name']}"
            safe_execute(supabase.table('admin_activity_log').insert({
                'user_id': user_id,
                'user_role': 'Student',
                'action': 'Register Account',
                'activity': 'Student Registration',
                'description': f"{full_name} registered an account.",
                'details': f"Email: {insert_data['email']}, Section: {insert_data['section']}, Year Level: {insert_data['year_level']}"
            }))
            return jsonify({'status': 'success', 'message': 'OTP verified! Registration complete.'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Registration failed after OTP.'}), 500
    else:
        return jsonify({'status': 'error', 'message': 'Invalid OTP'}), 400



# --- NLP NOTIFICATIONS DISLAY ROUTE ---
@app.route('/student_nlp_notifications', methods=['GET'])
def students_nlp_notifications():
    student_id = request.args.get('user_id')
    if not student_id:
        print("[DEBUG] No student_id provided")
        return jsonify({'success': False, 'notifications': []})
    try:
        result = supabase.table('nlp_notifications') \
            .select('*') \
            .eq('student_id', student_id) \
            .eq('status', 'Unread') \
            .order('created_at', desc=True) \
            .limit(5) \
            .execute()
        notifications = result.data if result.data else []
        print(f"[DEBUG] NLP notifications for student_id={student_id}: {notifications}")
        return jsonify({'success': True, 'notifications': notifications})
    except Exception as e:
        print(f"[DEBUG] Error fetching NLP notifications: {e}")
        return jsonify({'success': False, 'notifications': []})

# --- MARK NLP NOTIFICATION AS READ ROUTE ---
@app.route('/mark_student_nlp_notifications/<int:notif_id>/read', methods=['POST'])
def mark_student_nlp_notification_read(notif_id):
    try:
        safe_execute(
            supabase.table('nlp_notifications')
            .update({'status': 'Read'})
            .eq('id', notif_id)
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500




# --- DASHBOARD USER INFO ROUTE ---
@app.route('/dashboard', methods=['GET'])
def get_current_user_info():
    from dateutil import parser
    from pytz import timezone
    user_id = request.args.get('user_id') or session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not logged in'}), 401

    # Get user info
    user_resp = safe_execute(
        supabase.table('user_info').select(
            'id, first_name, last_name, total_points, section, year_level, streak'
        ).eq('id', user_id)
    )
    if not user_resp.data or len(user_resp.data) == 0:
        return jsonify({'error': 'User not found'}), 404

    user = user_resp.data[0]
    section = user.get('section')

    # Get all students in the same section, sorted by total_points desc
    classmates = safe_execute(
        supabase.table('user_info').select(
            'id, total_points'
        ).eq('section', section).eq('role', 'Student').eq('status', 'Active')
    )
    classmates_list = classmates.data if classmates.data else []
    classmates_list.sort(key=lambda x: x.get('total_points', 0), reverse=True)
    # Find rank
    rank = next((i+1 for i, s in enumerate(classmates_list) if s['id'] == user['id']), None)

    # Get latest profile picture from profile_pictures table
    pic_resp = safe_execute(
        supabase.table('profile_pictures').select('file_path').eq('user_id', user_id).order('uploaded_at', desc=True).limit(1)
    )
    profile_picture = None
    if pic_resp.data and len(pic_resp.data) > 0:
        profile_picture = pic_resp.data[0].get('file_path')
    else:
        profile_picture = ''

    # --- Weekly points logic (Asia/Manila timezone) ---
    from datetime import datetime, timedelta
    tz = timezone('Asia/Manila')
    utc_tz = timezone('UTC')
    now = datetime.now(tz)
    start_of_week = now - timedelta(days=now.weekday())
    days = [(start_of_week + timedelta(days=i)).date() for i in range(7)]
    points_per_day = [0] * 7

    # Points from 'points' table (approved, per day)
    points_resp = safe_execute(
        supabase.table('points')
        .select('points, received_at')
        .eq('student_id', user_id)
        .eq('status', 'approved')
    )
    
    if points_resp.data:
        for p in points_resp.data:
            raw_dt = p['received_at']
            try:
                # Parse as UTC first, then convert to Manila time
                dt_utc = parser.parse(raw_dt).replace(tzinfo=utc_tz)
                dt_manila = dt_utc.astimezone(tz)
                date_obj = dt_manila.date()
                
                # Check if this date falls within current week
                if days[0] <= date_obj <= days[-1]:
                    idx = (date_obj - start_of_week.date()).days
                    if 0 <= idx < 7:
                        points_per_day[idx] += p['points']
            except Exception:
                continue

    # Add milestone_claims points_awarded per day
    milestone_resp = safe_execute(
        supabase.table('milestone_claims')
        .select('points_awarded', 'claimed_at')
        .eq('student_id', user_id)
    )
    
    if milestone_resp.data:
        for m in milestone_resp.data:
            raw_dt = m.get('claimed_at', '')
            try:
                # Parse as UTC first, then convert to Manila time
                dt_utc = parser.parse(raw_dt).replace(tzinfo=utc_tz)
                dt_manila = dt_utc.astimezone(tz)
                date_obj = dt_manila.date()
                
                # Check if this date falls within current week
                if days[0] <= date_obj <= days[-1]:
                    idx = (date_obj - start_of_week.date()).days
                    if 0 <= idx < 7:
                        points_per_day[idx] += m.get('points_awarded', 0)
            except Exception:
                continue

    # --- Compute points earned today (from points and milestone_claims) ---
    today_str = now.date().isoformat()
    
    # Points from 'points' table for today
    points_today_resp = safe_execute(
        supabase.table('points')
        .select('points, received_at')
        .eq('student_id', user_id)
        .eq('status', 'approved')
    )
    
    points_today = 0
    if points_today_resp.data:
        for p in points_today_resp.data:
            try:
                # Parse as UTC first, then convert to Manila time
                dt_utc = parser.parse(p.get('received_at', '')).replace(tzinfo=utc_tz)
                dt_manila = dt_utc.astimezone(tz)
                point_date = dt_manila.date().isoformat()
                
                if point_date == today_str:
                    points_today += p['points']
            except Exception:
                continue

    # Points from milestone_claims for today
    milestone_today_resp = safe_execute(
        supabase.table('milestone_claims')
        .select('points_awarded, claimed_at')
        .eq('student_id', user_id)
    )
    
    milestone_points_today = 0
    if milestone_today_resp.data:
        for m in milestone_today_resp.data:
            try:
                # Parse as UTC first, then convert to Manila time
                dt_utc = parser.parse(m.get('claimed_at', '')).replace(tzinfo=utc_tz)
                dt_manila = dt_utc.astimezone(tz)
                milestone_date = dt_manila.date().isoformat()
                
                if milestone_date == today_str:
                    milestone_points_today += m['points_awarded']
            except Exception:
                continue

    total_points_today = points_today + milestone_points_today
    
    # --- Recent activities (tasks, rewards, milestones, etc.) ---
    recent_activities = []

    # --- Recent completed/denied tasks ---
    tasks_resp = safe_execute(
        supabase.table('task_assignments').select(
            'task, points, status, completed_at, due_date'
        ).eq('student_id', user_id)
        .in_('status', ['Completed', 'Denied'])
        .order('completed_at', desc=True)
        # REMOVED: .limit(5)
    )
    if tasks_resp.data:
        for t in tasks_resp.data:
            # Convert task dates to Manila time for display
            activity_time = ''
            raw_time = t.get('completed_at', t.get('due_date', ''))
            if raw_time:
                try:
                    dt_utc = parser.parse(raw_time).replace(tzinfo=utc_tz)
                    dt_manila = dt_utc.astimezone(tz)
                    activity_time = format_date(dt_manila.isoformat())
                except:
                    activity_time = format_date(raw_time)
            
            recent_activities.append({
                'type': 'task',
                'title': t['task'],
                'points': t['points'],
                'status': t['status'],
                'time': activity_time,
            })

    # --- Recent reward redemptions ---
    try:
        rewards_resp = safe_execute(
            supabase.table('reward_redemptions').select(
                'reward_id, points_deducted, processed_at, rewards(reward_name)'
            ).eq('student_id', user_id).order('processed_at', desc=True)
            # REMOVED: .limit(5)
        )
    except Exception:
        rewards_resp = type('obj', (object,), {'data': []})()
    if rewards_resp.data:
        for r in rewards_resp.data:
            reward_name = ''
            if r.get('rewards') and r['rewards'].get('reward_name'):
                reward_name = r['rewards']['reward_name']
            
            # Convert reward dates to Manila time for display
            activity_time = ''
            raw_time = r.get('processed_at', '')
            if raw_time:
                try:
                    dt = parser.parse(raw_time)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=utc_tz)
                    dt_manila = dt.astimezone(tz)
                    activity_time = format_date(dt_manila.isoformat())
                except:
                    activity_time = format_date(raw_time)
            
            recent_activities.append({
                'type': 'reward',
                'title': f"Redeemed: {reward_name}",
                'points': -abs(r['points_deducted']),
                'status': 'Redeemed',
                'time': activity_time,
            })

    # --- Recent teacher awards (e.g., points) ---
    stars_resp = safe_execute(
        supabase.table('points').select(
            'points, received_at, note, point_category'
        ).eq('student_id', user_id).eq('status', 'approved').order('received_at', desc=True)
        # REMOVED: .limit(5)
    )
    if stars_resp.data:
        for s in stars_resp.data:
            # Convert points dates to Manila time for display
            activity_time = ''
            raw_time = s.get('received_at', '')
            if raw_time:
                try:
                    dt_utc = parser.parse(raw_time).replace(tzinfo=utc_tz)
                    dt_manila = dt_utc.astimezone(tz)
                    activity_time = format_date(dt_manila.isoformat())
                except:
                    activity_time = format_date(raw_time)
            
            recent_activities.append({
                'type': 'star',
                'title': s.get('note', 'Teacher Award'),
                'category': s.get('point_category', ''),
                'points': s['points'],
                'status': 'Awarded',
                'time': activity_time,
            })

    # --- Recent milestone claims ---
    milestone_claims_resp = safe_execute(
        supabase.table('milestone_claims')
        .select('milestone_type, milestone, points_awarded, claimed_at')
        .eq('student_id', user_id)
        .order('claimed_at', desc=True)
        # REMOVED: .limit(5)
    )
    if milestone_claims_resp.data:
        for m in milestone_claims_resp.data:
            # Convert milestone dates to Manila time for display
            activity_time = ''
            raw_time = m.get('claimed_at', '')
            if raw_time:
                try:
                    dt_utc = parser.parse(raw_time).replace(tzinfo=utc_tz)
                    dt_manila = dt_utc.astimezone(tz)
                    activity_time = format_date(dt_manila.isoformat())
                except:
                    activity_time = format_date(raw_time)
            
            recent_activities.append({
                'type': 'milestone',
                'title': f"Claimed {m['milestone_type'].capitalize()} Milestone: {m['milestone']}",
                'points': m.get('points_awarded', 0),
                'status': 'Claimed',
                'time': activity_time,
                'is_me': True,
            })     

    # --- Streak milestones (e.g., every 7, 30, 50 days) ---
    streak_milestone_notifs = safe_execute(
        supabase.table('notifications')
        .select('title, message, created_at')
        .eq('user_id', user_id)
        .eq('title', 'Streak Milestone Unlocked!')
        .order('created_at', desc=True)
    )

    if streak_milestone_notifs.data:
        for notif in streak_milestone_notifs.data:
            import re
            milestone_match = re.search(r'the (\d+) streak milestone', notif.get('message', ''))
            milestone_num = milestone_match.group(1) if milestone_match else '?'
            
            # Convert notification dates to Manila time for display
            activity_time = ''
            raw_time = notif.get('created_at', '')
            if raw_time:
                try:
                    dt_utc = parser.parse(raw_time).replace(tzinfo=utc_tz)
                    dt_manila = dt_utc.astimezone(tz)
                    activity_time = format_date(dt_manila.isoformat())
                except:
                    activity_time = format_date(raw_time)
            
            recent_activities.append({
                'type': 'streak',
                'title': f"Streak Milestone: {milestone_num} days!",
                'points': 0,
                'status': 'Milestone',
                'time': activity_time,
            })
        
    # Sort by time, most recent first
    final_activities = sorted(
        [a for a in recent_activities if a.get('time')],
        key=lambda x: x.get('time') or '',
        reverse=True
    )

    return jsonify({
        'id': user['id'],
        'name': f"{user.get('first_name', '')} {user.get('last_name', '')}",
        'total_points': user.get('total_points', 0),
        'streak': user.get('streak', 0),
        'rank': rank,
        'profile_picture': profile_picture,
        'weekly_points': points_per_day,
        'recent_activities': final_activities,
        'points_today': total_points_today,
    }), 200




# --- ACHIEVEMENTS PAGE ROUTE ---
@app.route('/achievements', methods=['GET'])
def get_achievements():
    from datetime import datetime, timedelta

    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    # Get streak and points (all-time)
    user_resp = safe_execute(supabase.table('user_info').select('streak, total_points').eq('id', user_id))
    user = user_resp.data[0] if user_resp.data else {}

    # --- ALL-TIME COMPLETED TASKS ---
    all_tasks_resp = safe_execute(
        supabase.table('task_assignments')
        .select('task_id')
        .eq('student_id', user_id)
        .eq('status', 'Completed')
    )
    all_completed_tasks = len(all_tasks_resp.data) if all_tasks_resp.data else 0

    # --- ALL-TIME REWARDS REDEEMED ---
    all_rewards_resp = safe_execute(
        supabase.table('reward_redemptions')
        .select('redemption_id')
        .eq('student_id', user_id)
    )
    all_redeemed_rewards = len(all_rewards_resp.data) if all_rewards_resp.data else 0

    # --- WEEKLY RANGE ---
    now = datetime.now()
    start_of_week = now - timedelta(days=now.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    start_str = start_of_week.date().isoformat()
    end_str = end_of_week.date().isoformat()

    # --- WEEKLY COMPLETED TASKS ---
    weekly_tasks_resp = safe_execute(
        supabase.table('task_assignments')
        .select('task_id, completed_at')
        .eq('student_id', user_id)
        .eq('status', 'Completed')
        .gte('completed_at', start_str)
        .lte('completed_at', end_str)
    )
    weekly_completed_tasks = len(weekly_tasks_resp.data) if weekly_tasks_resp.data else 0

    # --- WEEKLY REWARDS REDEEMED ---
    weekly_rewards_resp = safe_execute(
        supabase.table('reward_redemptions')
        .select('redemption_id, processed_at')
        .eq('student_id', user_id)
        .gte('processed_at', start_str)
        .lte('processed_at', end_str)
    )
    weekly_redeemed_rewards = len(weekly_rewards_resp.data) if weekly_rewards_resp.data else 0

    # --- CLAIMED MILESTONES ---
    claimed_resp = safe_execute(
        supabase.table('milestone_claims')
        .select('milestone_type, milestone')
        .eq('student_id', user_id)
    )
    claimed_set = set()
    if claimed_resp.data:
        for c in claimed_resp.data:
            claimed_set.add((c['milestone_type'], c['milestone']))

    all_achievements = []

    # Helper for notification insert
    def insert_milestone_unlocked_notif(milestone_type, milestone):
        notif_exists = safe_execute(
            supabase.table('notifications')
            .select('notif_id')
            .eq('user_id', user_id)
            .eq('title', f'{milestone_type.capitalize()} Milestone Unlocked!')
            .eq('message', f'You unlocked the {milestone} {milestone_type} milestone! Claim your bonus points.')
        )
        if not notif_exists.data or len(notif_exists.data) == 0:
            safe_execute(supabase.table('notifications').insert({
                'user_id': user_id,
                'sender_id': user_id,
                'title': f'{milestone_type.capitalize()} Milestone Unlocked!',
                'message': f'You unlocked the {milestone} {milestone_type} milestone! Claim your bonus points.',
                'notif_type': milestone_type.capitalize(),
                'status': 'Unread',
            }))

    # Streak milestones (all-time)
    for milestone in [7, 15, 22, 29, 36, 43, 50]:
        is_unlocked = user.get('streak', 0) >= milestone
        is_claimed = ('streak', milestone) in claimed_set
        if is_unlocked and not is_claimed:
            insert_milestone_unlocked_notif('streak', milestone)
        all_achievements.append({
            'type': 'streak',
            'title': f'{milestone}-Day Streak',
            'emoji': '🔥',
            'description': f'Reach a {milestone}-day streak!',
            'progress': user.get('streak', 0),
            'total': milestone,
            'isUnlocked': is_unlocked,
            'isClaimed': is_claimed,
            'unlocked_at': None
        })

    # Points milestones (all-time)
    for milestone in [100, 200, 300, 500]:
        is_unlocked = user.get('total_points', 0) >= milestone
        is_claimed = ('points', milestone) in claimed_set
        if is_unlocked and not is_claimed:
            insert_milestone_unlocked_notif('points', milestone)
        all_achievements.append({
            'type': 'points',
            'title': f'{milestone} Points',
            'emoji': '🏆',
            'description': f'Earn {milestone} points!',
            'progress': user.get('total_points', 0),
            'total': milestone,
            'isUnlocked': is_unlocked,
            'isClaimed': is_claimed,
            'unlocked_at': None
        })

    # Task milestones (all-time)
    for milestone in [10, 25, 50, 100]:
        is_unlocked = all_completed_tasks >= milestone
        is_claimed = ('task', milestone) in claimed_set
        # Debug print for task milestone
        print(f"[DEBUG] Task milestone {milestone}: completed={all_completed_tasks}, is_unlocked={is_unlocked}, is_claimed={is_claimed}")
        if is_unlocked and not is_claimed:
            insert_milestone_unlocked_notif('task', milestone)
        all_achievements.append({
            'type': 'task',
            'title': f'Completed {milestone} Activities',
            'emoji': '✅',
            'description': f'Complete {milestone} activities (all-time)!',
            'progress': all_completed_tasks,
            'total': milestone,
            'isUnlocked': is_unlocked,
            'isClaimed': is_claimed,
            'unlocked_at': None
        })

    # Reward milestones (all-time)
    for milestone in [1, 5, 10]:
        is_unlocked = all_redeemed_rewards >= milestone
        is_claimed = ('reward', milestone) in claimed_set
        if is_unlocked and not is_claimed:
            insert_milestone_unlocked_notif('reward', milestone)
        all_achievements.append({
            'type': 'reward',
            'title': f'Redeemed {milestone} Reward{"s" if milestone > 1 else ""}',
            'emoji': '🎁',
            'description': f'Redeem {milestone} reward{"s" if milestone > 1 else ""} (all-time)!',
            'progress': all_redeemed_rewards,
            'total': milestone,
            'isUnlocked': is_unlocked,
            'isClaimed': is_claimed,
            'unlocked_at': None
        })

    # Weekly milestone: 1 task
    is_unlocked = weekly_completed_tasks >= 1
    is_claimed = False  # or check if you want to track weekly claims
    if is_unlocked and not is_claimed:
        insert_milestone_unlocked_notif('task', 1)
    all_achievements.append({
        'type': 'task',
        'title': 'Completed 1 Activity (This Week)',
        'emoji': '📅',
        'description': 'Complete at least 1 activity this week!',
        'progress': weekly_completed_tasks,
        'total': 1,
        'isUnlocked': is_unlocked,
        'isClaimed': False,
        'unlocked_at': None
    })

    # Weekly milestone: 1 reward
    is_unlocked = weekly_redeemed_rewards >= 1
    is_claimed = False  # or check if you want to track weekly claims
    if is_unlocked and not is_claimed:
        insert_milestone_unlocked_notif('reward', 1)
    all_achievements.append({
        'type': 'reward',
        'title': 'Redeemed 1 Reward (This Week)',
        'emoji': '🗓️',
        'description': 'Redeem at least 1 reward this week!',
        'progress': weekly_redeemed_rewards,
        'total': 1,
        'isUnlocked': is_unlocked,
        'isClaimed': False,
        'unlocked_at': None
    })

    return jsonify({'success': True, 'achievements': all_achievements}), 200


# --- CLAIM MILESTONE ROUTE ---
@app.route('/claim_milestone', methods=['POST'])
def claim_milestone():
    data = request.get_json()
    user_id = data.get('user_id')
    milestone_type = data.get('milestone_type')
    milestone = int(data.get('milestone'))

    if not user_id or not milestone_type or not milestone:
        return jsonify({'success': False, 'error': 'Missing fields'}), 400

    claim_table = "milestone_claims"

    # Check if already claimed
    claim_resp = safe_execute(
        supabase.table(claim_table)
        .select('id')
        .eq('student_id', user_id)
        .eq('milestone_type', milestone_type)
        .eq('milestone', milestone)
    )
    if claim_resp.data and len(claim_resp.data) > 0:
        return jsonify({'success': False, 'error': 'Already claimed'}), 400

    # Get user progress
    user_resp = safe_execute(
        supabase.table('user_info').select('streak', 'total_points').eq('id', user_id)
    )
    if not user_resp.data or len(user_resp.data) == 0:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    user = user_resp.data[0]

    # Check if milestone reached
    progress = 0
    if milestone_type == 'streak':
        progress = user.get('streak', 0)
    elif milestone_type == 'points':
        progress = user.get('total_points', 0)
    elif milestone_type == 'reward':
        reward_resp = safe_execute(
            supabase.table('reward_redemptions').select('redemption_id').eq('student_id', user_id)
        )
        progress = len(reward_resp.data) if reward_resp.data else 0
    elif milestone_type == 'task':
        task_resp = safe_execute(
            supabase.table('task_assignments').select('task_id').eq('student_id', user_id).eq('status', 'Completed')
        )
        progress = len(task_resp.data) if task_resp.data else 0

    if progress < milestone:
        return jsonify({'success': False, 'error': 'Milestone not yet reached'}), 400

    # Award points (customize per milestone type)
    milestone_points = {
        'streak': {7: 10, 15: 20, 22: 30, 29: 40, 36: 50, 43: 60, 50: 100},
        'points': {100: 10, 200: 20, 300: 30, 500: 50},
        'reward': {1: 10, 5: 20, 10: 30},
        'task': {10: 10, 25: 20, 50: 30, 100: 50},
    }
    points_awarded = milestone_points.get(milestone_type, {}).get(milestone, 10)

    # Insert claim record (unified table)
    safe_execute(supabase.table(claim_table).insert({
        'student_id': user_id,
        'milestone_type': milestone_type,
        'milestone': milestone,
        'points_awarded': points_awarded,
        'claimed_at': datetime.now().isoformat()
    }))

    new_total_points = user.get('total_points', 0) + points_awarded
    safe_execute(
        supabase.table('user_info')
        .update({'total_points': new_total_points})
        .eq('id', user_id)
    )

    # Get student's section and grade_level
    student_resp = safe_execute(
        supabase.table('user_info')
        .select('section', 'year_level')
        .eq('id', user_id)
    )
    if not student_resp.data or len(student_resp.data) == 0:
        return jsonify({'success': False, 'error': 'Student not found'}), 404

    student = student_resp.data[0]
    section = student.get('section')
    grade_level = student.get('year_level')

    # Find all teachers assigned to this section and grade_level
    teachers_resp = safe_execute(
        supabase.table('teacher_class_assignments')
        .select('teacher_id')
        .eq('section', section)
        .eq('grade_level', grade_level)
    )
    teacher_ids = [t['teacher_id'] for t in teachers_resp.data] if teachers_resp.data else []

    notif_title = f'{milestone_type.capitalize()} Milestone Claimed!'
    notif_message = f'Student {user_id} claimed {points_awarded} points for reaching a {milestone} {milestone_type} milestone!'

    for teacher_id in teacher_ids:
        safe_execute(supabase.table('notifications').insert({
            'user_id': teacher_id,
            'sender_id': user_id,
            'title': notif_title,
            'message': notif_message,
            'notif_type': milestone_type.capitalize(),
            'status': 'Unread',
        }))

    # 2. Log to admin_activity_log
    safe_execute(supabase.table('admin_activity_log').insert({
        'user_id': int(user_id),
        'user_role': 'Student',
        'action': 'Claim Milestone',
        'activity': 'Milestone Claimed',
        'description': f"Claimed {milestone_type} milestone: {milestone}",
        'details': f"Points awarded: {points_awarded}",
    }))

    return jsonify({'success': True, 'points_awarded': points_awarded}), 200



# --- GET TASKS ROUTE ---
@app.route('/tasks', methods=['GET'])
def get_tasks():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    # Fetch user's all-time points
    user_resp = safe_execute(
        supabase.table('user_info').select('total_points').eq('id', user_id)
    )
    if not user_resp.data or len(user_resp.data) == 0:
        return jsonify({'error': 'User not found'}), 404

    all_time_points = user_resp.data[0].get('total_points', 0)

    # Fetch tasks for this student
    tasks_resp = safe_execute(
        supabase.table('task_assignments')
        .select('*')
        .eq('student_id', user_id)  # <-- FIXED: use student_id
    )
    tasks = tasks_resp.data if tasks_resp and hasattr(tasks_resp, 'data') else []

    # After fetching tasks
    teacher_ids = list({t.get('teacher_id') for t in tasks if t.get('teacher_id')})
    teacher_map = {}
    if teacher_ids:
        teacher_resp = safe_execute(
            supabase.table('user_info')
            .select('id, first_name, last_name, subject')
            .in_('id', teacher_ids)
        )
        for t in teacher_resp.data:
            teacher_map[t['id']] = {
                'name': f"{t.get('first_name', '')} {t.get('last_name', '')}".strip(),
                'subject': t.get('subject', '')
            }
        # Get profile pictures
        pic_resp = safe_execute(
            supabase.table('profile_pictures')
            .select('user_id, file_path')
            .in_('user_id', teacher_ids)
        )
        for p in pic_resp.data:
            if p['user_id'] in teacher_map:
                teacher_map[p['user_id']]['profile_picture'] = p['file_path']

    # Attach teacher info to each task
    for t in tasks:
        tid = t.get('teacher_id')
        if tid and tid in teacher_map:
            t['teacher_name'] = teacher_map[tid]['name']
            t['teacher_subject'] = teacher_map[tid].get('subject', '')
            t['teacher_profile_picture'] = teacher_map[tid].get('profile_picture', '')

    # Fetch awarded points for this student
    points_resp = safe_execute(
        supabase.table('points')
        .select('*')
        .eq('student_id', user_id)
        .order('received_at', desc=True)  # <-- Add this
    )
    awarded_points = points_resp.data if points_resp and hasattr(points_resp, 'data') else []

    # After collecting teacher_ids from awarded_points
    teacher_ids = list({p.get('teacher_id') for p in awarded_points if p.get('teacher_id')})
    teacher_map = {}
    if teacher_ids:
        # Get teacher names and subject
        teacher_resp = safe_execute(
            supabase.table('user_info')
            .select('id, first_name, last_name, subject')
            .in_('id', teacher_ids)
        )
        for t in teacher_resp.data:
            teacher_map[t['id']] = {
                'name': f"{t.get('first_name', '')} {t.get('last_name', '')}".strip(),
                'subject': t.get('subject', '')
            }
        # Get teacher profile pictures
        pic_resp = safe_execute(
            supabase.table('profile_pictures')
            .select('user_id, file_path')
            .in_('user_id', teacher_ids)
        )
        for p in pic_resp.data:
            if p['user_id'] in teacher_map:
                teacher_map[p['user_id']]['profile_picture'] = p['file_path']

    # Attach teacher info to each awarded point
    for p in awarded_points:
        tid = p.get('teacher_id')
        if tid and tid in teacher_map:
            p['teacher_name'] = teacher_map[tid]['name']
            p['teacher_subject'] = teacher_map[tid].get('subject', '')
            p['teacher_profile_picture'] = teacher_map[tid].get('profile_picture', '')

    # Return tasks, awarded points, and all-time points
    return jsonify({
        'tasks': tasks,
        'awarded_points': awarded_points,
        'total_points': sum([t.get('points', 0) for t in tasks if t.get('status', '').lower() in ['assigned', 'pending']]),
        'all_time_points': all_time_points
    })





# ✅ FILE CONFIGURATION
ALLOWED_EXTENSIONS = {
    # Images
    'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg',
    # Documents
    'pdf', 'doc', 'docx', 'txt', 'rtf', 'odt',
    # Spreadsheets
    'xls', 'xlsx', 'csv', 'ods',
    # Presentations
    'ppt', 'pptx', 'odp',
    # Archives
    'zip', 'rar', '7z',
    # Audio
    'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg',
    # Removed video: 'mp4', 'mov', 'avi', 'wmv', 'mkv', 'flv',
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per file
MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50MB per submission


# Add this after initializing Supabase client

# ✅ SIMPLER: Remove the bucket creation attempt
def init_storage_buckets():
    """Initialize required storage buckets"""
    try:
        # Just check if bucket exists
        buckets = supabase.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        
        if 'task-files' in bucket_names:
            print("[STORAGE] ✅ 'task-files' bucket already exists")
        else:
            print("[STORAGE] ⚠️ WARNING: 'task-files' bucket not found - please create manually in Supabase")
            
    except Exception as e:
        print(f"[STORAGE] Warning: {e}")

# Call this on app startup
@app.before_request
def before_first_request():
    if not hasattr(app, 'buckets_initialized'):
        init_storage_buckets()
        app.buckets_initialized = True

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_type(file_extension):
    """Return file type based on extension"""
    ext = file_extension.lower()
    
    if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg']:
        return 'image'
    elif ext == 'pdf':
        return 'pdf'
    elif ext in ['doc', 'docx', 'txt', 'rtf', 'odt']:
        return 'document'
    elif ext in ['xls', 'xlsx', 'csv', 'ods']:
        return 'spreadsheet'
    elif ext in ['ppt', 'pptx', 'odp']:
        return 'presentation'
    elif ext in ['zip', 'rar', '7z']:
        return 'archive'
    # Removed video types
    elif ext in ['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg']:
        return 'audio'
    else:
        return 'document'


# --- UPLOAD PROOF OF FILES PAGE ROUTE ---
@app.route('/api/upload_task_files', methods=['POST'])
def upload_task_files():
    """
    Upload multiple files for task submission.
    Updates task status to "Pending" and sends notifications.
    """
    try:
        user_id = request.form.get('user_id')
        task_id = request.form.get('task_id')
        
        # Validate required fields
        if not user_id or not task_id:
            return jsonify({
                'success': False,
                'message': 'Missing user_id or task_id'
            }), 400
        
        # Check for files
        if 'files' not in request.files or len(request.files.getlist('files')) == 0:
            return jsonify({
                'success': False,
                'message': 'No files provided'
            }), 400
        
        files = request.files.getlist('files')
        uploaded_files = []
        total_size = 0
        
        # ✅ PROCESS EACH FILE
        for file in files:
            if not file or file.filename == '':
                continue
            
            # Check if file is allowed
            if not allowed_file(file.filename):
                continue
            
            # Get file size
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)
            
            # Validate file size
            if file_size == 0 or file_size > MAX_FILE_SIZE:
                continue
            
            # Generate unique filename
            file_ext = file.filename.rsplit('.', 1)[1].lower()
            unique_filename = f"task_{task_id}_user_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}.{file_ext}"
            
            # Get MIME type
            mime_type, _ = mimetypes.guess_type(file.filename)
            if not mime_type:
                mime_type = 'application/octet-stream'
            
            file_bytes = file.read()
            
            try:
                # ✅ UPLOAD TO SUPABASE STORAGE
                response = supabase.storage.from_('task-files').upload(
                    unique_filename, 
                    file_bytes, 
                    {"content-type": mime_type}
                )
                
                # Generate public URL
                public_url = f"https://bdcmzatfoaocnsfdpudv.supabase.co/storage/v1/object/public/task-files/{unique_filename}"
                
                uploaded_files.append({
                    'filename': unique_filename,
                    'original_filename': file.filename,
                    'file_url': public_url,
                    'file_size': file_size,
                    'file_type': get_file_type(file_ext),
                    'mime_type': mime_type
                })
                
                total_size += file_size
                
            except Exception as e:
                print(f"[UPLOAD] Error uploading file: {e}")
                continue
        
        # ✅ INSERT RECORDS INTO DATABASE
        if uploaded_files:
            records = []
            for f in uploaded_files:
                records.append({
                    'task_id': int(task_id),
                    'student_id': int(user_id),
                    'filename': f['filename'],
                    'original_filename': f['original_filename'],
                    'file_url': f['file_url'],
                    'file_size': f['file_size'],
                    'file_type': f['file_type'],
                    'mime_type': f['mime_type'],
                })
            
            # Insert all records
            result = safe_execute(supabase.table('task_file_submissions').insert(records))
            print(f"[UPLOAD] Inserted {len(records)} file records")
            
            # ✅ UPDATE TASK STATUS TO PENDING
            now_ph = datetime.now(timezone('Asia/Manila')).isoformat()
            safe_execute(
                supabase.table('task_assignments').update({
                    'status': 'Pending',
                    'submitted_at': now_ph,
                    'completed_at': now_ph
                }).eq('task_id', int(task_id)).eq('student_id', int(user_id))
            )
            print(f"[UPLOAD] Updated task {task_id} status to Pending")
            
            # ✅ GET TASK INFORMATION
            task_info = safe_execute(
                supabase.table('task_assignments')
                .select('teacher_id, task, points')
                .eq('task_id', int(task_id))
            )
            
            if task_info.data and len(task_info.data) > 0:
                task_data = task_info.data[0]
                teacher_id = task_data.get('teacher_id')
                task_name = task_data.get('task', '')
                points = task_data.get('points', 0)
                
                # ✅ GET STUDENT INFORMATION
                student_info = safe_execute(
                    supabase.table('user_info')
                    .select('first_name, last_name, role')
                    .eq('id', int(user_id))
                )
                student_name = 'Student'
                user_role = 'Student'
                if student_info.data and len(student_info.data) > 0:
                    student_name = f"{student_info.data[0].get('first_name', '')} {student_info.data[0].get('last_name', '')}".strip()
                    user_role = student_info.data[0].get('role', 'Student')
                
                # ✅ SEND NOTIFICATION TO TEACHER
                safe_execute(supabase.table('notifications').insert({
                    'user_id': teacher_id,
                    'sender_id': int(user_id),
                    'title': 'Activity Submitted',
                    'message': f"{student_name} has submitted the activity '{task_name}'. Please review and approve.",
                    'task_id': int(task_id),
                    'notif_type': 'Task',
                    'status': 'Unread',
                }))
                print(f"[UPLOAD] Sent notification to teacher {teacher_id}")
                
                # ✅ LOG TO ACTIVITY LOG
                safe_execute(supabase.table('admin_activity_log').insert({
                    'user_id': int(user_id),
                    'user_role': user_role,
                    'action': 'Submit Activity',
                    'activity': 'Activity Submission',
                    'description': f"{student_name} submitted activity '{task_name}' ({len(uploaded_files)} file(s))",
                    'details': f"Points: {points}, Files: {', '.join([f['original_filename'] for f in uploaded_files])}",
                }))
                print(f"[UPLOAD] Logged activity for student {user_id}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully uploaded {len(uploaded_files)} file(s)',
            'files_uploaded': len(uploaded_files),
            'total_size': total_size,
            'file_urls': uploaded_files,
            'new_status': 'Pending'
        }), 200
        
    except Exception as e:
        print(f"[UPLOAD] Critical error: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500



# --- DISPLAY PROOF OF MARRIAGE IN TASK PAGE ROUTE ---
@app.route('/api/get_task_files', methods=['GET'])
def get_task_files():
    """
    Get all submitted files for a specific task and student.
    Query params: task_id, user_id (student_id)
    """
    try:
        task_id = request.args.get('task_id')
        user_id = request.args.get('user_id')
        
        print(f"[DEBUG get_task_files] START - task_id={task_id}, user_id={user_id}")
        
        if not task_id or not user_id:
            print(f"[DEBUG get_task_files] MISSING PARAMS")
            return jsonify({
                'success': False,
                'message': 'Missing task_id or user_id'
            }), 400
        
        # Fetch files from task_file_submissions table
        files_resp = safe_execute(
            supabase.table('task_file_submissions')
            .select('*')
            .eq('task_id', int(task_id))
            .eq('student_id', int(user_id))
            .order('uploaded_at', desc=True)
        )
        
        files = files_resp.data if files_resp.data else []
        
        print(f"[DEBUG get_task_files] FILES FOUND: {len(files)}")
        
        return jsonify({
            'success': True,
            'files': files,
            'total_files': len(files),
            'total_size': sum([f.get('file_size', 0) for f in files])
        }), 200
        
    except Exception as e:
        print(f"[ERROR get_task_files] {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500



    

# --- DISPLAY REWARDS IN REWARDS PAGE ROUTE ---
@app.route('/rewards', methods=['GET'])
def get_rewards():
    import ast
    try:
        def to_list(val):
            if isinstance(val, list):
                return val
            if val is None or val == '':
                return []
            if isinstance(val, str):
                val = val.strip()
                if val.startswith('[') and val.endswith(']'):
                    try:
                        parsed = ast.literal_eval(val)
                        if isinstance(parsed, list):
                            return parsed
                    except Exception:
                        pass
                    try:
                        import json
                        parsed = json.loads(val)
                        if isinstance(parsed, list):
                            return parsed
                    except Exception:
                        pass
                if ',' in val:
                    return [v.strip().strip('"').strip("'") for v in val.split(',')]
                return [val.strip().strip('"').strip("'")]
            return [val]

        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'Missing user_id'}), 400

        # Fetch student's year_level and section from user_info
        user_resp = safe_execute(
            supabase.table('user_info')
            .select('year_level', 'section', 'total_points')
            .eq('id', user_id)
        )
        if not user_resp.data or len(user_resp.data) == 0:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        year_level = user_resp.data[0].get('year_level', '')
        section = user_resp.data[0].get('section', '')
        total_points = user_resp.data[0].get('total_points', 0)

        # --- NEW: Get all teachers assigned to this section and grade level ---
        teacher_assignments_resp = safe_execute(
            supabase.table('teacher_class_assignments')
            .select('teacher_id')
            .eq('section', section)
            .eq('grade_level', year_level)
        )
        
        teacher_ids = [t['teacher_id'] for t in teacher_assignments_resp.data] if teacher_assignments_resp.data else []

        teachers = []
        if teacher_ids:
            user_resp = safe_execute(
                supabase.table('user_info')
                .select('id, first_name, last_name, subject')
                .in_('id', teacher_ids)
            )
            for t in user_resp.data if user_resp.data else []:
                pic_resp = safe_execute(
                    supabase.table('profile_pictures')
                    .select('file_path')
                    .eq('user_id', t['id'])
                    .order('uploaded_at', desc=True)
                    .limit(1)
                )
                profile_picture = pic_resp.data[0]['file_path'] if pic_resp.data else ''
                teachers.append({
                    'id': t['id'],
                    'name': f"{t.get('first_name', '')} {t.get('last_name', '')}".strip(),
                    'subject': t.get('subject', ''),
                    'profilePicture': profile_picture,
                })

        # Fetch all available rewards
        rewards_resp = safe_execute(
            supabase.table('rewards')
            .select('reward_id, reward_name, description, point_cost, available_quantity, category, status, grade_level, section, created_by')
            .eq('status', 'Available')
            .gt('available_quantity', 0)
        )
        rewards = rewards_resp.data if rewards_resp.data else []

        rewards = [r for r in rewards if r.get('reward_id') is not None]
        for r in rewards:
            r['reward_id'] = int(r.get('reward_id', 0) or 0)
            r['point_cost'] = int(r.get('point_cost', 0) or 0)
            r['available_quantity'] = int(r.get('available_quantity', 0) or 0)
            r['created_by'] = int(r.get('created_by', 0) or 0) if r.get('created_by') is not None else None

        filtered_rewards = []
        for r in rewards:
            grade_levels = to_list(r.get('grade_level'))
            sections = to_list(r.get('section'))
            grade_ok = (
                not grade_levels or
                str(year_level) in [str(g) for g in grade_levels] or
                'All Grades' in [str(g) for g in grade_levels]
            )
            section_ok = (
                not sections or
                str(section) in [str(s) for s in sections] or
                'All Sections' in [str(s) for s in sections]
            )
            if grade_ok and section_ok:
                filtered_rewards.append(r)

        for r in filtered_rewards:
            teacher_id = r.get('created_by')
            teacher_name = ''
            teacher_subject = ''
            teacher_profile_picture = ''
            if teacher_id:
                teacher_resp = safe_execute(
                    supabase.table('user_info')
                    .select('first_name', 'last_name', 'subject')
                    .eq('id', teacher_id)
                )
                if teacher_resp.data and len(teacher_resp.data) > 0:
                    t = teacher_resp.data[0]
                    teacher_name = f"{t.get('first_name', '')} {t.get('last_name', '')}".strip()
                    teacher_subject = t.get('subject', '')
                pic_resp = safe_execute(
                    supabase.table('profile_pictures')
                    .select('file_path')
                    .eq('user_id', teacher_id)
                    .order('uploaded_at', desc=True)
                    .limit(1)
                )
                if pic_resp.data and len(pic_resp.data) > 0:
                    teacher_profile_picture = pic_resp.data[0].get('file_path', '')
            r['teacher_name'] = teacher_name
            r['teacher_subject'] = teacher_subject
            r['teacher_profile_picture'] = teacher_profile_picture

        redeemed_resp = safe_execute(supabase.table('reward_redemptions')
            .select('reward_id')
            .eq('student_id', user_id))
        redeemed_ids = [int(r['reward_id']) for r in redeemed_resp.data if r.get('reward_id') is not None] if redeemed_resp.data else []

        return jsonify({
            'success': True,
            'rewards': filtered_rewards,
            'total_points': total_points,
            'redeemed_ids': redeemed_ids,
            'year_level': year_level,
            'section': section,
            'teachers': teachers,  # <-- ADD THIS LINE
        }), 200
    except Exception as e:
        print(f"Error fetching rewards: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# --- PAG REDEEM REWARDS ROUTE ---
@app.route('/redeem_reward', methods=['POST'])
def redeem_reward():
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        reward_id = data.get('reward_id')
        grade_level = data.get('grade_level')
        section = data.get('section')
        points_deducted = data.get('points_deducted')
        remarks = data.get('remarks', '')  # <-- REMARKS FIELD

        if student_id is None or reward_id is None or grade_level is None or section is None or points_deducted is None:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        # 1. Check if student already redeemed this reward
        already_redeemed = safe_execute(supabase.table('reward_redemptions') \
            .select('redemption_id') \
            .eq('student_id', student_id) \
            .eq('reward_id', reward_id))
        if already_redeemed.data and len(already_redeemed.data) > 0:
            print('ALREADY REDEEMED')
            return jsonify({'success': False, 'error': 'You have already redeemed this reward.'}), 400

        # 2. Check reward quantity
        reward_resp = safe_execute(supabase.table('rewards').select('available_quantity, created_by').eq('reward_id', reward_id))
        if not reward_resp.data or len(reward_resp.data) == 0:
            return jsonify({'success': False, 'error': 'Reward not found'}), 404

        available_quantity = reward_resp.data[0]['available_quantity']
        teacher_id = reward_resp.data[0].get('created_by')
        if available_quantity is None or available_quantity <= 0:
            print('OUT OF STOCK')
            return jsonify({'success': False, 'error': 'Reward is out of stock'}), 400

        # 3. Deduct points from user_info
        user_resp = safe_execute(supabase.table('user_info').select('total_points').eq('id', student_id))
        if not user_resp.data or len(user_resp.data) == 0:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        current_points = user_resp.data[0]['total_points']
        if current_points < points_deducted:
            print('NOT ENOUGH POINTS')
            return jsonify({'success': False, 'error': 'Not enough points'}), 400

        new_points = current_points - points_deducted

        # 4. Update user points
        safe_execute(supabase.table('user_info').update({'total_points': new_points}).eq('id', student_id))

        # 5. Update reward quantity
        safe_execute(supabase.table('rewards').update({'available_quantity': available_quantity - 1}).eq('reward_id', reward_id))

        # 6. Insert into reward_redemptions (WITH REMARKS)
        redemption_resp = safe_execute(supabase.table('reward_redemptions').insert({
            'student_id': student_id,
            'reward_id': reward_id,
            'grade_level': grade_level,
            'section': section,
            'points_deducted': points_deducted,
            'teacher_id': teacher_id,
            'remarks': remarks,  # <-- SAVE REMARKS HERE
            'processed_at': datetime.now().isoformat()
        }))
        
        # Get the redemption_id from the insert response
        redemption_id = None
        if redemption_resp.data and len(redemption_resp.data) > 0:
            redemption_id = redemption_resp.data[0].get('redemption_id')

        # --- Insert into admin_activity_log ---
        # Get student info for log
        student_resp = safe_execute(supabase.table('user_info').select('first_name, last_name').eq('id', student_id))
        student = student_resp.data[0] if student_resp.data else {}
        student_name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip()

        # Get reward info for log
        reward_resp2 = safe_execute(supabase.table('rewards').select('reward_name').eq('reward_id', reward_id))
        reward_name = reward_resp2.data[0]['reward_name'] if reward_resp2.data else ''

        safe_execute(supabase.table('admin_activity_log').insert({
            'user_id': int(student_id),
            'user_role': 'Student',
            'action': 'Redeem Reward',
            'activity': 'Reward Redemption',
            'description': f"{student_name} redeemed the reward '{reward_name}'.",
            'details': f"Reward: {reward_name}, Points Deducted: {points_deducted}, Grade: {grade_level}, Section: {section}, Remarks: {remarks}",
        }))

        # --- Insert into notifications table for teacher/admin ---
        if teacher_id:
            safe_execute(supabase.table('notifications').insert({
                'user_id': teacher_id,  # teacher/admin who created the reward
                'sender_id': int(student_id),
                'title': 'Reward Redemption',
                'message': f"{student_name} redeemed the reward '{reward_name}'. Please process the claim.",
                'redemption_id': redemption_id,
                'notif_type': 'Reward',
                'status': 'Unread',
            }))

        return jsonify({'success': True, 'message': 'Reward redeemed successfully', 'new_points': new_points}), 200

    except Exception as e:
        print(f"Error redeeming reward: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    

# --- GET REWARD REDEMPTIONS HISTORY ROUTE ---
@app.route('/reward_redemptions', methods=['GET'])
def get_reward_redemptions():
    """
    Get all reward redemptions for a student.
    Query param: student_id
    """
    student_id = request.args.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'error': 'Missing student_id'}), 400

    try:
        # Join reward_redemptions with rewards table to get reward details
        resp = safe_execute(supabase.table('reward_redemptions') \
            .select('redemption_id, reward_id, points_deducted, processed_at, teacher_id, status, notes, used_at, rewards(reward_name, description, category, point_cost, created_by)')
            .eq('student_id', student_id) \
            .order('processed_at', desc=True))
        redemptions = resp.data if resp.data else []

        # For each redemption, get teacher name, subject, and profile picture
        for r in redemptions:
            teacher_id = None
            # Try from reward's created_by first
            if r.get('rewards') and r['rewards'].get('created_by'):
                teacher_id = r['rewards']['created_by']
            elif r.get('teacher_id'):
                teacher_id = r['teacher_id']
            teacher_name = ''
            teacher_subject = ''
            teacher_profile_picture = ''
            if teacher_id:
                teacher_resp = safe_execute(
                    supabase.table('user_info')
                    .select('first_name', 'last_name', 'subject')
                    .eq('id', teacher_id)
                )
                if teacher_resp.data and len(teacher_resp.data) > 0:
                    t = teacher_resp.data[0]
                    teacher_name = f"{t.get('first_name', '')} {t.get('last_name', '')}".strip()
                    teacher_subject = t.get('subject', '')
                # Get profile picture
                pic_resp = safe_execute(
                    supabase.table('profile_pictures')
                    .select('file_path')
                    .eq('user_id', teacher_id)
                    .order('uploaded_at', desc=True)
                    .limit(1)
                )
                if pic_resp.data and len(pic_resp.data) > 0:
                    teacher_profile_picture = pic_resp.data[0].get('file_path', '')
            r['teacher_name'] = teacher_name
            r['teacher_subject'] = teacher_subject
            r['teacher_profile_picture'] = teacher_profile_picture

        return jsonify({'success': True, 'redemptions': redemptions}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    

    

# --- GET LEADERBOARD BY SECTION ROUTE ---
@app.route('/leaderboard', methods=['GET'])
def get_leaderboard():
    """
    Get leaderboard for a specific section.
    Query params: section (required), period (optional: 'This Week', 'This Month', 'Current Points')
    """
    try:
        section = request.args.get('section')
        period = request.args.get('period', 'Current Points')

        if not section:
            return jsonify({'error': 'Section is required'}), 400

        # 1. Get all students in the section
        students_resp = safe_execute(supabase.table('user_info') \
            .select('id, first_name, last_name, section, year_level, total_points') \
            .eq('section', section) \
            .eq('role', 'Student') \
            .eq('status', 'Active'))
        students = students_resp.data if students_resp and getattr(students_resp, 'data', None) else []

        leaderboard = []
        if period == 'Current Points':
            for student in students:
                user_id = student['id']
                # Get latest profile picture from profile_pictures table
                pic_resp = safe_execute(supabase.table('profile_pictures') \
                    .select('file_path') \
                    .eq('user_id', user_id) \
                    .order('uploaded_at', desc=True) \
                    .limit(1))
                if pic_resp and getattr(pic_resp, 'data', None) and len(pic_resp.data) > 0:
                    profile_picture = pic_resp.data[0].get('file_path')
                else:
                    profile_picture = ''  # or None

                leaderboard.append({
                    'id': user_id,
                    'first_name': student.get('first_name', ''),
                    'last_name': student.get('last_name', ''),
                    'total_points': student.get('total_points', 0),
                    'section': student.get('section', ''),
                    'year_level': student.get('year_level', ''),
                    'profile_picture': profile_picture,
                })
        else:
            # Use points table for This Week, This Month
            now = datetime.now()
            if period == 'This Week':
                start = now - timedelta(days=now.weekday())
            elif period == 'This Month':
                start = now.replace(day=1)
            else:
                start = None

            for student in students:
                user_id = student['id']
                points_query = supabase.table('points') \
                    .select('points, received_at') \
                    .eq('student_id', user_id) \
                    .eq('status', 'approved')
                if start:
                    points_query = points_query.gte('received_at', start.isoformat())
                points_resp = safe_execute(points_query)
                total_points = sum([p['points'] for p in points_resp.data]) if points_resp and getattr(points_resp, 'data', None) else 0

                # Get latest profile picture from profile_pictures table
                pic_resp = safe_execute(supabase.table('profile_pictures') \
                    .select('file_path') \
                    .eq('user_id', user_id) \
                    .order('uploaded_at', desc=True) \
                    .limit(1))
                profile_picture = ''
                if pic_resp and getattr(pic_resp, 'data', None) and len(pic_resp.data) > 0:
                    profile_picture = pic_resp.data[0].get('file_path')
                else:
                    profile_picture = ''  # or None

                leaderboard.append({
                    'id': user_id,
                    'first_name': student.get('first_name', ''),
                    'last_name': student.get('last_name', ''),
                    'total_points': total_points,
                    'section': student.get('section', ''),
                    'year_level': student.get('year_level', ''),
                    'profile_picture': profile_picture,
                })

        # 3. Sort by total_points desc
        leaderboard.sort(key=lambda x: x['total_points'], reverse=True)
        for idx, student in enumerate(leaderboard):
            student['rank'] = idx + 1

        current_user_id = request.args.get('user_id')
        current_points = 0
        if current_user_id:
            user_resp = safe_execute(supabase.table('user_info').select('total_points').eq('id', current_user_id))
            if user_resp and getattr(user_resp, 'data', None) and len(user_resp.data) > 0:
                current_points = user_resp.data[0].get('total_points', 0)

        return jsonify({
            'students': leaderboard,
            'current_points': current_points
        }), 200
    except Exception as e:
        import traceback
        return jsonify({'error': str(e)}), 500


# --- GET CURRENT SCHOOL LEADERBOARD BY SECTION ROUTE ---
def get_current_school_year():
    today = datetime.now().date()
    resp = safe_execute(
        supabase.table('quarters')
        .select('school_year, start_date, end_date')
    )
    for q in resp.data:
        start = parser.parse(q['start_date']).date()
        end = parser.parse(q['end_date']).date()
        if start <= today <= end:
            return q['school_year']
    return None

# --- GET CURRENT QUARTER LEADERBOARD BY SECTION ROUTE ---
@app.route('/current_quarter', methods=['GET'])
def get_current_quarter():
    today = datetime.now().date()
    resp = safe_execute(
        supabase.table('quarters')
        .select('quarter_name, start_date, end_date, school_year')
    )
    for q in resp.data:
        start = parser.parse(q['start_date']).date()
        end = parser.parse(q['end_date']).date()
        if start <= today <= end:
            # Ensure ISO format for end_date
            end_iso = parser.parse(q['end_date']).isoformat()
            return jsonify({
                'quarter_name': q['quarter_name'],
                'school_year': q['school_year'],
                'end_date': end_iso
            }), 200
    return jsonify({'error': 'No current quarter found'}), 404

# --- GET ALL TIME POINTS KADA QUARTER LEADERBOARD BY SECTION ROUTE ---
@app.route('/quarter_points', methods=['GET'])
def get_quarter_points():
    from dateutil import parser
    from pytz import timezone

    quarter_name = request.args.get('quarter_name')
    school_year = request.args.get('school_year')
    section = request.args.get('section')

    if not quarter_name or not section:
        return jsonify({'error': 'Missing parameters'}), 400

    # Auto-detect school year if not provided
    if not school_year:
        school_year = get_current_school_year()
        if not school_year:
            return jsonify({'error': 'School year not found for today'}), 404

    # 1. Get quarter date range from DB
    quarter_resp = safe_execute(
        supabase.table('quarters')
        .select('start_date, end_date')
        .eq('quarter_name', quarter_name)
        .eq('school_year', school_year)
    )
    if not quarter_resp.data or len(quarter_resp.data) == 0:
        return jsonify({'error': 'Quarter not found'}), 404

    start_date = quarter_resp.data[0]['start_date']
    end_date = quarter_resp.data[0]['end_date']

    # 2. Get all students in the section
    students_resp = safe_execute(
        supabase.table('user_info')
        .select('id, first_name, last_name')
        .eq('section', section)
        .eq('role', 'Student')
        .eq('status', 'Active')
    )
    students = students_resp.data if students_resp.data else []

    results = []
    tz = timezone('Asia/Manila')

    for student in students:
        student_id = student['id']

        # 3. Sum points from points table (approved, within quarter)
        points_resp = safe_execute(
            supabase.table('points')
            .select('points, received_at')
            .eq('student_id', student_id)
            .eq('status', 'approved')
            .gte('received_at', start_date)
            .lte('received_at', end_date)
        )
        points_total = sum([
            p['points'] for p in points_resp.data if p.get('points') is not None
        ]) if points_resp.data else 0

        # 4. Sum points from milestone_claims table (within quarter)
        milestone_resp = safe_execute(
            supabase.table('milestone_claims')
            .select('points_awarded', 'claimed_at')
            .eq('student_id', student_id)
            .gte('claimed_at', start_date)
            .lte('claimed_at', end_date)
        )
        milestone_total = sum([
            m['points_awarded'] for m in milestone_resp.data if m.get('points_awarded') is not None
        ]) if milestone_resp.data else 0

        total = points_total + milestone_total

        # 5. Get latest profile picture from profile_pictures table
        pic_resp = safe_execute(
            supabase.table('profile_pictures')
            .select('file_path')
            .eq('user_id', student_id)
            .order('uploaded_at', desc=True)
            .limit(1)
        )
        profile_picture = ''
        if pic_resp and getattr(pic_resp, 'data', None) and len(pic_resp.data) > 0:
            profile_picture = pic_resp.data[0].get('file_path')
        else:
            profile_picture = ''  # or default

        results.append({
            'student_id': student_id,
            'name': f"{student.get('first_name', '')} {student.get('last_name', '')}",
            'points': total,
            'points_from_tasks': points_total,
            'points_from_milestones': milestone_total,
            'profile_picture': profile_picture, # <-- ADD THIS
        })

    # Sort by points descending
    results.sort(key=lambda x: x['points'], reverse=True)

    return jsonify({
        'success': True,
        'quarter': quarter_name,
        'school_year': school_year,
        'section': section,
        'students': results
    }), 200


# --- GET ACTIVITIES COMPLETED COUNT ROUTE SA LEADERBOARDS PAGE ---
@app.route('/activities_completed', methods=['GET'])
def activities_completed():
    user_id = request.args.get('user_id')
    period = request.args.get('period', 'Current Points')
    quarter_name = request.args.get('quarter_name')
    school_year = request.args.get('school_year')

    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    from datetime import datetime, timedelta
    now = datetime.now()
    start = None
    end = None

    # If quarter_name is provided, get its date range
    if quarter_name:
        if not school_year:
            school_year = get_current_school_year()
        quarter_resp = safe_execute(
            supabase.table('quarters')
            .select('start_date, end_date')
            .eq('quarter_name', quarter_name)
            .eq('school_year', school_year)
        )
        if not quarter_resp.data or len(quarter_resp.data) == 0:
            return jsonify({'error': 'Quarter not found'}), 404
        start = quarter_resp.data[0]['start_date']
        end = quarter_resp.data[0]['end_date']
    elif period == 'Current Points':
        school_year = get_current_school_year()
        quarter_resp = safe_execute(
            supabase.table('quarters')
            .select('start_date, end_date, quarter_name')
            .eq('school_year', school_year)
        )
        today = now.date()
        
        current_quarter = None
        for q in quarter_resp.data:
            q_start = parser.parse(q['start_date']).date()
            q_end = parser.parse(q['end_date']).date()
            if q_start <= today <= q_end:
                current_quarter = q
                break
        
        if current_quarter:
            start = current_quarter['start_date']
            end = current_quarter['end_date']
        else:
            # Fallback: use the most recent quarter that hasn't ended yet
            future_quarters = [q for q in quarter_resp.data if parser.parse(q['end_date']).date() >= today]
            if future_quarters:
                future_quarters.sort(key=lambda x: parser.parse(x['start_date']).date())
                current_quarter = future_quarters[0]
                start = current_quarter['start_date']
                end = current_quarter['end_date']
    elif period == 'This Week':
        start = (now - timedelta(days=now.weekday())).date().isoformat()
        end = (now + timedelta(days=6-now.weekday())).date().isoformat()
    elif period == 'This Month':
        start = now.replace(day=1).date().isoformat()
        next_month = now.replace(day=28) + timedelta(days=4)
        last_day = (next_month - timedelta(days=next_month.day)).date().isoformat()
        end = last_day

    # Build query
    query = supabase.table('points') \
        .select('note, received_at') \
        .eq('student_id', user_id) \
        .eq('status', 'approved')
    
    if start:
        query = query.gte('received_at', start)
    if end:
        query = query.lte('received_at', end)

    resp = safe_execute(query)
    
    if not resp.data:
        return jsonify({'count': 0}), 200
    
    count = 0
    
    for p in resp.data:
        note = p.get('note', '')
        # More flexible activity detection
        if note and ('completed task:' in note.lower() or 'activity' in note.lower() or 'task' in note.lower()):
            count += 1
    
    return jsonify({'count': count}), 200


# --- WEEKLY POINTS ROUTE SA LEADERBIARD PAFE---
@app.route('/weekly_points', methods=['GET'])
def weekly_points():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    tz = timezone('Asia/Manila')
    now = datetime.now(tz)
    start_of_week = now - timedelta(days=now.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    days = [(start_of_week + timedelta(days=i)).date() for i in range(7)]
    points_per_day = [0] * 7

    # 1. Points from 'points' table (all approved points)
    points_resp = safe_execute(
        supabase.table('points')
        .select('points, received_at')
        .eq('student_id', user_id)
        .eq('status', 'approved')
        .gte('received_at', start_of_week.date().isoformat())
        .lte('received_at', end_of_week.date().isoformat())
    )
    if points_resp.data:
        for p in points_resp.data:
            date_str = p['received_at']
            try:
                dt = parser.parse(date_str)
                dt_local = dt.astimezone(tz)
                date_obj = dt_local.date()
                if date_obj in days:
                    idx = (date_obj - start_of_week.date()).days
                    points_per_day[idx] += p['points']
            except Exception:
                continue

    # 2. Points from 'milestone_claims' table (points_awarded per day)
    milestone_resp = safe_execute(
        supabase.table('milestone_claims')
        .select('points_awarded, claimed_at')
        .eq('student_id', user_id)
        .gte('claimed_at', start_of_week.date().isoformat())
        .lte('claimed_at', end_of_week.date().isoformat())
    )
    if milestone_resp.data:
        for m in milestone_resp.data:
            date_str = m.get('claimed_at', '')
            points_awarded = m.get('points_awarded', 0)
            try:
                dt = parser.parse(date_str)
                dt_local = dt.astimezone(tz)
                date_obj = dt_local.date()
                if date_obj in days:
                    idx = (date_obj - start_of_week.date()).days
                    points_per_day[idx] += points_awarded
            except Exception:
                continue

    return jsonify({'points': points_per_day}), 200


# --- PROFILE PAGE ROUTE ---
@app.route('/profile_info', methods=['GET'])
def profile_info():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    # Get user info
    user_resp = safe_execute(supabase.table('user_info').select(
        'id, first_name, last_name, total_points, section, year_level, streak'
    ).eq('id', user_id))
    if not user_resp.data or len(user_resp.data) == 0:
        return jsonify({'error': 'User not found'}), 404

    user = user_resp.data[0]
    section = user.get('section')

    # Get all students in the same section, sorted by total_points desc
    classmates = safe_execute(supabase.table('user_info').select(
        'id, total_points'
    ).eq('section', section).eq('role', 'Student').eq('status', 'Active'))
    classmates_list = classmates.data if classmates.data else []
    classmates_list.sort(key=lambda x: x.get('total_points', 0), reverse=True)
    # Find rank
    rank = next((i+1 for i, s in enumerate(classmates_list) if s['id'] == user['id']), None)

    # Get latest profile picture from profile_pictures table
    pic_resp = safe_execute(supabase.table('profile_pictures').select('file_path').eq('user_id', user_id).order('uploaded_at', desc=True).limit(1))
    profile_picture = None
    if pic_resp.data and len(pic_resp.data) > 0:
        profile_picture = pic_resp.data[0].get('file_path')
    else:
        profile_picture = ''  # or None

    return jsonify({
        'id': user['id'],
        'name': f"{user.get('first_name', '')} {user.get('last_name', '')}",
        'total_points': user.get('total_points', 0),
        'streak': user.get('streak', 0),
        'rank': rank,
        'profile_picture': profile_picture
    }), 200


# --- PROFILE PICTURE UPLOAD ROUTE ---
@app.route('/upload_profile_picture', methods=['POST'])
def upload_profile_picture():
    user_id = request.form.get('user_id')
    if 'image' not in request.files or not user_id:
        return jsonify({'error': 'Missing image or user_id'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'Invalid file'}), 400

    from datetime import datetime
    filename = f"user_{user_id}_image_{datetime.now().strftime('%Y-%m-%d_%H%M%S%f')}.png"

    # Upload to Supabase Storage
    file_bytes = file.read()
    storage_resp = supabase.storage.from_('profile-pictures').upload(filename, file_bytes, {"content-type": file.mimetype})

    if hasattr(storage_resp, 'error') and storage_resp.error is not None:
        return jsonify({'error': str(storage_resp.error)}), 500

    public_url = f"https://bdcmzatfoaocnsfdpudv.supabase.co/storage/v1/object/public/profile-pictures/{filename}"

    # Check if user already has a profile picture
    existing = safe_execute(supabase.table('profile_pictures').select('pic_id').eq('user_id', user_id))
    if existing.data and len(existing.data) > 0:
        # Update existing record
        safe_execute(supabase.table('profile_pictures').update({
            'file_path': public_url,
            'uploaded_at': datetime.now().isoformat()
        }).eq('user_id', user_id))
    else:
        # Insert new record
        safe_execute(supabase.table('profile_pictures').insert({
            'user_id': int(user_id),
            'file_path': public_url,
            'uploaded_at': datetime.now().isoformat()
        }))

    # --- INSERT TO PROFILE PICTURE HISTORY ---
    safe_execute(supabase.table('profile_picture_history').insert({
        'user_id': int(user_id),
        'file_path': public_url,
        'uploaded_at': datetime.now().isoformat()
    }))

    # --- Insert to admin_activity_log ---
    user_resp = safe_execute(supabase.table('user_info').select('role, first_name, last_name').eq('id', user_id))
    user = user_resp.data[0] if user_resp.data else {}
    user_role = user.get('role', 'Student')
    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()

    safe_execute(supabase.table('admin_activity_log').insert({
        'user_id': int(user_id),
        'user_role': user_role,
        'action': 'Update Profile Picture',
        'activity': 'Profile Picture Updated',
        'description': f"{user_name} updated their profile picture.",
        'details': public_url,
    }))

    return jsonify({'success': True, 'profile_picture': public_url}), 200


@app.route('/recent_profile_pictures', methods=['GET'])
def recent_profile_pictures():
    user_id = request.args.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    try:
        resp = safe_execute(
            supabase.table('profile_picture_history')
            .select('file_path')
            .eq('user_id', user_id)
            .order('uploaded_at', desc=True)
            .limit(6)
        )
        
        if resp.data:
            pics = [r['file_path'] for r in resp.data]
        else:
            pics = []
        
        return jsonify({'recent_pictures': pics}), 200
        
    except Exception as e:
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/set_profile_picture_from_history', methods=['POST'])
def set_profile_picture_from_history():
    data = request.get_json()
    user_id = data.get('user_id')
    file_path = data.get('file_path')
    if not user_id or not file_path:
        return jsonify({'success': False, 'error': 'Missing user_id or file_path'}), 400

    from datetime import datetime

    # Update or insert into profile_pictures table
    existing = safe_execute(supabase.table('profile_pictures').select('pic_id').eq('user_id', user_id))
    if existing.data and len(existing.data) > 0:
        safe_execute(supabase.table('profile_pictures').update({
            'file_path': file_path,
            'uploaded_at': datetime.now().isoformat()
        }).eq('user_id', user_id))
    else:
        safe_execute(supabase.table('profile_pictures').insert({
            'user_id': int(user_id),
            'file_path': file_path,
            'uploaded_at': datetime.now().isoformat()
        }))

    # Log to admin_activity_log (optional)
    user_resp = safe_execute(supabase.table('user_info').select('role, first_name, last_name').eq('id', user_id))
    user = user_resp.data[0] if user_resp.data else {}
    user_role = user.get('role', 'Student')
    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    safe_execute(supabase.table('admin_activity_log').insert({
        'user_id': int(user_id),
        'user_role': user_role,
        'action': 'Change Avatar',
        'activity': 'Profile Management',
        'description': 'Changed profile picture from history.',
        'details': '',
    }))

    return jsonify({'success': True, 'profile_picture': file_path}), 200


# --- PROFILE PICTURE DELETE ROUTE ---
@app.route('/delete_profile_picture', methods=['POST'])
def delete_profile_picture():
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'Missing user_id'}), 400

        # Fetch all profile_pictures rows for the user
        resp = safe_execute(
            supabase.table('profile_pictures')
            .select('pic_id, file_path')
            .eq('user_id', int(user_id))
        )
        rows = resp.data if resp and getattr(resp, 'data', None) else []

        # Collect filenames to remove from storage
        filenames = []
        for r in rows:
            fp = r.get('file_path') or ''
            if fp:
                # Expecting public URL: .../profile-pictures/<filename>
                filename = fp.rstrip('/').split('/')[-1]
                if filename:
                    filenames.append(filename)

        # Try remove from Supabase storage (if any)
        if filenames:
            try:
                remove_resp = supabase.storage.from_('profile-pictures').remove(filenames)
                # remove_resp may have error attribute depending on client; log if present
                if hasattr(remove_resp, 'error') and remove_resp.error:
                    print(f"Storage remove error: {remove_resp.error}")
            except Exception as e:
                print(f"Exception while removing files from storage: {e}")

        # Delete DB records for the user's profile pictures
        safe_execute(
            supabase.table('profile_pictures')
            .delete()
            .eq('user_id', int(user_id))
        )

        # Optionally, you may want to update user_info or admin logs here.
        return jsonify({'success': True}), 200

    except Exception as e:
        print(f"delete_profile_picture error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



# ---PAG DISPLAY NG INFO NI STUDENTS PERSONAL INFO PAGE ROUTE ---
@app.route('/personal_info', methods=['GET'])
def personal_info():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    # Kunin lahat ng fields na kailangan mo
    user_resp = safe_execute(supabase.table('user_info').select(
        'id, first_name, middle_name, last_name, gender, email, mobile_no, year_level, section'
    ).eq('id', user_id))
    
    if not user_resp.data or len(user_resp.data) == 0:
        return jsonify({'error': 'User not found'}), 404

    user = user_resp.data[0]
    return jsonify(user), 200


# --- PERSONAL INFO PAGE SAVE CHANGES BUTTON ROUTE ---
@app.route('/update_profile_info', methods=['POST'])
def update_profile_info():
    data = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    # Email uniqueness check
    email = data.get('email')
    if email:
        resp = safe_execute(supabase.table('user_info').select('id').eq('email', email))
        for u in resp.data:
            if str(u['id']) != str(user_id):
                return jsonify({'error': 'Email already exists'}), 409

    # Get old data
    old_resp = safe_execute(supabase.table('user_info').select('*').eq('id', user_id))
    if not old_resp.data or len(old_resp.data) == 0:
        return jsonify({'error': 'User not found'}), 404
    old_data = old_resp.data[0]

    # Prepare update
    update_data = {k: v for k, v in data.items() if k != 'user_id'}
    safe_execute(supabase.table('user_info').update(update_data).eq('id', user_id))

    # Compare and log changes
    changed_fields = []
    for k, v in update_data.items():
        old_v = old_data.get(k)
        if str(old_v) != str(v):
            changed_fields.append(f"{k}: '{old_v}' → '{v}'")
    if changed_fields:
        # Get user info for log
        user_role = old_data.get('role', 'Student')
        user_name = f"{old_data.get('first_name', '')} {old_data.get('last_name', '')}".strip()
        safe_execute(supabase.table('admin_activity_log').insert({
        'user_id': int(user_id),
        'user_role': user_role,
        'action': 'Update Personal Information',
        'activity': 'User Information Modification',
        'description': f"{user_name} updated their profile details: {', '.join([field.split(':')[0] for field in changed_fields])}",
        'details': f"Modified fields: {'; '.join(changed_fields)}",
    }))

    return jsonify({'success': True, 'changed_fields': [f.split(':')[0] for f in changed_fields]}), 200


# --- PASSWORD CHANGE ROUTE ---
@app.route('/change_password', methods=['POST'])
def change_password():
    data = request.get_json()
    user_id = data.get('user_id')
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if not user_id or not current_password or not new_password:
        return jsonify({'error': 'Missing required fields'}), 400

    # 1. Check if current password is correct
    user_resp = safe_execute(supabase.table('user_info').select('password', 'role', 'first_name', 'last_name').eq('id', user_id))
    if not user_resp.data or len(user_resp.data) == 0:
        return jsonify({'error': 'User not found'}), 404

    user = user_resp.data[0]
    if user['password'] != current_password:
        return jsonify({'error': 'Current password is incorrect'}), 401

    # 2. Update password
    safe_execute(supabase.table('user_info').update({'password': new_password}).eq('id', user_id))

    # 3. Log activity
    user_role = user.get('role', 'Student')
    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    safe_execute(supabase.table('admin_activity_log').insert({
        'user_id': int(user_id),
        'user_role': user_role,
        'action': 'Change Password',
        'activity': 'User Password Modification',
        'description': f"{user_name} changed their account password",
        'details': 'User successfully changed their authentication credentials',
    }))

    return jsonify({'success': True}), 200


# --- PAGDISPLAY NG INFO NI STUDENTS SA PARENT PAGE ROUTE ---
@app.route('/parent_info', methods=['GET'])
def parent_info():
    """
    Fetch all parent records for a given student_id from the parents table.
    Usage: /parent_info?student_id=123
    """
    student_id = request.args.get('student_id')
    if not student_id:
        return jsonify({'error': 'Missing student_id'}), 400

    try:
        resp = safe_execute(supabase.table('parents').select(
            'parent_id, student_id, relationship, first_name, middle_name, last_name, gender, email, mobile_no, occupation, region, province, municipality, barangay, created_at'
        ).eq('student_id', student_id))
        parents = resp.data if resp.data else []
        return jsonify({'success': True, 'parents': parents}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

# --- PAG ADD / UPDATE NG INFO NG PARENTS ROUTE ---
@app.route('/add_parent_info', methods=['POST'])
def add_parent_info():
    """
    Insert or update a parent record for a student.
    If a parent with the same student_id and relationship exists, update it.
    Otherwise, insert a new record.
    """
    data = request.get_json()
    student_id = data.get('user_id') or data.get('student_id')
    relationship = data.get('relationship')

    if not student_id or not relationship:
        return jsonify({'error': 'Missing student_id or relationship'}), 400

    try:
        # Check if parent already exists for this student and relationship
        existing = safe_execute(supabase.table('parents') \
            .select('parent_id') \
            .eq('student_id', student_id) \
            .eq('relationship', relationship))
        
        insert_data = {
            'student_id': int(student_id),
            'relationship': relationship,
            'first_name': data.get('first_name', ''),
            'middle_name': data.get('middle_name', ''),
            'last_name': data.get('last_name', ''),
            'gender': data.get('gender', ''),
            'email': data.get('email', ''),
            'mobile_no': str(data.get('mobile_no', '')),
            'occupation': data.get('occupation', ''),
            'region': data.get('region', ''),
            'province': data.get('province', ''),
            'municipality': data.get('municipality', ''),
            'barangay': data.get('barangay', ''),
            
        }
        insert_data.pop('parent_id', None)

        if existing.data and len(existing.data) > 0:
            # Update existing parent info
            parent_id = existing.data[0]['parent_id']
            resp = safe_execute(supabase.table('parents').update(insert_data).eq('parent_id', parent_id))
            if hasattr(resp, 'error') and resp.error:
                return jsonify({'error': str(resp.error)}), 500
            return jsonify({'success': True, 'parent': insert_data, 'action': 'updated'}), 200
        else:
            # Insert new parent info
            resp = safe_execute(supabase.table('parents').insert(insert_data))
            if hasattr(resp, 'error') and resp.error:
                return jsonify({'error': str(resp.error)}), 500
            return jsonify({'success': True, 'parent': insert_data, 'action': 'inserted'}), 200

    except Exception as e:
        return jsonify({'error': f'Insert/Update error: {str(e)}'}), 500


# --- NOTIFICATIONS ROUTE ---
@app.route('/notifications', methods=['GET'])
def get_notifications():
    print('NOTIFICATIONS ROUTE CALLED')
    user_id = request.args.get('user_id')
    if not user_id:
        print('NO USER_ID')
        return jsonify({'success': False, 'error': 'Missing user_id'}), 400

    try:
        # JOIN task_assignments to get the status of the task for each notification (if notif_type == 'Task')
        resp = safe_execute(
            supabase.table('notifications')
            .select('notif_id, user_id, sender_id, title, message, reward_id, redemption_id, point_id, task_id, assignment_id, history_id, notif_type, status, created_at, task_assignments(status)')
            .eq('user_id', user_id)
            .order('created_at', desc=True)
            .limit(30)
        )
        notifications = resp.data if resp.data else []

        # Add teacher profile picture and task_status for each notification
        for n in notifications:
            teacher_id = n.get('sender_id')
            if teacher_id:
                pic_resp = safe_execute(
                    supabase.table('profile_pictures')
                    .select('file_path')
                    .eq('user_id', teacher_id)
                    .order('uploaded_at', desc=True)
                    .limit(1)
                )
                n['teacher_profile_picture'] = pic_resp.data[0]['file_path'] if pic_resp.data else ''
            # Add task_status if notif_type is Task or Points
            if n.get('notif_type') in ['Task'] and n.get('task_assignments'):
                n['task_status'] = n['task_assignments']['status']
            else:
                n['task_status'] = None

        unread_count = sum(1 for n in notifications if (n.get('status') or '').lower() == 'unread')
        return jsonify({
            'success': True,
            'notifications': notifications,
            'unread_count': unread_count
        }), 200
    except Exception as e:
        print(f"Error fetching notifications: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to fetch notifications'}), 500


# --- MARK NOTIFICATION READ PAG CLICK ROUTE ---
@app.route('/mark_notification_read', methods=['POST'])
def mark_notification_read():
    data = request.get_json()
    notif_id = data.get('notif_id')
    if not notif_id:
        return jsonify({'success': False, 'error': 'Missing notif_id'}), 400
    safe_execute(supabase.table('notifications').update({'status': 'Read'}).eq('notif_id', notif_id))
    return jsonify({'success': True}), 200


# --- MARK ALL NOTIFICATIONS READ BUTTON ROUTE ---
@app.route('/mark_all_notifications_read', methods=['POST'])
def mark_all_notifications_read():
    data = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Missing user_id'}), 400
    safe_execute(supabase.table('notifications').update({'status': 'Read'}).eq('user_id', user_id))
    return jsonify({'success': True}), 200



# --- LOGOUT ROUTE ---
@app.route('/logout', methods=['POST'])
def logout():
    data = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    # Get user info for log
    user_resp = safe_execute(supabase.table('user_info').select('role', 'first_name', 'last_name', 'email').eq('id', user_id))
    if not user_resp.data or len(user_resp.data) == 0:
        return jsonify({'error': 'User not found'}), 404
    user = user_resp.data[0]
    user_role = user.get('role', 'Student')
    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    email = user.get('email', '')

    # Get client IP address
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    # Detect device type (prefer from request, fallback to user agent)
    device_type = data.get('device_type')
    if not device_type:
        user_agent = (request.user_agent.string or '').lower()
        if 'mobile' in user_agent or 'android' in user_agent or 'iphone' in user_agent:
            device_type = 'mobile'
        elif 'tablet' in user_agent or 'ipad' in user_agent:
            device_type = 'tablet'
        elif 'windows' in user_agent:
            device_type = 'Windows computer'
        elif 'mac' in user_agent or 'macos' in user_agent:
            device_type = 'Mac computer'
        elif 'linux' in user_agent:
            device_type = 'Linux computer'
        else:
            device_type = 'computer'

    # Calculate session duration
    session_duration = "Unknown"
    login_time = data.get('login_time') or session.get('login_time')
    if login_time:
        try:
            from datetime import datetime
            if isinstance(login_time, (int, float)):
                login_dt = datetime.fromtimestamp(float(login_time))
            elif isinstance(login_time, str):
                try:
                    login_dt = datetime.fromtimestamp(float(login_time))
                except Exception:
                    from dateutil import parser
                    login_dt = parser.parse(login_time)
            else:
                login_dt = None
            logout_time = datetime.now()
            duration_seconds = (logout_time - login_dt).total_seconds()
            if duration_seconds < 60:
                session_duration = f"{int(duration_seconds)} seconds"
            elif duration_seconds < 3600:
                minutes = int(duration_seconds // 60)
                seconds = int(duration_seconds % 60)
                session_duration = f"{minutes} minutes {seconds} seconds"
            else:
                hours = int(duration_seconds // 3600)
                minutes = int((duration_seconds % 3600) // 60)
                session_duration = f"{hours} hours {minutes} minutes"
        except Exception as e:
            print(f"Error calculating session duration: {e}")
            session_duration = "Calculation error"

    # Record logout in admin_activity_log with same format as web version
    safe_execute(supabase.table('admin_activity_log').insert({
        'user_id': int(user_id),
        'user_role': user_role,
        'action': 'Logout',
        'activity': 'Authentication',
        'description': f"{user_role} {user_name} logged out from {device_type}",
        'details': f"Email: {email}\nIP Address: {ip_address.split(',')[0].strip()}\nSession Duration: {session_duration}"
    }))

    session.pop('user_id', None)

    return jsonify({'success': True}), 200



# --- END OF AN ERA FOR STUDENTS ---



# --- START FOR NEW GENERATION TEACHER ---


# ✅ ADD THIS LIGHTWEIGHT ENDPOINT FOR LOGIN VERIFICATION
@app.route('/verify_teacher_account', methods=['GET'])
def verify_teacher_account():
    """
    ✅ LIGHTWEIGHT: Quick verification that teacher exists
    No dashboard data loading - used during login only
    """
    teacher_id = request.args.get('user_id')
    if not teacher_id:
        return jsonify({'error': 'Missing user_id'}), 400

    try:
        # ✅ FAST: Just get basic teacher info - NO DASHBOARD DATA
        user_resp = safe_execute(
            supabase.table('user_info').select(
                'id, first_name, last_name, role'
            ).eq('id', teacher_id).eq('role', 'Teacher')
        )
        
        if not user_resp.data or len(user_resp.data) == 0:
            return jsonify({'error': 'Teacher not found'}), 404

        teacher = user_resp.data[0]
        
        return jsonify({
            'success': True,
            'id': teacher['id'],
            'first_name': teacher.get('first_name', ''),
            'last_name': teacher.get('last_name', ''),
            'role': teacher.get('role', '')
        }), 200

    except Exception as e:
        print(f"Error verifying teacher: {e}")
        return jsonify({'error': str(e)}), 500


# --- TEACHER DASHBOARD ROUTE ---
# --- TEACHER DASHBOARD ROUTE ---
@app.route('/teacher_dashboard', methods=['GET'])
def get_teacher_dashboard():
    try:
        user_id = request.args.get('user_id') or session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not logged in'}), 401

        # Fetch teacher info
        user_resp = safe_execute(
            supabase.table('user_info').select(
                'id, first_name, last_name, gender, section, year_level, role, subject'
            ).eq('id', user_id)
        )
        if not user_resp.data or len(user_resp.data) == 0:
            return jsonify({'error': 'User not found'}), 404

        user = user_resp.data[0]

        # Fetch latest profile picture
        pic_resp = safe_execute(
            supabase.table('profile_pictures')
            .select('file_path')
            .eq('user_id', user_id)
            .order('uploaded_at', desc=True)
            .limit(1)
        )
        profile_picture = pic_resp.data[0]['file_path'] if pic_resp.data else ''

        # Fetch teacher's class assignments
        assignments_resp = safe_execute(
            supabase.table('teacher_class_assignments')
            .select('grade_level, section')
            .eq('teacher_id', user_id)
        )
        assignments = assignments_resp.data if assignments_resp.data else []

        # Get all students from teacher's classes
        student_ids = []
        for assignment in assignments:
            students_resp = safe_execute(
                supabase.table('user_info')
                .select('id')
                .eq('role', 'Student')
                .eq('year_level', assignment['grade_level'])
                .eq('section', assignment['section'])
            )
            if students_resp.data:
                student_ids.extend([s['id'] for s in students_resp.data])

        # Remove duplicate student IDs
        student_ids = list(set(student_ids))
        active_students_count = len(student_ids)

        # Calculate monthly stats
        now = datetime.now()
        month_start = now.replace(day=1).date().isoformat()

        # Points awarded this month
        points_awarded_resp = safe_execute(
            supabase.table('points')
            .select('points, student_id')
            .eq('teacher_id', user_id)
            .eq('status', 'approved')
            .gte('received_at', month_start)
        )
        points_awarded_this_month = sum([
            p['points'] for p in points_awarded_resp.data
            if p['student_id'] in student_ids
        ]) if points_awarded_resp.data else 0

        # Rewards redeemed this month
        rewards_redeemed_resp = safe_execute(
            supabase.table('reward_redemptions')
            .select('redemption_id, student_id')
            .eq('teacher_id', user_id)
            .gte('processed_at', month_start)
        )
        rewards_redeemed_this_month = len([ 
            r for r in rewards_redeemed_resp.data
            if r['student_id'] in student_ids
        ]) if rewards_redeemed_resp.data else 0

        # Calculate class engagement this week
        week_start = now - timedelta(days=now.weekday())
        week_start_str = week_start.date().isoformat()
        
        points_this_week_resp = safe_execute(
            supabase.table('points')
            .select('student_id')
            .eq('teacher_id', user_id)
            .eq('status', 'approved')
            .gte('received_at', week_start_str)
        )
        
        students_awarded_this_week = set([
            p['student_id'] for p in points_this_week_resp.data
            if p['student_id'] in student_ids
        ]) if points_this_week_resp.data else set()
        
        engagement_percent = 0
        if active_students_count > 0:
            engagement_percent = round((len(students_awarded_this_week) / active_students_count) * 100)

        dashboard_stats = {
            'active_students': active_students_count,
            'points_awarded_this_month': points_awarded_this_month,
            'rewards_redeemed_this_month': rewards_redeemed_this_month,
            'class_engagement_this_week': engagement_percent,
        }

        # Get top students
        top_students = []
        if student_ids:
            students_resp = safe_execute(
                supabase.table('user_info')
                .select('id, first_name, last_name, streak, total_points, year_level, section')
                .in_('id', student_ids)
                .eq('role', 'Student')
                .limit(50)
            )
            students = students_resp.data if students_resp.data else []

            for student in students:
                # Get student's profile picture
                pic_resp = safe_execute(
                    supabase.table('profile_pictures')
                    .select('file_path')
                    .eq('user_id', student['id'])
                    .order('uploaded_at', desc=True)
                    .limit(1)
                )
                st_profile = pic_resp.data[0]['file_path'] if pic_resp.data else ''

                # Get redeemed rewards count
                redeemed_resp = safe_execute(
                    supabase.table('reward_redemptions')
                    .select('redemption_id')
                    .eq('student_id', student['id'])
                )
                redeemed_count = len(redeemed_resp.data) if redeemed_resp.data else 0

                # Check if student was active this week
                active_this_week = student['id'] in students_awarded_this_week

                top_students.append({
                    'id': student['id'],
                    'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
                    'streak': student.get('streak', 0),
                    'total_points': student.get('total_points', 0),
                    'profile_picture': st_profile,
                    'redeemed_rewards': redeemed_count,
                    'active_this_week': active_this_week,
                    'year_level': student.get('year_level', ''),
                    'section': student.get('section', ''),
                })

            # Sort by total points descending and limit to 50
            top_students.sort(key=lambda x: x.get('total_points', 0), reverse=True)
            top_students = top_students[:50]

        # Get recent awards
        recent_awards = []
        if student_ids:
            recent_awards_resp = safe_execute(
                supabase.table('points')
                .select('student_id, points, point_category, received_at, note')
                .eq('teacher_id', user_id)
                .eq('status', 'approved')
                .in_('student_id', student_ids)
                .order('received_at', desc=True)
                .limit(10)
            )

            for award in recent_awards_resp.data if recent_awards_resp.data else []:
                student_id = award.get('student_id')
                
                # Get student name
                student_name = ''
                student_resp = safe_execute(
                    supabase.table('user_info')
                    .select('first_name, last_name')
                    .eq('id', student_id)
                )
                if student_resp.data and len(student_resp.data) > 0:
                    s = student_resp.data[0]
                    student_name = f"{s.get('first_name', '')} {s.get('last_name', '')}".strip()

                # Get student profile picture
                profile_picture = ''
                pic_resp = safe_execute(
                    supabase.table('profile_pictures')
                    .select('file_path')
                    .eq('user_id', student_id)
                    .order('uploaded_at', desc=True)
                    .limit(1)
                )
                if pic_resp.data and len(pic_resp.data) > 0:
                    profile_picture = pic_resp.data[0].get('file_path', '')

                # Clean up note
                raw_note = (award.get('note') or '').strip()
                note = raw_note
                if raw_note.lower().startswith('completed task:'):
                    note = raw_note[len('completed task:'):].strip()
                elif raw_note.startswith('Completed Task:'):
                    note = raw_note[len('Completed Task:'):].strip()

                recent_awards.append({
                    'student_id': student_id,
                    'student_name': student_name,
                    'profile_picture': profile_picture,
                    'points': award.get('points', 0),
                    'category': award.get('point_category', 'Task'),
                    'time': award.get('received_at', ''),
                    'note': note,
                })

        # Prepare final response
        response_data = {
            'id': user['id'],
            'name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            'gender': user.get('gender', ''),
            'section': user.get('section', ''),
            'year_level': user.get('year_level', ''),
            'subject': user.get('subject', ''),
            'role': user.get('role', ''),
            'profile_picture': profile_picture,
            'dashboard_stats': dashboard_stats,
            'students_count': len(top_students),
            'top_students': top_students,
            'recent_awards': recent_awards,
        }

        return jsonify(response_data), 200

    except Exception as e:
        # Log the error for debugging
        app.logger.error(f"Teacher dashboard error: {str(e)}")
        return jsonify({
            'error': 'Server error',
            'message': 'Unable to load dashboard data'
        }), 500
######################### TEACHER DASHBOARD ENDS ###############################################


@app.route('/teacher_notifications', methods=['GET'])
def get_teacher_notifications():
    """
    Fetch all notifications for a logged-in teacher.
    Returns: List of notifications with full sender names (NO Mr/Ms prefix)
    """
    teacher_id = request.args.get('teacher_id') or request.args.get('user_id')
    
    if not teacher_id:
        return jsonify({
            'success': False,
            'message': 'Missing teacher_id',
            'notifications': [],
            'unread_count': 0
        }), 400
    
    try:
        # ✅ Fetch notifications
        notif_resp = safe_execute(
            supabase.table('notifications')
            .select('notif_id, user_id, sender_id, title, message, notif_type, status, created_at')
            .eq('user_id', int(teacher_id))
            .order('created_at', desc=True)
            .limit(50)
        )
        
        notifications = notif_resp.data if notif_resp.data else []
        unread_count = sum(1 for n in notifications if (n.get('status') or '').lower() == 'unread')
        
        # ✅ Get sender info - FULL NAME ONLY (NO PREFIX)
        sender_ids = list(set([n.get('sender_id') for n in notifications if n.get('sender_id')]))
        sender_map = {}
        
        if sender_ids:
            sender_resp = safe_execute(
                supabase.table('user_info')
                .select('id, first_name, last_name')
                .in_('id', sender_ids)
            )
            
            for sender in sender_resp.data if sender_resp.data else []:
                sender_id = sender['id']
                # ✅ FULL NAME ONLY - NO Mr/Ms PREFIX
                first_name = sender.get('first_name', '').strip()
                last_name = sender.get('last_name', '').strip()
                full_name = f"{first_name} {last_name}".strip()
                
                # Get profile picture
                pic_resp = safe_execute(
                    supabase.table('profile_pictures')
                    .select('file_path')
                    .eq('user_id', sender_id)
                    .order('uploaded_at', desc=True)
                    .limit(1)
                )
                
                profile_pic = ''
                if pic_resp.data and len(pic_resp.data) > 0:
                    profile_pic = pic_resp.data[0].get('file_path', '')
                
                sender_map[sender_id] = {
                    'name': full_name,
                    'profile_picture': profile_pic
                }
        
        # ✅ Format response with full names
        formatted_notifications = []
        for notif in notifications:
            sender_id = notif.get('sender_id')
            sender_info = sender_map.get(sender_id, {'name': 'Unknown User', 'profile_picture': ''})
            
            formatted_notifications.append({
                'id': notif.get('notif_id'),
                'title': notif.get('title', ''),
                'message': notif.get('message', ''),
                'type': notif.get('notif_type', 'General'),
                'status': notif.get('status', 'Unread'),
                'created_at': notif.get('created_at'),
                'sender_id': sender_id,
                'sender_name': sender_info['name'],  # ✅ FULL NAME ONLY
                'sender_profile_picture': sender_info['profile_picture'],
            })
        
        return jsonify({
            'success': True,
            'notifications': formatted_notifications,
            'unread_count': unread_count
        }), 200
        
    except Exception as e:
        print(f"Error fetching teacher notifications: {e}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}',
            'notifications': [],
            'unread_count': 0
        }), 500


# ✅ ADD THIS ROUTE - Mark Notification as Read
@app.route('/mark_teacher_notification_read', methods=['POST'])
def mark_teacher_notification_read():
    """
    Mark a specific notification as read.
    Expects JSON: { "notif_id": 123 }
    """
    data = request.get_json()
    notif_id = data.get('notif_id')
    
    if not notif_id:
        return jsonify({'success': False, 'message': 'Missing notif_id'}), 400
    
    try:
        safe_execute(
            supabase.table('notifications')
            .update({'status': 'Read'})
            .eq('notif_id', int(notif_id))
        )
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ✅ ADD THIS ROUTE - Mark All Notifications as Read
@app.route('/mark_teacher_notifications_read', methods=['POST'])
def mark_teacher_notifications_read():
    """
    Mark all notifications as read for a teacher.
    Expects JSON: { "teacher_id": 123 }
    """
    data = request.get_json()
    teacher_id = data.get('teacher_id')
    
    if not teacher_id:
        return jsonify({'success': False, 'message': 'Missing teacher_id'}), 400
    
    try:
        safe_execute(
            supabase.table('notifications')
            .update({'status': 'Read'})
            .eq('user_id', int(teacher_id))
        )
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500





# --- TEACHER STUDENTS/ PAG DISPLAY PAGE ROUTE ---
@app.route('/students', methods=['GET'])
def api_student_list():
    teacher_id = session.get('user_id') or request.args.get('user_id')
    if not teacher_id or (not session.get('user_id') and not request.args.get('user_id')):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        # 1. Get all classrooms assigned to this teacher
        assignments_result = safe_execute(
            supabase.table('teacher_class_assignments')
            .select('grade_level, section')
            .eq('teacher_id', teacher_id)
        )
        assignments = assignments_result.data if assignments_result.data else []

        # Build unique classroom labels for dropdown
        classroom_labels = []
        seen = set()
        for a in assignments:
            label = f"Grade {a['grade_level']} - {a['section']}"
            if label not in seen:
                classroom_labels.append(label)
                seen.add(label)

        # 2. For each classroom, get all students in that grade_level and section
        students = []
        for assignment in assignments:
            grade_level = assignment.get('grade_level')
            section = assignment.get('section')
            if not grade_level or not section:
                continue
            students_result = safe_execute(
                supabase.table('user_info')
                .select('id, first_name, last_name, year_level, section, streak, total_points')
                .eq('role', 'Student')
                .eq('year_level', grade_level)
                .eq('section', section)
                .eq('status', 'Active')
            )
            if students_result and hasattr(students_result, 'data') and students_result.data:
                students.extend(students_result.data)

        # 3. Remove duplicates
        unique_students = {student['id']: student for student in students}.values()
        student_ids = [student['id'] for student in unique_students]

        # Get profile pictures
        pics_map = {}
        if student_ids:
            pics_result = safe_execute(
                supabase.table('profile_pictures')
                .select('user_id, file_path')
                .in_('user_id', student_ids)
            )
            if pics_result.data:
                for p in pics_result.data:
                    pics_map[p['user_id']] = p['file_path']

        # Get redeemed rewards count - FILTERED BY THIS TEACHER ONLY
        redeemed_map = {}
        if student_ids:
            redeemed_result = safe_execute(
                supabase.table('reward_redemptions')
                .select('student_id')
                .eq('teacher_id', teacher_id)
                .in_('student_id', student_ids)
            )
            if redeemed_result.data:
                for r in redeemed_result.data:
                    sid = r['student_id']
                    redeemed_map[sid] = redeemed_map.get(sid, 0) + 1

        # Build student list with all-time points from user_info
        student_list = []
        for student in unique_students:
            sid = student['id']
            profile_picture = pics_map.get(sid, '')
            redeemed_count = redeemed_map.get(sid, 0)
            streak = student.get('streak', 0)
            total_points = student.get('total_points', 0)  # <-- All-time points

            student_list.append({
                'id': sid,
                'name': f"{student.get('first_name', '')} {student.get('last_name', '')}",
                'grade': student.get('year_level', ''),
                'section': student.get('section', ''),
                'points': total_points,  # <-- All-time points from user_info
                'redeemed_rewards': redeemed_count,
                'profile_picture': profile_picture,
                'streak': streak,
                # ...add other fields as needed...
            })

        # Sort by points
        student_list.sort(key=lambda x: x['points'], reverse=True)

        return jsonify({
            'success': True,
            'students': student_list,
            'classrooms': classroom_labels,
        }), 200

    except Exception as e:
        print(f"Error in api_student_list: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/class-summary', methods=['GET'])
def api_class_summary():
    teacher_id = request.args.get('user_id') or session.get('user_id')
    if not teacher_id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    try:
        # 1. Get all classrooms assigned to this teacher
        assignments_result = safe_execute(
            supabase.table('teacher_class_assignments')
            .select('grade_level, section')
            .eq('teacher_id', teacher_id)
        )
        assignments = assignments_result.data if assignments_result.data else []

        # 2. Get all students in these classrooms
        students = []
        for assignment in assignments:
            grade_level = assignment.get('grade_level')
            section = assignment.get('section')
            if not grade_level or not section:
                continue
            student_result = safe_execute(
                supabase.table('user_info')
                .select('id, first_name, last_name, year_level, section')
                .eq('role', 'Student')
                .eq('year_level', grade_level)
                .eq('section', section)
                .eq('status', 'Active')
            )
            if student_result.data:
                students.extend(student_result.data)

        # Remove duplicates
        unique_students = {student['id']: student for student in students}.values()
        student_ids = [student['id'] for student in unique_students]

        # Get profile pictures
        pics_map = {}
        if student_ids:
            pics_result = safe_execute(
                supabase.table('profile_pictures')
                .select('user_id', 'file_path')
                .in_('user_id', student_ids)
            )
            if pics_result.data:
                for pic in pics_result.data:
                    pics_map[pic['user_id']] = pic['file_path']

        # Get total points for each student - FILTERED BY THIS TEACHER
        points_map = {}
        if student_ids:
            points_result = safe_execute(
                supabase.table('points')
                .select('student_id', 'points')
                .eq('teacher_id', teacher_id)
                .in_('student_id', student_ids)
            )
            if points_result.data:
                for row in points_result.data:
                    sid = row['student_id']
                    points_map[sid] = points_map.get(sid, 0) + row['points']

        # Prepare summary data
        student_list = []
        total_points = 0
        for student in unique_students:
            pic = pics_map.get(student['id'], '')
            points = points_map.get(student['id'], 0)
            total_points += points
            student_list.append({
                'id': student['id'],
                'name': f"{student['first_name']} {student['last_name']}",
                'grade': student['year_level'],
                'section': student['section'],
                'points': points,
                'profile_picture': pic,
            })

        # Sort by points descending
        student_list.sort(key=lambda x: x['points'], reverse=True)
        top_students = student_list[:5]
        avg_points = total_points / len(student_list) if student_list else 0

        # Participation calculation
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        participation = {
            'this_week': 0,
            'last_week': 0,
            'this_month': 0,
            'last_month': 0
        }

        # Count points using rolling periods
        if student_ids:
            # Get all points from last 2 weeks
            points_result = safe_execute(
                supabase.table('points')
                .select('student_id', 'received_at')
                .eq('teacher_id', teacher_id)
                .in_('student_id', student_ids)
                .gte('received_at', two_weeks_ago.isoformat())
            )
            if points_result.data:
                for row in points_result.data:
                    received_at = row['received_at']
                    try:
                        dt = datetime.fromisoformat(str(received_at).replace('Z', '+00:00'))
                    except Exception:
                        continue
                    if dt >= week_ago:
                        participation['this_week'] += 1
                    elif dt >= two_weeks_ago:
                        participation['last_week'] += 1

        # Month calculations (calendar months)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month = (start_of_month - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        if student_ids:
            points_month = safe_execute(
                supabase.table('points')
                .select('student_id', 'received_at')
                .eq('teacher_id', teacher_id)
                .in_('student_id', student_ids)
                .gte('received_at', start_of_month.isoformat())
            )
            participation['this_month'] = len(points_month.data) if points_month.data else 0

            points_last_month = safe_execute(
                supabase.table('points')
                .select('student_id', 'received_at')
                .eq('teacher_id', teacher_id)
                .in_('student_id', student_ids)
                .gte('received_at', last_month.isoformat())
                .lt('received_at', start_of_month.isoformat())
            )
            participation['last_month'] = len(points_last_month.data) if points_last_month.data else 0

        # Calculate percentages
        week_increase = 0
        if participation['last_week'] > 0:
            week_increase = min(round((participation['this_week'] - participation['last_week']) / participation['last_week'] * 100, 1), 100)
        elif participation['this_week'] > 0:
            week_increase = 100.0

        month_increase = 0
        if participation['last_month'] > 0:
            month_increase = min(round((participation['this_month'] - participation['last_month']) / participation['last_month'] * 100, 1), 100)
        elif participation['this_month'] > 0:
            month_increase = 100.0

        # Add week_increase to each top student
        for stu in top_students:
            stu['week_increase'] = round(week_increase, 1)

        return jsonify({
            'success': True,
            'class_summary': {
                'total_students': len(student_list),
                'average_points': round(avg_points, 2),
                'top_students': top_students,
                'participation': {
                    'this_week': participation['this_week'],
                    'last_week': participation['last_week'],
                    'week_increase': round(week_increase, 1),
                    'this_month': participation['this_month'],
                    'last_month': participation['last_month'],
                    'month_increase': round(month_increase, 1)
                }
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# --- EXPORT STUDENT SUMMARY TO EXCEL ROUTE --- 
@app.route('/export_student_summary', methods=['POST'])
def export_student_summary():
    """Export filtered student data to Excel with professional formatting"""
    try:
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
        if pd is None:
            return jsonify({'success': False, 'error': 'pandas not available'}), 500

        data = request.get_json() or {}
        teacher_id = data.get('teacher_id')
        filters = data.get('filters') or {}

        # Fetch students
        response = requests.get(
            f'{request.host_url.rstrip("/")}/students?user_id={teacher_id}'
        )
        if response.status_code != 200:
            return jsonify({'success': False, 'error': 'Failed to fetch students'}), 500

        data_resp = response.json()
        students = data_resp.get('students', [])

        # Apply filters
        search_q = filters.get('search', '').lower()
        classroom = filters.get('classroom')
        
        if search_q:
            students = [s for s in students if search_q in s.get('name', '').lower()]
        if classroom and classroom != 'Grade & Section':
            students = [s for s in students if f"Grade {s.get('grade')} - {s.get('section')}" == classroom]

        # Prepare Excel data - ✅ MATCHING EXACT FORMAT FROM IMAGE
        excel_data = []
        for s in students:
            excel_data.append({
                'Name': s.get('name', ''),
                'Grade': s.get('grade', ''),
                'Section': s.get('section', ''),
                'Points': s.get('points', 0),
                'Rewards Redeemed': s.get('redeemed_rewards', 0),
                'Last Activity': s.get('last_activity', 'N/A'),
                'Participation (%)': f"{s.get('participation_percent', 0):.1f}",
            })

        df = pd.DataFrame(excel_data)

        # Create Excel with professional formatting - ✅ EXACT FORMAT FROM IMAGE
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Write data starting at row 6 (to leave space for header info)
            df.to_excel(writer, sheet_name='Students', index=False, startrow=5)
            
            ws = writer.sheets['Students']
            
            # ===== ROW 1: Learn2Earn Title (NO BACKGROUND) =====
            ws['A1'] = 'Learn2Earn'
            ws['A1'].font = Font(name='Calibri', size=11, bold=False, color='000000')  # ✅ CHANGED: bold=False
            ws['A1'].fill = PatternFill()  # ✅ NO BACKGROUND COLOR
            ws['A1'].alignment = Alignment(horizontal='left', vertical='center')
            ws.row_dimensions[1].height = 28
            ws.merge_cells('A1:G1')
            
            # ===== ROW 2: School Name (NO BACKGROUND COLOR) =====
            ws['A2'] = 'Masico National High School'
            ws['A2'].font = Font(name='Calibri', size=11, bold=False, color='000000')
            ws['A2'].alignment = Alignment(horizontal='left', vertical='center')
            ws.row_dimensions[2].height = 16
            
            # ===== ROW 3: Date and Time (NO COLOR) =====
            now = datetime.now()
            date_str = now.strftime('%B %d, %Y at %I:%M %p')
            ws['A3'] = f'Student Report - {date_str}'
            ws['A3'].font = Font(name='Calibri', size=10, color='000000')  # ✅ BLACK TEXT
            ws['A3'].alignment = Alignment(horizontal='left', vertical='center')
            ws.row_dimensions[3].height = 14
            
            # ===== ROW 4: Empty row for spacing =====
            ws.row_dimensions[4].height = 8
            
            # ===== ROW 5: Empty row =====
            ws.row_dimensions[5].height = 0
            
            # ===== ROW 6: Blue Header Row with Column Names =====
            header_fill = PatternFill(start_color='7485E8', end_color='7485E8', fill_type='solid')  # ✅ CORRECT BLUE
            header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
            header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            
            thin_border = Border(
                left=Side(style='thin', color='D9D9D9'),
                right=Side(style='thin', color='D9D9D9'),
                top=Side(style='thin', color='D9D9D9'),
                bottom=Side(style='thin', color='D9D9D9')
            )
            
            # ✅ Set header row formatting
            for col_num, col_title in enumerate(['Name', 'Grade', 'Section', 'Points', 'Rewards Redeemed', 'Last Activity', 'Participation (%)'], 1):
                cell = ws.cell(row=6, column=col_num)
                cell.value = col_title
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_alignment
                cell.border = thin_border
            
            ws.row_dimensions[6].height = 20
            
            # ===== DATA ROWS: Format student data =====
            data_font = Font(name='Calibri', size=10, color='000000')
            data_alignment_center = Alignment(horizontal='center', vertical='center')
            data_alignment_left = Alignment(horizontal='left', vertical='center')
            
            for row in ws.iter_rows(min_row=7, max_row=ws.max_row, min_col=1, max_col=7):
                for col_num, cell in enumerate(row, 1):
                    cell.font = data_font
                    cell.border = thin_border
                    
                    # ✅ Left align for Name and Last Activity
                    if col_num in [1, 6]:
                        cell.alignment = data_alignment_left
                    else:
                        cell.alignment = data_alignment_center
                    
                    # ✅ Format numbers
                    if col_num in [4, 5]:  # Points, Rewards Redeemed
                        if isinstance(cell.value, (int, float)):
                            cell.number_format = '0'
            
            # ===== SET COLUMN WIDTHS - ✅ EXACT FROM IMAGE =====
            ws.column_dimensions['A'].width = 20  # Name
            ws.column_dimensions['B'].width = 8   # Grade
            ws.column_dimensions['C'].width = 12  # Section
            ws.column_dimensions['D'].width = 12  # Points
            ws.column_dimensions['E'].width = 18  # Rewards Redeemed
            ws.column_dimensions['F'].width = 28  # Last Activity
            ws.column_dimensions['G'].width = 18  # Participation (%)

        output.seek(0)
        
        # ✅ FILENAME FORMAT: Learn2Earn_Student_Report_2025-11-30
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"Learn2Earn_Student_Report_{date_str}.xlsx"

        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
       
        return jsonify({'success': False, 'error': str(e)}), 500


# --- SEND DISMISSAL FUNCTION IN STUDENT PAGE ROUTE ---
# --- SEND DISMISSAL FUNCTION IN STUDENT PAGE ROUTE (UPDATED WITH SMS) ---
@app.route('/send-dismissal', methods=['POST'])
def send_dismissal():
    data = request.get_json()
    user_id = session.get('user_id') or data.get('user_id')
    role = session.get('role') or data.get('role')
    if not user_id or role != 'Teacher':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    dismissal_time = data.get('dismissal_time')
    message = data.get('message', '')
    notify_email = data.get('notify_email')
    notify_sms = data.get('notify_sms')  # ✅ NEW: SMS notification flag
    grade = data.get('grade')
    section = data.get('section')
    student_id = data.get('student_id')
    if student_id in [None, '', 'None']:
        student_id = None

    # If "All Grade Level" or "All Section" is selected, treat as None
    if grade == 'All Grade Level':
        grade = None
    if section == 'All Section':
        section = None

    # ✅ Format time to AM/PM for display
    dismissal_time_formatted = dismissal_time
    try:
        dt = None
        try:
            dt = datetime.strptime(dismissal_time, "%H:%M")
        except Exception:
            try:
                dt = datetime.strptime(dismissal_time, "%I:%M %p")
            except Exception:
                dt = None
        if dt:
            dismissal_time_formatted = dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        dismissal_time_formatted = dismissal_time

    # Query students: if no grade/section/student_id, get all students handled by teacher
    students_query = supabase.table('user_info').select('id, first_name, last_name, year_level, section').eq('role', 'Student')
    if student_id is not None:
        students_query = students_query.eq('id', student_id)
    elif grade or section:
        if grade:
            students_query = students_query.eq('year_level', grade)
        if section:
            students_query = students_query.eq('section', section)
    else:
        # Get all students handled by teacher
        assignments = safe_execute(
            supabase.table('teacher_class_assignments')
            .select('grade_level', 'section')
            .eq('teacher_id', user_id)
        ).data or []
        student_ids = set()
        for a in assignments:
            grade_level = a.get('grade_level')
            section_val = a.get('section')
            students_result = safe_execute(
                supabase.table('user_info')
                .select('id')
                .eq('role', 'Student')
                .eq('year_level', grade_level)
                .eq('section', section_val)
            )
            if students_result and hasattr(students_result, 'data') and students_result.data:
                for s in students_result.data:
                    student_ids.add(s['id'])
        students_query = supabase.table('user_info').select('id, first_name, last_name, year_level, section').in_('id', list(student_ids))

    students_result = students_query.execute()
    students = students_result.data if students_result.data else []

    if not students:
        return jsonify({'success': False, 'message': 'No students found.'}), 404

    # ✅ Get teacher's name for notifications
    teacher_info = supabase.table('user_info').select('first_name, last_name', 'gender').eq('id', user_id).execute()
    teacher_name = ''
    if teacher_info.data and len(teacher_info.data) > 0:
        teacher_name = f"{teacher_info.data[0].get('first_name', '')} {teacher_info.data[0].get('last_name', '')}"

    # Prepare student IDs as both string and int for parent lookup
    student_ids_str = [str(s['id']).strip() for s in students]
    student_ids_int = []
    for sid in student_ids_str:
        try:
            student_ids_int.append(int(sid))
        except ValueError:
            pass

    # Query parents table for emails and phone numbers
    parents = []
    try:
        parents_result = supabase.table('parents').select('student_id, email, mobile_no, relationship, first_name, last_name').in_('student_id', student_ids_str).execute()
        parents = parents_result.data if parents_result.data else []
    except Exception as e:
        print(f"DEBUG: String query failed: {e}")

    if not parents and student_ids_int:
        try:
            parents_result = supabase.table('parents').select('student_id, email, mobile_no, relationship, first_name, last_name').in_('student_id', student_ids_int).execute()
            parents = parents_result.data if parents_result.data else []
        except Exception as e:
            print(f"DEBUG: Integer query failed: {e}")

    # Fallback: try individual queries for first 2 students if still no parents found
    if not parents:
        for student_id_str in student_ids_str[:2]:
            try:
                individual_result = supabase.table('parents').select('student_id, email, mobile_no, relationship, first_name, last_name').eq('student_id', student_id_str).execute()
                individual_parents = individual_result.data if individual_result.data else []
                if individual_parents:
                    parents.extend(individual_parents)
            except Exception as e:
                print(f"DEBUG: Individual query for {student_id_str} failed: {e}")

    # ✅ Map student_id to list of parent emails and phone numbers
    parent_email_map = {}
    parent_phone_map = {}
    for p in parents:
        sid = str(p['student_id']).strip()
        
        # Email mapping
        if p.get('email') and p['email'].strip():
            if sid not in parent_email_map:
                parent_email_map[sid] = []
            parent_email_map[sid].append({
                'email': p['email'].strip(),
                'name': f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                'relationship': p.get('relationship', 'Parent')
            })
        
        # Phone mapping
        if p.get('mobile_no') and p['mobile_no'].strip():
            if sid not in parent_phone_map:
                parent_phone_map[sid] = []
            parent_phone_map[sid].append({
                'phone': p['mobile_no'].strip(),
                'name': f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                'relationship': p.get('relationship', 'Parent')
            })

    sent_count = 0
    email_sent_count = 0
    sms_sent_count = 0
    students_without_parents = []
    email_failures = []
    sms_failures = []

    # ✅ Build base message
    base_message = "Dear Parent,\n\nThis is to inform you that your child, {student_name}, has been dismissed at {dismissal_time}.\n\nMasico National High School\nGrade: {grade} - Section: {section}"
    
    if message:
        base_message += f"\n\nNote: {message}"
    
    base_message += f"\n\nThank you,\nLearn2Earn\nTeacher: {teacher_name}"

    # ✅ SEND EMAIL NOTIFICATIONS
    if notify_email:
        for student in students:
            sid = str(student['id']).strip()
            parent_emails = parent_email_map.get(sid, [])
            
            if parent_emails:
                student_name = f"{student['first_name']} {student['last_name']}"
                grade_level = student.get('year_level', 'Unknown')
                section_name = student.get('section', 'Unknown')
                
                email_body = base_message.format(
                    student_name=student_name,
                    dismissal_time=dismissal_time_formatted,
                    grade=grade_level,
                    section=section_name
                )
                
                for parent in parent_emails:
                    subject = "Dismissal Notification"
                    msg = Message(subject, sender=app.config['MAIL_USERNAME'], recipients=[parent['email']])
                    msg.body = email_body
                    
                    try:
                        mail.send(msg)
                        email_sent_count += 1
                        sent_count += 1
                    except Exception as e:
                        app.logger.error(f"Failed to send dismissal email to {parent['email']}: {str(e)}")
                        email_failures.append(f"{student_name} - {parent['name']} ({parent['email']})")
            else:
                student_name = f"{student['first_name']} {student['last_name']}"
                if student_name not in students_without_parents:
                    students_without_parents.append(student_name)

    # ✅ SEND SMS NOTIFICATIONS
    if notify_sms:
        for student in students:
            sid = str(student['id']).strip()
            parent_phones = parent_phone_map.get(sid, [])
            
            if parent_phones:
                student_name = f"{student['first_name']} {student['last_name']}"
                grade_level = student.get('year_level', 'Unknown')
                section_name = student.get('section', 'Unknown')
                
                sms_message = base_message.format(
                    student_name=student_name,
                    dismissal_time=dismissal_time_formatted,
                    grade=grade_level,
                    section=section_name
                )
                
                for parent in parent_phones:
                    parent_number = parent['phone']
                    
                    # ✅ Convert to +63 format if needed
                    if parent_number and parent_number.startswith('0'):
                        parent_number = '+63' + parent_number[1:]
                    elif parent_number and not parent_number.startswith('+'):
                        parent_number = '+63' + parent_number
                    
                    # ✅ Only send if we have a valid phone number
                    if parent_number and len(parent_number) >= 12:
                        sms_result = send_sms_via_api(parent_number, sms_message, student['id'])
                        
                        if sms_result['success']:
                            sms_sent_count += 1
                            sent_count += 1
                        else:
                            sms_failures.append(f"{student_name} - {parent['name']} ({parent_number}): {sms_result['error']}")
                    else:
                        sms_failures.append(f"{student_name} - {parent['name']}: Invalid phone number format")
            else:
                student_name = f"{student['first_name']} {student['last_name']}"
                if student_name not in students_without_parents:
                    students_without_parents.append(student_name)

    # ✅ Build response message
    response_parts = []
    if notify_email:
        response_parts.append(f'Emails sent: {email_sent_count}')
    if notify_sms:
        response_parts.append(f'SMS sent: {sms_sent_count}')
    
    response_message = 'Dismissal notification sent! ' + ' | '.join(response_parts) if response_parts else 'Dismissal notification sent!'
    
    if students_without_parents:
        response_message += f' (Note: {len(students_without_parents)} students have no parent contact on file)'

    # ✅ Build result data with all details
    result_data = {
        'success': True,
        'sent_count': sent_count,
        'email_sent_count': email_sent_count,
        'sms_sent_count': sms_sent_count,
        'message': response_message,
        'students_without_contacts': students_without_parents
    }
    
    if email_failures:
        result_data['email_failures'] = email_failures
    if sms_failures:
        result_data['sms_failures'] = sms_failures

    return jsonify(result_data)


# ✅ SEND SMS VIA HTTPSMS API
def send_sms_via_api(phone_number, message, student_id):
    """Send SMS via HTTPSMS API"""
    HTTPSMS_API_KEY = "uk_2ublvy1otAtb3S-BQa9KZfIywUgGh6cXqc5ONgJb-fBRs9s8HU7ODFqO32qBEm7H"
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": HTTPSMS_API_KEY,
        "Accept": "application/json"
    }

    payload = {
        "content": message,
        "from": "+639761271972",  # ✅ Your registered number
        "to": phone_number
    }

    try:
        response = requests.post(
            "https://api.httpsms.com/v1/messages/send",
            headers=headers,
            json=payload,
            timeout=30
        )

        # ✅ Save to Supabase SMS log
        safe_execute(supabase.table('sms_messages').insert({
            "phone_number": phone_number,
            "message": message,
            "status": "sent" if response.status_code == 200 else "failed",
            "sent_at": datetime.now().isoformat(),
            "student_id": student_id,
            "message_type": "dismissal_notification",
            "response_data": json.dumps({
                "status_code": response.status_code,
                "response": response.text[:500]  # Limit response text
            })
        }))

        if response.status_code == 200:
            return {"success": True, "message": "SMS sent successfully"}
        else:
            return {"success": False, "error": f"HTTP {response.status_code}"}
            
    except Exception as e:
        # ✅ Log error to Supabase
        try:
            safe_execute(supabase.table('sms_messages').insert({
                "phone_number": phone_number,
                "message": message,
                "status": "failed",
                "sent_at": datetime.now().isoformat(),
                "student_id": student_id,
                "message_type": "dismissal_notification",
                "response_data": json.dumps({"error": str(e)[:200]})
            }))
        except Exception as log_e:
            print(f"Failed to log SMS error: {log_e}")
        
        return {"success": False, "error": str(e)[:100]}









# Download required NLTK data
nltk.download('vader_lexicon', quiet=True)
nltk.download('words', quiet=True)

# Load English word dictionary
ENGLISH_WORDS = set(words.words())

# Expanded content filtering lists with variations
SEXUAL_TERMS = {
    'sexual', 'sex', 'porn', 'porno', 'xxx', 'nude', 'naked', 'erotic', 'erotica',
    'fuck', 'fucking', 'fucker', 'shit', 'asshole', 'bitch', 'bastard', 'dick',
    'cock', 'pussy', 'whore', 'slut', 'cunt', 'nigga', 'nigger', 'fag', 'faggot',
    'dyke', 'tranny', 'retard', 'chink', 'spic', 'kike', 'penis', 'vagina', 'boobs',
    'boobies', 'tits', 'titties', 'breasts', 'anal', 'blowjob', 'handjob', 'masterbate',
    'masturbate', 'orgasm', 'cum', 'semen', 'ejaculate', 'horny', 'aroused'
}

RACIST_TERMS = {
    'nigger', 'nigga', 'chink', 'gook', 'spic', 'wetback', 'kike', 'heeb',
    'raghead', 'towelhead', 'cameljockey', 'sandnigger', 'beaner', 'coon',
    'darkie', 'porchmonkey', 'redskin', 'squaw', 'yellow', 'cracker', 'honky',
    'whitey', 'gyp', 'gypsy', 'jap', 'nip', 'mongoloid', 'oriental', 'ape'
}

HOMOPHOBIC_TERMS = {
    'fag', 'faggot', 'dyke', 'queer', 'homo', 'lesbo', 'tranny', 'shemale',
    'he-she', 'fruit', 'fairy', 'butch', 'femme', 'genderbender', 'it', 'thing'
}

PROFANITY_TERMS = {
    'fuck', 'shit', 'ass', 'asshole', 'bitch', 'bastard', 'dick', 'cock',
    'pussy', 'whore', 'slut', 'cunt', 'damn', 'hell', 'crap', 'piss',
    'dickhead', 'motherfucker', 'bullshit', 'bollocks', 'wanker', 'twat',
    'arse', 'arsehole', 'bugger', 'sod', 'bloody', 'git', 'screw', 'screwing'
}

# Common evasive spellings and variations
EVASIVE_SPELLINGS = {
    'fuck': ['phuck', 'fuk', 'f u c k', 'f*ck', 'f**k', 'f--k', 'f_u_c_k'],
    'shit': ['shyt', 'shet', 'sh!t', 'sh*t', 's**t', 's--t', 's_h_i_t'],
    'ass': ['azz', 'as$', 'a$$', 'a**', 'a--s', 'a_s_s'],
    'bitch': ['biatch', 'b!tch', 'b*tch', 'b**ch', 'b--ch', 'b_i_t_c_h'],
    'nigger': ['n!gger', 'n*gger', 'n**ger', 'n--ger', 'n_i_g_g_e_r', 'nigga'],
}

def normalize_text(text):
    """
    Normalize text by handling common evasion techniques
    """
    # Convert to lowercase
    text = text.lower()
    
    # Handle leetspeak substitutions
    leet_replacements = {
        '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's',
        '6': 'g', '7': 't', '8': 'b', '9': 'g', '@': 'a',
        '$': 's', '!': 'i', '+': 't'
    }
    
    for leet_char, normal_char in leet_replacements.items():
        text = text.replace(leet_char, normal_char)
    
    # Remove excessive spaces and special characters used as separators
    text = re.sub(r'[\-\_\*\~]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def contains_inappropriate_content(text):
    """
    Robust check for inappropriate content with multiple detection methods
    Returns (has_inappropriate, reason)
    """
    original_text = text
    text_lower = text.lower()
    normalized_text = normalize_text(text)
    
    # Method 1: Direct word matching
    all_restricted_terms = SEXUAL_TERMS | RACIST_TERMS | HOMOPHOBIC_TERMS | PROFANITY_TERMS
    
    # Check normalized text for direct matches
    words_in_normalized = set(re.findall(r'\b\w+\b', normalized_text))
    direct_matches = words_in_normalized.intersection(all_restricted_terms)
    
    if direct_matches:
        # Categorize the matches
        sexual_found = direct_matches.intersection(SEXUAL_TERMS)
        racist_found = direct_matches.intersection(RACIST_TERMS)
        homophobic_found = direct_matches.intersection(HOMOPHOBIC_TERMS)
        profanity_found = direct_matches.intersection(PROFANITY_TERMS)
        
        reasons = []
        if sexual_found:
            reasons.append(f"sexual content: {', '.join(sexual_found)}")
        if racist_found:
            reasons.append(f"racist content: {', '.join(racist_found)}")
        if homophobic_found:
            reasons.append(f"homophobic content: {', '.join(homophobic_found)}")
        if profanity_found:
            reasons.append(f"profanity: {', '.join(profanity_found)}")
        
        return True, f"Inappropriate content detected ({'; '.join(reasons)})"

    
    # Method 3: Character repetition detection (like "fffffuck")
    repetition_pattern = r'(\w)\1{2,}.*\b(fuck|shit|ass|bitch|nigger|fag)\b'
    if re.search(repetition_pattern, normalized_text):
        return True, "Disguised inappropriate content detected"
    
    # Method 4: Aggressive/harassment patterns
    aggressive_patterns = [
        r'\b(?:kill|die|hurt|harm)\s+(?:yourself|urself|u|you|them|him|her)\b',
        r'\b(?:go\s+)?(?:fuck|kill)\s+(?:yourself|off|urself)\b',
        r'\b(?:suck|lick)\s+my\s+(?:dick|cock|balls)\b',
        r'\b(?:beat|kick|punch)\s+(?:your|ur)\s+(?:ass|face|head)\b',
        r'\b(?:i\s+hope\s+you|wish\s+you)\s+(?:die|fail|suffer)\b',
        r'\b(?:you\s+should)\s+(?:die|kill yourself)\b',
    ]
    
    for pattern in aggressive_patterns:
        if re.search(pattern, normalized_text):
            return True, "Aggressive or harassing content detected"
    
    # Method 5: Check for word combinations that create inappropriate meanings
    inappropriate_combinations = [
        (r'\b(?:suck|blow)\b.*\b(?:dick|cock|penis)\b', "sexual content"),
        (r'\b(?:eat)\b.*\b(?:ass|pussy|cunt)\b', "sexual content"),
        (r'\b(?:fuck)\b.*\b(?:you|u|off)\b', "profanity"),
        (r'\b(?:stupid|dumb)\b.*\b(?:nigger|fag|dyke)\b', "discriminatory content"),
    ]
    
    for pattern, content_type in inappropriate_combinations:
        if re.search(pattern, normalized_text):
            return True, f"Inappropriate {content_type} detected"
    
    # Method 6: Check for excessive special characters trying to evade detection
    special_char_ratio = len(re.findall(r'[\*\-\_\~\+]', text)) / len(text) if text else 0
    if special_char_ratio > 0.3:  # More than 30% special characters
        # Check if it contains suspicious patterns even with special chars
        suspicious_with_chars = re.search(r'[fps][\*\-\_]*[uckh][\*\-\_]*[it]', normalized_text)
        if suspicious_with_chars:
            return True, "Suspicious content with evasion attempts detected"
    
    # Method 7: Check for space-separated inappropriate words (f u c k)
    space_separated = re.search(r'\b(f\s+u\s+c\s+k|s\s+h\s+i\s+t|a\s+s\s+s)\b', text_lower)
    if space_separated:
        return True, "Space-separated inappropriate content detected"
    
    return False, None

def is_valid_english_text(text):
    """
    Enhanced validation with robust content filtering
    Returns (is_valid, error_message)
    """
    # First check for inappropriate content with robust detection
    has_inappropriate, reason = contains_inappropriate_content(text)
    if has_inappropriate:
        return False, f"Content violates community guidelines: {reason}"
    
    # Remove punctuation and split into words
    cleaned_text = re.sub(r'[^\w\s]', '', text.lower())
    words_list = cleaned_text.split()
    
    # Check minimum word count
    if len(words_list) < 3:
        return False, "Feedback is too short. Please provide at least 3 words."
    
    # Check for excessive numbers
    number_count = sum(1 for word in words_list if word.isdigit())
    if number_count / len(words_list) > 0.3:
        return False, "Feedback contains too many numbers. Please use proper sentences."
    
    # Check for valid English words (at least 60% should be real words)
    valid_word_count = 0
    for word in words_list:
        # Skip very short words and numbers
        if len(word) <= 2 or word.isdigit():
            continue
        if word in ENGLISH_WORDS or word.endswith(('ing', 'ed', 'ly', 's', 'es')):
            valid_word_count += 1
    
    # Calculate percentage of valid words (excluding short words)
    significant_words = [w for w in words_list if len(w) > 2 and not w.isdigit()]
    if len(significant_words) == 0:
        return False, "Please provide meaningful feedback text."
    
    valid_percentage = valid_word_count / len(significant_words)
    
    if valid_percentage < 0.6:
        return False, "Feedback appears to contain invalid or gibberish text. Please use real English words."
    
    # Check for excessive character repetition (like "awfawfawf")
    if re.search(r'(.{3,})\1{2,}', text.lower()):
        return False, "Feedback contains repeated character patterns. Please use proper words."
    
    # Check for random keyboard mashing
    keyboard_mash_pattern = r'\b(?:asdf|jkl|qwert|zxcv|mnb)\w*\b'
    if len(re.findall(keyboard_mash_pattern, text.lower())) > 2:
        return False, "Feedback appears to contain random text. Please provide meaningful feedback."
    
    return True, None

def safe_execute(query):
    """
    Safely execute Supabase query with error handling
    """
    try:
        result = query.execute()
        if hasattr(result, 'error') and result.error:
            raise Exception(f"Supabase error: {result.error}")
        return result
    except Exception as e:
        raise Exception(f"Database operation failed: {str(e)}")

class FeedbackAnalyzer:
    def __init__(self):
        self.sia = SentimentIntensityAnalyzer()
        
        self.positive_messages = [
            "Fantastic work! Your teacher sees your effort paying off. Keep up this amazing momentum! 🌟",
            "You're doing brilliantly! Your hard work is truly shining through. Continue this excellent path! 💪",
            "Outstanding! Your dedication is clearly recognized. You're on the right track—keep going! ✨",
            "Wonderful progress! Your teacher is impressed, and so are we. Keep reaching for the stars! 🚀",
            "Excellent job! You're demonstrating real growth. Stay focused and keep achieving great things! 🎯",
            "Incredible achievement! Your commitment to excellence is paying off beautifully. Keep shining bright! ⭐",
            "Superb performance! You've exceeded expectations and shown true mastery. Continue this winning streak! 🏆",
            "Phenomenal work! Your teacher recognizes your exceptional effort. You're setting a great example for others! 🎓"
        ]
        
        self.neutral_messages = [
            "You're making progress! Every step forward counts. Keep pushing yourself—you've got this! 💫",
            "Good start! With a bit more effort, you'll see even better results. Believe in yourself! 🌱",
            "You're on the right path! Stay consistent and focused, and you'll reach your goals soon! 🎓",
            "Nice work so far! A little extra dedication will take you even further. Keep going! 📚",
            "You're doing okay! Remember, small improvements lead to big achievements. Keep trying! 🔑",
            "Steady progress is being made! Stay committed to your learning journey and success will follow! 🌟",
            "You're building a solid foundation! Keep refining your skills and you'll reach new heights! 🎯",
            "Decent effort shown! With more practice and focus, you'll unlock your full potential! 💡"
        ]
        
        self.negative_messages = [
            "I know you can do much better than this. Let's identify what went wrong and work on improving it together. 💪",
            "You have the potential to do great work. Take this as a learning moment and focus on how you can strengthen your next attempt. 🎯",
            "This result doesn't reflect your true ability. Let's figure out where you struggled and make a plan to improve. 🌱",
            "You're capable of more than what you've shown here. Review your work carefully and let's aim higher next time. 🚀",
            "Everyone has off days — what matters is how you bounce back. Take this feedback as a guide for your next improvement. 🌟",
            "Don't be discouraged! This is an opportunity to learn and grow stronger. Let's work on this together and improve! 💡",
            "Your potential is much greater than this result shows. Use this as motivation to push harder and prove what you can do! 🔥",
            "Challenges are stepping stones to success. Let's identify your weak spots and turn them into strengths! 🎓"
        ]
    
    def analyze_sentiment(self, feedback):
        scores = self.sia.polarity_scores(feedback)
        compound = scores['compound']
        
        # Adjusted thresholds for more nuanced classification
        if compound >= 0.05:
            sentiment = "Positive"
            sentiment_color = "success"
            motivation = random.choice(self.positive_messages)
        elif compound <= -0.05:
            sentiment = "Negative"
            sentiment_color = "danger"
            motivation = random.choice(self.negative_messages)
        else:
            sentiment = "Neutral"
            sentiment_color = "warning"
            motivation = random.choice(self.neutral_messages)
        
        return {
            'feedback': feedback,
            'sentiment': sentiment,
            'sentiment_color': sentiment_color,
            'scores': {
                'positive': round(scores['pos'], 3),
                'neutral': round(scores['neu'], 3),
                'negative': round(scores['neg'], 3),
                'compound': round(scores['compound'], 3)
            },
            'motivation': motivation
        }

analyzer = FeedbackAnalyzer()

# ============================================================================
# MOBILE-SPECIFIC ROUTES
# ============================================================================

@app.route('/api/mobile/analyze-feedback', methods=['POST'])
def mobile_analyze_feedback():
    """
    Mobile endpoint for feedback analysis with robust English fallback.
    """
    try:
        data = request.get_json()
        feedback = data.get('feedback', '').strip()
        student_name = data.get('student_name', '')
        student_id = data.get('student_id', '')

        if not feedback:
            return jsonify({'success': False, 'message': 'Feedback is required'}), 400

        # --- Language detection with fallback ---
        try:
            if len(feedback.split()) < 3:
                return jsonify({'success': False, 'message': 'Feedback is too short. Please provide at least 3 words.'}), 400
            lang = detect(feedback)
            print(f"[DEBUG analyze-feedback] Detected language: {lang}")
            if lang != 'en':
                # Fallback: Check if most words are English
                words_list = re.findall(r'\b[a-zA-Z]+\b', feedback)
                english_words = sum(1 for word in words_list if word.lower() in ENGLISH_WORDS)
                if words_list and english_words / len(words_list) >= 0.5:
                    pass  # Accept as English
                else:
                    return jsonify({'success': False, 'message': 'Please write your feedback in English.'}), 400
        except LangDetectException as e:
            # Fallback: Check if most words are English
            words_list = re.findall(r'\b[a-zA-Z]+\b', feedback)
            english_words = sum(1 for word in words_list if word.lower() in ENGLISH_WORDS)
            if words_list and english_words / len(words_list) >= 0.5:
                pass  # Accept as English
            else:
                return jsonify({'success': False, 'message': 'Please write your feedback in English.'}), 400

        # --- (Continue with your validation, sentiment analysis, etc.) ---
        # Example:
        is_valid, error_message = is_valid_english_text(feedback)
        if not is_valid:
            return jsonify({'success': False, 'message': error_message}), 400

        result = analyzer.analyze_sentiment(feedback)
        result['success'] = True
        result['student_name'] = student_name
        result['student_id'] = student_id
        result['timestamp'] = datetime.now().isoformat()
        return jsonify(result), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ✅ ADD THIS HELPER FUNCTION
def has_nlp_notification_this_week(student_id):
    """
    Check if student has received an NLP notification this week.
    Returns (has_notification, last_notification_date)
    """
    from datetime import datetime, timedelta, timezone
    
    now = datetime.now(timezone.utc)
    # Start of this week (Monday)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    
    try:
        result = safe_execute(
            supabase.table('nlp_notifications')
            .select('id, created_at')
            .eq('student_id', student_id)
            .gte('created_at', start_of_week.isoformat())
            .order('created_at', desc=True)
            .limit(1)
        )
        
        if result.data and len(result.data) > 0:
            notification = result.data[0]
            last_date = notification.get('created_at')
            return True, last_date
        
        return False, None
        
    except Exception as e:
        print(f"Error checking NLP notifications: {e}")
        return False, None

# ✅ MODIFY: /api/mobile/send-nlp-notification - ADD WEEKLY CHECK
@app.route('/api/mobile/send-nlp-notification', methods=['POST'])
def api_mobile_send_nlp_notification():
    """Mobile endpoint to send NLP feedback notification"""
    try:
        data = request.get_json()
        
        print(f"[DEBUG send-nlp] Received data: {data}")
        
        if not data:
            print("[DEBUG send-nlp] ERROR: No JSON data received")
            return jsonify({
                'success': False,
                'message': 'Request body is empty'
            }), 400
        
        teacher_id = data.get('teacher_id')
        student_id = data.get('student_id')
        feedback = data.get('feedback', '').strip()
        feedback_hidden = data.get('feedback_hidden', False)

        print(f"[DEBUG send-nlp] teacher_id={teacher_id}, student_id={student_id}, feedback='{feedback[:50] if feedback else '[HIDDEN]'}...', feedback_hidden={feedback_hidden}")

        if not teacher_id or not student_id:
            print(f"[DEBUG send-nlp] ERROR: Missing required fields - teacher_id={teacher_id}, student_id={student_id}")
            return jsonify({
                'success': False,
                'message': 'Missing teacher_id or student_id'
            }), 400

        # ✅ NEW: CHECK IF STUDENT ALREADY HAS NOTIFICATION THIS WEEK
        has_notif, last_notif_date = has_nlp_notification_this_week(student_id)
        if has_notif:
            print(f"[DEBUG send-nlp] BLOCKED: Student already has notification this week (sent: {last_notif_date})")
            return jsonify({
                'success': False,
                'message': 'Student already received a notification this week. Try again next week!',
                'error_type': 'weekly_limit_reached',
                'last_notification_date': last_notif_date
            }), 429  # 429 = Too Many Requests

        # ✅ FIXED: Allow empty feedback if feedback_hidden=True
        if not feedback_hidden and not feedback:
            print(f"[DEBUG send-nlp] ERROR: Feedback is required when feedback_hidden=False")
            return jsonify({
                'success': False,
                'message': 'Feedback required'
            }), 400

        # ✅ Validate feedback content (only if not hidden)
        if feedback and not feedback_hidden:
            is_valid, error_message = is_valid_english_text(feedback)
            print(f"[DEBUG send-nlp] Validation: is_valid={is_valid}, error={error_message}")
            
            if not is_valid:
                print(f"[DEBUG send-nlp] ERROR: Validation failed - {error_message}")
                return jsonify({
                    'success': False,
                    'message': error_message
                }), 400

            # ✅ Check for inappropriate content
            has_inappropriate, reason = contains_inappropriate_content(feedback)
            print(f"[DEBUG send-nlp] Content check: has_inappropriate={has_inappropriate}, reason={reason}")
            
            if has_inappropriate:
                print(f"[DEBUG send-nlp] ERROR: Inappropriate content - {reason}")
                return jsonify({
                    'success': False,
                    'message': f'Content violates community guidelines: {reason}'
                }), 400

        # ✅ Analyze sentiment (works for all sentiments: positive, negative, neutral)
        analysis_result = analyzer.analyze_sentiment(feedback if feedback else "Good job")
        print(f"[DEBUG send-nlp] Analysis: sentiment={analysis_result['sentiment']}")
        
        sentiment = analysis_result['sentiment']
        sentiment_color = analysis_result['sentiment_color']
        scores = analysis_result['scores']
        motivation = analysis_result['motivation']

        # ✅ Store in database - works for ALL sentiments
        try:
            print(f"[DEBUG send-nlp] Inserting to database...")
            insert_result = safe_execute(
                supabase.table('nlp_notifications').insert({
                    'teacher_id': int(teacher_id),
                    'student_id': int(student_id),
                    'feedback': feedback if not feedback_hidden else '',
                    'sentiment': sentiment,
                    'sentiment_col': sentiment_color,
                    'positive_score': float(scores['positive']),
                    'negative_score': float(scores['negative']),
                    'neutral_score': float(scores['neutral']),
                    'compound_score': float(scores['compound']),
                    'motivation': motivation,
                    'feedback_hidden': feedback_hidden,
                    'status': 'Unread',
                    'created_at': datetime.now().isoformat()
                })
            )

            print(f"[DEBUG send-nlp] SUCCESS: Insert result: {insert_result.data}")
            return jsonify({
                'success': True,
                'message': 'Notification sent successfully',
                'sentiment': sentiment,
                'feedback_hidden': feedback_hidden
            }), 200

        except Exception as db_error:
            print(f"[DEBUG send-nlp] DATABASE ERROR: {str(db_error)}")
         
            app.logger.error(f"Database error in send_nlp_notification: {str(db_error)}")
            return jsonify({
                'success': False,
                'message': f'Failed to save notification: {str(db_error)}'
            }), 500

    except Exception as e:
        print(f"[CRITICAL ERROR send-nlp] {str(e)}")
      
        app.logger.error(f"Error in api_mobile_send_nlp_notification: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e),
            'error_type': 'server_error'
        }), 500

# ✅ NEW ENDPOINT: CHECK IF NOTES BUTTON SHOULD BE DISABLED
@app.route('/api/mobile/check-nlp-limit', methods=['GET'])
def api_mobile_check_nlp_limit():
    """
    Check if student has already received NLP notification this week.
    Returns whether Notes button should be disabled.
    Query params: student_id
    """
    try:
        student_id = request.args.get('student_id')
        
        if not student_id:
            return jsonify({
                'success': False,
                'message': 'Missing student_id'
            }), 400

        has_notif, last_notif_date = has_nlp_notification_this_week(student_id)
        
        return jsonify({
            'success': True,
            'has_notification_this_week': has_notif,
            'last_notification_date': last_notif_date,
            'button_disabled': has_notif,
            'message': 'Student already received notification this week' if has_notif else 'No notification sent this week'
        }), 200

    except Exception as e:
        print(f"Error checking NLP limit: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# ✅ GET NLP NOTIFICATIONS FOR STUDENT (Mobile)
@app.route('/api/mobile/nlp-notifications', methods=['GET'])
def api_mobile_get_nlp_notifications():
    """Get NLP notifications for student"""
    try:
        student_id = request.args.get('student_id')
        limit = request.args.get('limit', 10, type=int)
        
        if not student_id:
            return jsonify({
                'success': False,
                'notifications': [],
                'message': 'Student ID is required'
            }), 400

        # ✅ Fetch notifications
        result = safe_execute(
            supabase.table('nlp_notifications')
            .select('*')
            .eq('student_id', student_id)
            .order('created_at', desc=True)
            .limit(limit)
        )

        notifications = result.data if result.data else []

        return jsonify({
            'success': True,
            'notifications': notifications,
            'total_count': len(notifications)
        }), 200

    except Exception as e:
        app.logger.error(f"Error fetching notifications: {str(e)}")
        return jsonify({
            'success': False,
            'notifications': [],
            'message': str(e)
        }), 500

# ✅ MARK NOTIFICATION AS READ (Mobile)
@app.route('/api/mobile/nlp-notifications/<notification_id>/read', methods=['POST'])
def api_mobile_mark_notification_read(notification_id):
    """Mark notification as read"""
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        
        if not student_id:
            return jsonify({
                'success': False,
                'message': 'Student ID is required'
            }), 400

        # ✅ Update notification status
        safe_execute(
            supabase.table('nlp_notifications')
            .update({
                'status': 'Read', 
                'read_at': datetime.now().isoformat()
            })
            .eq('id', notification_id)
            .eq('student_id', student_id)
        )

        return jsonify({
            'success': True,
            'message': 'Notification marked as read'
        }), 200

    except Exception as e:
        app.logger.error(f"Error marking notification as read: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# ✅ DELETE NOTIFICATION (Mobile)
@app.route('/api/mobile/nlp-notifications/<notification_id>', methods=['DELETE'])
def api_mobile_delete_notification(notification_id):
    """Delete a notification"""
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        
        if not student_id:
            return jsonify({
                'success': False,
                'message': 'Student ID is required'
            }), 400

        # ✅ Delete notification
        safe_execute(
            supabase.table('nlp_notifications')
            .delete()
            .eq('id', notification_id)
            .eq('student_id', student_id)
        )

        return jsonify({
            'success': True,
            'message': 'Notification deleted'
        }), 200

    except Exception as e:
        app.logger.error(f"Error deleting notification: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# ✅ TEST NLP ANALYSIS (Mobile) - for debugging
@app.route('/api/mobile/test-nlp', methods=['POST'])
def api_mobile_test_nlp():
    """Test NLP analysis without storing"""
    try:
        data = request.get_json()
        feedback = data.get('feedback', '').strip()

        if not feedback:
            return jsonify({
                'success': False,
                'message': 'Feedback is required'
            }), 400

        # ✅ Validate feedback
        is_valid, error_message = is_valid_english_text(feedback)
        if not is_valid:
            return jsonify({
                'success': False,
                'message': error_message,
                'error_type': 'validation'
            }), 400

        # ✅ Check inappropriate content
        has_inappropriate, reason = contains_inappropriate_content(feedback)
        if has_inappropriate:
            return jsonify({
                'success': False,
                'message': f'Content violates guidelines: {reason}',
                'error_type': 'inappropriate_content'
            }), 400

        # ✅ Analyze sentiment
        result = analyzer.analyze_sentiment(feedback)

        return jsonify({
            'success': True,
            'analysis': result
        }), 200

    except Exception as e:
        app.logger.error(f"Error in test_nlp: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/api/mobile/send-nlp-notification-old', methods=['POST'])
def mobile_send_nlp_notification_old():
    """
    Mobile endpoint for sending NLP notifications
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': 'No data provided'
            }), 400

        # Extract data with validation
        teacher_id = data.get('teacher_id')
        student_id = data.get('student_id')
        feedback = data.get('feedback', '')
        sentiment = data.get('sentiment', '')
        sentiment_color = data.get('sentiment_color', '')
        positive_score = data.get('positive_score')
        negative_score = data.get('negative_score')
        neutral_score = data.get('neutral_score')
        compound_score = data.get('compound_score')
        motivation = data.get('motivation', '')
        feedback_hidden = data.get('feedback_hidden', False)

        # Validate required fields
        if not teacher_id or not student_id:
            return jsonify({
                'success': False,
                'message': 'Teacher ID and Student ID are required'
            }), 400

        # Insert into nlp_notifications table
        try:
            result = safe_execute(supabase.table('nlp_notifications').insert({
                'teacher_id': teacher_id,
                'student_id': student_id,
                'feedback': feedback,
                'sentiment': sentiment,
                'sentiment_col': sentiment_color,
                'positive_score': positive_score,
                'negative_score': negative_score,
                'neutral_score': neutral_score,
                'compound_score': compound_score,
                'motivation': motivation,
                'feedback_hidden': feedback_hidden,
                'source': 'mobile'  # Track that this came from mobile
            }))
            
            return jsonify({
                'success': True,
                'message': 'Notification sent successfully',
                'notification_id': result.data[0]['id'] if result.data else None
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Database operation failed: {str(e)}'
            }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}'
        }), 500

@app.route('/api/mobile/nlp-notifications/<int:notif_id>/read-old', methods=['POST'])
def mobile_mark_notification_read_old(notif_id):
    """
    Mobile endpoint for marking notification as read
    """
    try:
        result = safe_execute(supabase.table('nlp_notifications')
            .update({'status': 'Read', 'read_at': datetime.now().isoformat()})
            .eq('id', notif_id)
            .execute())
        
        return jsonify({
            'success': True,
            'message': 'Notification marked as read'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}'
        }), 500

@app.route('/api/mobile/test-content-filter', methods=['POST'])
def mobile_test_content_filter():
    """
    Mobile endpoint to test content filtering with various test cases
    """
    try:
        data = request.get_json()
        test_cases = data.get('test_cases', [])
        
        if not test_cases:
            return jsonify({
                'success': False,
                'message': 'No test cases provided'
            }), 400

        results = []
        for test_case in test_cases:
            is_valid, validation_message = is_valid_english_text(test_case)
            has_inappropriate, inappropriate_reason = contains_inappropriate_content(test_case)
            
            results.append({
                'text': test_case,
                'is_valid': is_valid,
                'validation_message': validation_message,
                'has_inappropriate': has_inappropriate,
                'inappropriate_reason': inappropriate_reason
            })
        
        return jsonify({
            'success': True,
            'results': results
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}'
        }), 500

@app.route('/api/mobile/teacher-stats', methods=['GET'])
def mobile_teacher_stats():
    """
    Mobile endpoint to get teacher statistics for NLP usage
    """
    try:
        teacher_id = request.args.get('teacher_id')
        
        if not teacher_id:
            return jsonify({
                'success': False,
                'message': 'Teacher ID is required'
            }), 400

        # Get notification count by sentiment
        try:
            result = safe_execute(supabase.table('nlp_notifications')
                .select('sentiment')
                .eq('teacher_id', teacher_id)
                .execute())
            
            notifications = result.data if result.data else []
            
            # Count by sentiment
            sentiment_count = {
                'Positive': 0,
                'Neutral': 0,
                'Negative': 0,
                'Total': len(notifications)
            }
            
            for notification in notifications:
                sentiment = notification.get('sentiment', 'Neutral')
                if sentiment in sentiment_count:
                    sentiment_count[sentiment] += 1
            
            # Get recent notifications (last 7 days)
            one_week_ago = (datetime.now() - timedelta(days=7)).isoformat()
            recent_result = safe_execute(supabase.table('nlp_notifications')
                .select('*')
                .eq('teacher_id', teacher_id)
                .gte('created_at', one_week_ago)
                .execute())
            
            recent_notifications = recent_result.data if recent_result.data else []
            
            return jsonify({
                'success': True,
                'stats': {
                    'sentiment_distribution': sentiment_count,
                    'recent_count': len(recent_notifications),
                    'total_count': len(notifications)
                }
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Database error: {str(e)}'
            }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}'
        }), 500

# Health check endpoint for mobile
@app.route('/api/mobile/health', methods=['GET'])
def mobile_health_check():
    """
    Health check endpoint for mobile app
    """
    return jsonify({
        'success': True,
        'message': 'NLP Feedback API is running',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

# Error handler for mobile
@app.errorhandler(404)
def mobile_not_found(error):
    return jsonify({
        'success': False,
        'message': 'Endpoint not found'
    }), 404

@app.errorhandler(500)
def mobile_server_error(error):
    return jsonify({
        'success': False,
        'message': 'Internal server error'
    }), 500

# ============================================================================
# ORIGINAL WEB ENDPOINTS (for backward compatibility)
# ============================================================================

@app.route('/analyze', methods=['POST'])
def analyze():
    """Original web endpoint for feedback analysis"""
    data = request.get_json()
    feedback = data.get('feedback', '').strip()
    
    if not feedback:
        return jsonify({'error': 'Please enter teacher feedback'}), 400

    # Language detection: Only allow English
    try:
        if len(feedback.split()) < 3:
            return jsonify({'error': 'Feedback too short for language detection. Please provide at least 3 words.'}), 400
            
        lang = detect(feedback)
        if lang != 'en':
            return jsonify({'error': 'Please enter feedback in English only.'}), 400
    except LangDetectException:
        # Fallback: Check if most words are English
        words_list = re.findall(r'\b[a-zA-Z]+\b', feedback)
        if words_list:
            english_words = sum(1 for word in words_list if word.lower() in ENGLISH_WORDS)
            if english_words / len(words_list) < 0.5:
                return jsonify({'error': 'Please enter feedback in English only.'}), 400

    # Validate text content with robust filtering
    is_valid, error_message = is_valid_english_text(feedback)
    if not is_valid:
        return jsonify({'error': error_message}), 400

    result = analyzer.analyze_sentiment(feedback)
    
    # PSYCHOLOGICALLY SAFE APPROACH:
    # Hide raw teacher feedback for Neutral/Negative sentiments
    if result['sentiment'] in ['Neutral', 'Negative']:
        result['raw_feedback'] = result['feedback']  # Keep for admin/teacher view
        result['feedback'] = None  # Hide from student view
        result['feedback_hidden'] = True
    else:
        result['feedback_hidden'] = False
    
    return jsonify(result)

@app.route('/api/nlp-notification', methods=['POST'])
def api_nlp_notification():
    """Original web endpoint for NLP notifications"""
    if 'user_id' not in session or session.get('role') != 'Teacher':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.get_json()
    teacher_id = session['user_id']
    student_id = data.get('student_id')
    feedback = data.get('feedback', '')
    sentiment = data.get('sentiment', '')
    sentiment_col = data.get('sentiment_color', '')
    positive_score = data.get('positive_score')
    negative_score = data.get('negative_score')
    neutral_score = data.get('neutral_score')
    compound_score = data.get('compound_score')
    motivation = data.get('motivation', '')
    feedback_hidden = data.get('feedback_hidden', False)

    # Insert into nlp_notifications table - ✅ REMOVED 'source' field
    try:
        result = safe_execute(supabase.table('nlp_notifications').insert({
            'teacher_id': teacher_id,
            'student_id': student_id,
            'feedback': feedback,
            'sentiment': sentiment,
            'sentiment_col': sentiment_col,
            'positive_score': positive_score,
            'negative_score': negative_score,
            'neutral_score': neutral_score,
            'compound_score': compound_score,
            'motivation': motivation,
            'feedback_hidden': feedback_hidden,
            'status': 'Unread'
            # ✅ REMOVED: 'source': 'web'
        }))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500









# --- TEACHER REWARDS PAGE DISPLAY ROUTE ---
@app.route('/teacher_rewards', methods=['GET'])
def teacher_rewards():
    teacher_id = request.args.get('user_id')
    if not teacher_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        rewards_resp = safe_execute(
            supabase.table('rewards')
            .select('reward_id, reward_name, description, point_cost, available_quantity, category, status, created_at, grade_level, section')
            .eq('created_by', teacher_id)  # <--- THIS FILTER
            .order('created_at', desc=True)
        )
        rewards = rewards_resp.data if rewards_resp and rewards_resp.data else []

        # Format for frontend
        rewards_list = []
        for r in rewards:
            rewards_list.append({
                'id': r.get('reward_id'),
                'name': r.get('reward_name', ''),
                'description': r.get('description', ''),
                'points': r.get('point_cost', 0),
                'quantity': r.get('available_quantity', 0),
                'category': r.get('category', ''),
                'status': r.get('status', ''),
                'created_at': r.get('created_at', ''),
                'grade_level': r.get('grade_level', ''),
                'section': r.get('section', ''),
            })

        return jsonify({'success': True, 'rewards': rewards_list}), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



# --- TEACHER ADD REWARDS IN REWARDS PAGE ROUTE ---
@app.route('/add_reward', methods=['POST'])
def add_reward():
    data = request.get_json()
    teacher_id = data.get('created_by')
    reward_name = data.get('reward_name')
    description = data.get('description', '')
    point_cost = data.get('point_cost')
    available_quantity = data.get('available_quantity')
    category = data.get('category')
    grade_level = data.get('grade_level', '')
    section = data.get('section', '')

    if not teacher_id or not reward_name or not point_cost or not available_quantity or not category:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    try:
        # If All Grades or All Sections, insert as one row with array values
        if (not grade_level or grade_level == '' or str(grade_level).lower() == 'all grades') or \
        (not section or section == '' or str(section).lower() == 'all sections'):
            # Get all classrooms assigned to this teacher
            assignments = safe_execute(
                supabase.table('teacher_class_assignments')
                .select('grade_level, section')
                .eq('teacher_id', teacher_id)
            ).data or []

            # Convert grade_levels to int, sections to str
            grade_levels = sorted({int(a.get('grade_level')) for a in assignments if a.get('grade_level') is not None})
            sections = sorted({str(a.get('section')) for a in assignments if a.get('section') is not None})

            # Insert as one row with array values
            resp = safe_execute(
                supabase.table('rewards').insert({
                    'reward_name': reward_name,
                    'description': description,
                    'point_cost': int(point_cost),
                    'available_quantity': int(available_quantity),
                    'category': category,
                    'status': 'Available',
                    'created_at': datetime.now().isoformat(),
                    'created_by': int(teacher_id),
                    'grade_level': grade_levels,  # int[]
                    'section': sections,          # text[]
                })
            )
            # ...rest of your code...
            reward_id = None
            if resp.data and len(resp.data) > 0:
                reward_id = resp.data[0].get('reward_id')

            # Activity log
            safe_execute(supabase.table('admin_activity_log').insert({
                'user_id': int(teacher_id),
                'user_role': 'Teacher',
                'action': 'Create Reward',
                'activity': 'Rewards Management',
                'description': f"Created reward: {reward_name} (Cost: {point_cost} pts, Qty: {available_quantity}) for Grades {grade_levels} Sections {sections}",
                'details': '',
            }))

            # Notify all students in these classrooms
            students_query = supabase.table('user_info').select('id').eq('role', 'Student').in_('year_level', grade_levels).in_('section', sections)
            students_result = students_query.execute()
            students = students_result.data if students_result.data else []

            notif_title = "New Reward Available"
            notif_message = f"Your teacher has added a new reward: {reward_name} ({point_cost} pts, Qty: {available_quantity}). Check the rewards page!"

            for student in students:
                supabase.table('notifications').insert({
                    'user_id': student['id'],
                    'sender_id': teacher_id,
                    'title': notif_title,
                    'message': notif_message,
                    'notif_type': 'Reward',
                    'status': 'Unread',
                    'reward_id': reward_id
                }).execute()

            # Notify teacher for confirmation
            supabase.table('notifications').insert({
                'user_id': teacher_id,
                'sender_id': teacher_id,
                'title': "New Reward Created",
                'message': f"You have created a new reward: {reward_name} ({point_cost} pts, Qty: {available_quantity}) for all assigned classrooms.",
                'notif_type': 'Reward',
                'status': 'Unread',
                'reward_id': reward_id
            }).execute()

            return jsonify({'success': True, 'message': 'Reward added for all assigned classrooms (indexed)'}), 200

        # Normal single insert
        resp = safe_execute(
            supabase.table('rewards').insert({
                'reward_name': reward_name,
                'description': description,
                'point_cost': int(point_cost),
                'available_quantity': int(available_quantity),
                'category': category,
                'status': 'Available',
                'created_at': datetime.now().isoformat(),
                'created_by': int(teacher_id),
                'grade_level': grade_level,
                'section': section,
            })
        )
        reward_id = None
        if resp.data and len(resp.data) > 0:
            reward_id = resp.data[0].get('reward_id')

        # Activity log
        safe_execute(supabase.table('admin_activity_log').insert({
            'user_id': int(teacher_id),
            'user_role': 'Teacher',
            'action': 'Create Reward',
            'activity': 'Rewards Management',
            'description': f"Created reward: {reward_name} (Cost: {point_cost} pts, Qty: {available_quantity})",
            'details': '',
        }))

        # Notify students in selected classroom
        students_query = supabase.table('user_info').select('id').eq('role', 'Student')
        if grade_level:
            students_query = students_query.eq('year_level', grade_level)
        if section:
            students_query = students_query.eq('section', section)
        students_result = students_query.execute()
        students = students_result.data if students_result.data else []

        notif_title = "New Reward Available"
        notif_message = f"Your teacher has added a new reward: {reward_name} ({point_cost} pts, Qty: {available_quantity}). Check the rewards page!"

        for student in students:
            supabase.table('notifications').insert({
                'user_id': student['id'],
                'sender_id': teacher_id,
                'title': notif_title,
                'message': notif_message,
                'notif_type': 'Reward',
                'status': 'Unread',
                'reward_id': reward_id
            }).execute()

        # Notify teacher for confirmation
        supabase.table('notifications').insert({
            'user_id': teacher_id,
            'sender_id': teacher_id,
            'title': "New Reward Created",
            'message': f"You have created a new reward: {reward_name} ({point_cost} pts, Qty: {available_quantity})",
            'notif_type': 'Reward',
            'status': 'Unread',
            'reward_id': reward_id
        }).execute()

        return jsonify({'success': True, 'message': 'Reward added successfully'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500




# --- TEACHER REWARDS PAGE TO EDIT AND DELIST REWARDS ROUTE ---
@app.route('/teacher_edit_rewards/<int:reward_id>', methods=['PUT'])
def update_reward(reward_id):
    try:
        data = request.get_json() or {}
        # teacher id can come from payload or session
        teacher_id = data.get('user_id') or session.get('user_id')
        if not teacher_id:
            return jsonify({'success': False, 'message': 'Unauthorized access (missing user_id)'}), 401
        try:
            teacher_id = int(teacher_id)
        except Exception:
            return jsonify({'success': False, 'message': 'Invalid user_id'}), 400

        # Verify reward exists and belongs to teacher
        check_result = safe_execute(
            supabase.table('rewards')
            .select('*')
            .eq('reward_id', reward_id)
            .eq('created_by', teacher_id)
        )
        if not check_result.data or len(check_result.data) == 0:
            return jsonify({'success': False, 'message': 'Reward not found or unauthorized'}), 404

        reward = check_result.data[0]
        prev_quantity = int(reward.get('available_quantity', 0) or 0)

        # Determine if this is a status-only update (order-independent)
        keys = {str(k).lower() for k in data.keys()}
        status_val = data.get('status')
        status_norm = str(status_val).strip().lower() if status_val is not None else None
        if keys == {'user_id', 'status'} and status_norm in {'available', 'unavailable'}:
            update_data = {'status': 'Available' if status_norm == 'available' else 'Unavailable'}
        else:
            # Full update -> validate required fields (removed 'status' from required fields)
            required_fields = ['reward_name', 'point_cost', 'available_quantity', 'category']
            missing = [f for f in required_fields if f not in data]
            if missing:
                return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing)}'}), 400

            # safe parsing / type conversion
            try:
                point_cost = int(data.get('point_cost') or 0)
            except Exception:
                return jsonify({'success': False, 'message': 'Invalid point_cost'}), 400
            try:
                available_quantity = int(data.get('available_quantity') or 0)
            except Exception:
                return jsonify({'success': False, 'message': 'Invalid available_quantity'}), 400

            update_data = {
                'reward_name': data.get('reward_name'),
                'description': data.get('description', ''),
                'point_cost': point_cost,
                'available_quantity': available_quantity,
                'category': data.get('category'),
                # Status is NOT included in full update - only in status-only updates
            }

            # optional: allow updating grade_level / section if provided
            if 'grade_level' in data:
                update_data['grade_level'] = data.get('grade_level')
            if 'section' in data:
                update_data['section'] = data.get('section')

        # perform update
        result = safe_execute(
            supabase.table('rewards')
            .update(update_data)
            .eq('reward_id', reward_id)
        )

        if not result.data or len(result.data) == 0:
            return jsonify({'success': False, 'message': 'Update failed'}), 500

        # activity log
        safe_execute(
            supabase.table('admin_activity_log').insert({
                'user_id': teacher_id,
                'user_role': 'Teacher',
                'action': 'Edit Reward',
                'activity': 'Rewards Management',
                'description': f"Edited reward: {data.get('reward_name', reward.get('reward_name',''))}",
                'details': f"Fields updated: {', '.join(update_data.keys())}",
            })
        )

        updated = result.data[0]
        reward_info = {
            'id': updated.get('reward_id'),
            'reward_id': updated.get('reward_id'),
            'reward_name': updated.get('reward_name'),
            'description': updated.get('description', ''),
            'point_cost': updated.get('point_cost'),
            'available_quantity': updated.get('available_quantity'),
            'category': updated.get('category'),
            'status': updated.get('status'),  # Keep this for response, but it won't be updated in full edit
            'created_at': updated.get('created_at'),
            'created_by': updated.get('created_by')
        }

        return jsonify({
            'success': True,
            'message': 'Reward updated successfully!',
            'reward': reward_info
        }), 200

    except Exception as e:
        print(f"Error updating reward: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500



# --- TEACHER REWARDS PAGE PARA SA REWARD REDEEMED OVERVIEW ROUTE ---
@app.route('/rewards_redeemed_overview', methods=['GET'])
def rewards_redeemed_overview():
    teacher_id = request.args.get('user_id') or session.get('user_id')
    if not teacher_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        # 1. Get all rewards created by this teacher
        rewards_resp = safe_execute(
            supabase.table('rewards')
            .select('reward_id, reward_name, category, point_cost')
            .eq('created_by', teacher_id)
        )
        rewards = rewards_resp.data if rewards_resp.data else []
        reward_map = {r['reward_id']: r for r in rewards}

        # 2. Get all redemptions for these rewards, filter out "Used"
        reward_ids = list(reward_map.keys())
        if not reward_ids:
            return jsonify({'success': True, 'overview': []}), 200

        redemptions_resp = safe_execute(
            supabase.table('reward_redemptions')
            .select('redemption_id, student_id, reward_id, processed_at, points_deducted, status')
            .in_('reward_id', reward_ids)
            .order('processed_at', desc=True)
        )
        # FILTER OUT USED REWARDS HERE
        redemptions = [
            r for r in (redemptions_resp.data if redemptions_resp.data else [])
            if r.get('status', '').lower() != 'used'
        ]

        # 3. Get all involved student info
        student_ids = list({r['student_id'] for r in redemptions})
        students_resp = safe_execute(
            supabase.table('user_info')
            .select('id, first_name, last_name, year_level, section')
            .in_('id', student_ids)
        )
        students = students_resp.data if students_resp.data else []
        student_map = {s['id']: s for s in students}

        # 4. Get profile pictures
        pics_resp = safe_execute(
            supabase.table('profile_pictures')
            .select('user_id, file_path')
            .in_('user_id', student_ids)
        )
        pics_map = {p['user_id']: p['file_path'] for p in pics_resp.data} if pics_resp.data else {}

        # 5. Group by student (for overview)
        overview = {}
        for r in redemptions:
            sid = r['student_id']
            student = student_map.get(sid, {})
            if not student:
                continue
            key = f"{student.get('year_level', '')}-{student.get('section', '')}-{sid}"
            if key not in overview:
                overview[key] = {
                    'student_id': sid,
                    'student_name': f"{student.get('first_name', '')} {student.get('last_name', '')}",
                    'grade': student.get('year_level', ''),
                    'section': student.get('section', ''),
                    'profile_picture': pics_map.get(sid, ''),
                    'rewards': []
                }
            reward = reward_map.get(r['reward_id'], {})
            overview[key]['rewards'].append({
                'redemption_id': r.get('redemption_id', 0),
                'reward_name': reward.get('reward_name', ''),
                'category': reward.get('category', ''),
                'points': r.get('points_deducted', 0),
                'date': r.get('processed_at', ''),
            })

        # 6. Convert to list and sort by grade/section/student
        overview_list = list(overview.values())
        overview_list.sort(key=lambda x: (x['grade'], x['section'], x['student_name']))

        return jsonify({'success': True, 'overview': overview_list}), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# --- TEACHER REWARD PAGE USE BUTTON ROUTE ---
@app.route('/use_reward_redemptions/<int:redemption_id>/use', methods=['POST'])
def use_reward_redemption(redemption_id):
    """
    Mark a reward redemption as Used.
    Expects JSON body: { "notes": "optional notes" }
    """
    data = request.get_json() or {}
    notes = data.get('notes', '')
    used_at = datetime.now(UTC).isoformat()

    try:
        result = supabase.table('reward_redemptions').update({
            'status': 'Used',
            'notes': notes,
            'used_at': used_at
        }).eq('redemption_id', redemption_id).execute()

        if hasattr(result, 'error') and result.error:
            raise Exception(result.error.message)

        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"use_reward_redemption error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500



# --- TEACHER REWARD REDEMPTION HISTORY PAGE ROUTE ---
@app.route('/teacher_reward_redemption_history', methods=['GET'])
def teacher_redemption_history():
    """
    Aggregated stats + redemptions for a teacher's rewards.
    Returns only redemptions made by students assigned to the teacher's classrooms.
    Also returns 'classrooms' (list of {grade, section, label}) for frontend dropdowns.
    Optional debug: ?debug=1 includes debug arrays.
    Query params: teacher_id or user_id
    """
    teacher_id_raw = request.args.get('teacher_id') or request.args.get('user_id')
    debug_mode = str(request.args.get('debug') or '').lower() in ['1', 'true', 'yes']

    if not teacher_id_raw:
        return jsonify({'success': False, 'error': 'Missing teacher_id'}), 400

    try:
        teacher_id = int(teacher_id_raw)
    except Exception:
        return jsonify({'success': False, 'error': 'Invalid teacher_id'}), 400

    debug_info = {
        'rewards_count': 0,
        'redemptions_fetched_count': 0,
        'assignments': [],
        'referenced_student_ids': [],
        'allowed_student_ids': [],
        'filtered_redemptions_count': 0,
    }

    try:
        # --- 0) teacher classrooms (assignments) ---
        assignments_resp = safe_execute(
            supabase.table('teacher_class_assignments')
            .select('grade_level, section')
            .eq('teacher_id', teacher_id)
        )
        assignments = assignments_resp.data if getattr(assignments_resp, 'data', None) else []
        debug_info['assignments'] = assignments

        # build classroom objects for frontend
        classrooms = []
        seen = set()
        for a in assignments:
            gy = str(a.get('grade_level', '')).strip()
            ss = str(a.get('section', '')).strip()
            if not gy or not ss:
                continue
            key = (gy, ss)
            if key in seen:
                continue
            seen.add(key)
            classrooms.append({'grade': gy, 'section': ss, 'label': f'Grade {gy} - {ss}'})

        # --- 1) rewards created by this teacher ---
        rewards_resp = safe_execute(
            supabase.table('rewards')
            .select('reward_id, reward_name, category, description')
            .eq('created_by', teacher_id)
        )
        reward_rows = rewards_resp.data if getattr(rewards_resp, 'data', None) else []
        reward_map = {r['reward_id']: r for r in reward_rows}
        reward_ids = list(reward_map.keys())
        debug_info['rewards_count'] = len(reward_rows)

        if not reward_ids:
            resp = {
                'success': True,
                'total_redemptions': 0,
                'points_redeemed': 0,
                'students_redeemed': 0,
                'this_week_redemptions': 0,
                'redemptions': [],
                'classrooms': classrooms
            }
            if debug_mode:
                resp['debug'] = debug_info
            return jsonify(resp), 200

        # --- 2) fetch redemptions for those rewards (most recent first) ---
        redemptions_resp = safe_execute(
            supabase.table('reward_redemptions')
            .select('redemption_id, reward_id, student_id, points_deducted, status, processed_at, used_at, notes, remarks')
            .in_('reward_id', reward_ids)
            .order('processed_at', desc=True)
        )
        redemptions_rows = redemptions_resp.data if getattr(redemptions_resp, 'data', None) else []
        debug_info['redemptions_fetched_count'] = len(redemptions_rows)

        # --- 3) determine allowed students: only those in teacher's assignments ---
        allowed_student_ids = set()
        referenced_student_ids = list({r.get('student_id') for r in redemptions_rows if r.get('student_id') is not None})
        debug_info['referenced_student_ids'] = referenced_student_ids

        if assignments and referenced_student_ids:
            students_resp = safe_execute(
                supabase.table('user_info')
                .select('id, year_level, section, first_name, last_name')
                .in_('id', referenced_student_ids)
                .eq('role', 'Student')
            )
            student_rows = students_resp.data if getattr(students_resp, 'data', None) else []

            # compare normalized grade/section values
            for s in student_rows:
                sid = s.get('id')
                sy = str(s.get('year_level', '')).strip()
                ss = str(s.get('section', '')).strip()
                for a in assignments:
                    ay = str(a.get('grade_level', '')).strip()
                    asn = str(a.get('section', '')).strip()
                    # match tolerant to leading zeros/spaces
                    if sy == ay and ss == asn:
                        allowed_student_ids.add(sid)
                        break

        debug_info['allowed_student_ids'] = list(allowed_student_ids)

        # --- 4) filter redemptions to only allowed students ---
        if allowed_student_ids:
            filtered_redemptions = [r for r in redemptions_rows if r.get('student_id') in allowed_student_ids]
        else:
            filtered_redemptions = []

        debug_info['filtered_redemptions_count'] = len(filtered_redemptions)

        # --- 5) compute stats from filtered redemptions ---
        total_redemptions = len(filtered_redemptions)
        points_redeemed = 0
        student_id_set = set()
        for r in filtered_redemptions:
            pts = r.get('points_deducted') or 0
            try:
                pts = int(pts)
            except Exception:
                try:
                    pts = int(float(pts))
                except Exception:
                    pts = 0
            points_redeemed += pts
            sid = r.get('student_id')
            if sid is not None:
                student_id_set.add(sid)

        # this-week count
        now_utc = datetime.now(UTC)
        week_ago = now_utc - timedelta(days=7)
        this_week_count = 0
        for r in filtered_redemptions:
            processed_at = r.get('processed_at')
            if not processed_at:
                continue
            try:
                dt = parser.parse(str(processed_at))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                else:
                    dt = dt.astimezone(UTC)
                if dt >= week_ago:
                    this_week_count += 1
            except Exception:
                continue

        # --- 6) fetch student details + latest profile pictures ---
        students_map = {}
        pics_map = {}
        if student_id_set:
            students_resp = safe_execute(
                supabase.table('user_info')
                .select('id, first_name, last_name, year_level, section')
                .in_('id', list(student_id_set))
            )
            for s in (students_resp.data if getattr(students_resp, 'data', None) else []):
                students_map[s['id']] = s

            pics_resp = safe_execute(
                supabase.table('profile_pictures')
                .select('user_id, file_path, uploaded_at')
                .in_('user_id', list(student_id_set))
                .order('uploaded_at', desc=True)
            )
            if getattr(pics_resp, 'data', None):
                for p in pics_resp.data:
                    uid = p.get('user_id')
                    if uid not in pics_map:
                        pics_map[uid] = p.get('file_path', '')

        # --- 7) build output redemptions list (Manila local date/time), include used_at/date/time ---
        out = []
        manila_tz = timezone('Asia/Manila')
        for r in filtered_redemptions:
            rid = r.get('redemption_id')
            reward_id = r.get('reward_id')
            reward = reward_map.get(reward_id, {})
            sid = r.get('student_id')
            student = students_map.get(sid, {}) or {}

            # processed_at -> date/time + ISO UTC
            processed_at = r.get('processed_at')
            date_str = ''
            time_str = ''
            processed_iso = processed_at
            try:
                dt = parser.parse(str(processed_at))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                dt_utc = dt.astimezone(UTC)
                dt_manila = dt.astimezone(manila_tz)
                date_str = dt_manila.strftime('%Y-%m-%d')
                time_str = dt_manila.strftime('%I:%M %p')
                processed_iso = dt_utc.isoformat()
            except Exception:
                date_str = str(processed_at)[:10] if processed_at else ''
                time_str = ''
                processed_iso = processed_at

            # used_at -> date/time + ISO UTC (may be empty)
            used_at_raw = r.get('used_at') or ''
            used_iso = used_at_raw
            used_date_str = ''
            used_time_str = ''
            if used_at_raw:
                try:
                    du = parser.parse(str(used_at_raw))
                    if du.tzinfo is None:
                        du = du.replace(tzinfo=UTC)
                    du_utc = du.astimezone(UTC)
                    du_manila = du.astimezone(manila_tz)
                    used_date_str = du_manila.strftime('%Y-%m-%d')
                    used_time_str = du_manila.strftime('%I:%M %p')
                    used_iso = du_utc.isoformat()
                except Exception:
                    used_date_str = str(used_at_raw)[:10]
                    used_time_str = ''

            pts = r.get('points_deducted') or 0
            try:
                pts = int(pts)
            except Exception:
                try:
                    pts = int(float(pts))
                except Exception:
                    pts = 0

            out.append({
                'redemption_id': rid,
                'reward_id': reward_id,
                'reward_name': reward.get('reward_name') or '',
                'category': reward.get('category') or '',
                'description': reward.get('description') or '',
                'points': pts,
                'status': r.get('status') or '',
                'processed_at': processed_iso,
                'date': date_str,
                'time': time_str,
                'used_at': used_iso,
                'used_date': used_date_str,
                'used_time': used_time_str,
                'student_id': sid,
                'student_name': f"{student.get('first_name','')} {student.get('last_name','')}".strip(),
                'grade': student.get('year_level') or '',
                'section': student.get('section') or '',
                'profile_picture': pics_map.get(sid, '') or '',
                'notes': r.get('notes') or '',
                'remarks': r.get('remarks') or ''
            })

        response = {
            'success': True,
            'total_redemptions': total_redemptions,
            'points_redeemed': points_redeemed,
            'students_redeemed': len(student_id_set),
            'this_week_redemptions': this_week_count,
            'redemptions': out,
            'classrooms': classrooms
        }

        if debug_mode:
            response['debug'] = debug_info
            print(f"[DEBUG teacher_reward_redemption_history] teacher_id={teacher_id} debug={debug_info}")

        return jsonify(response), 200

    except Exception as e:
        print(f"Error in teacher_reward_redemption_history: {e}")
        if debug_mode:
            return jsonify({'success': False, 'error': str(e), 'debug': debug_info}), 500
        return jsonify({'success': False, 'error': str(e)}), 500



# --- TEACHER REWARD EXPORT REDEMPTIONS EXCEL ROUTE ---
import io
try:
    import pandas as pd
except Exception:
    pd = None

@app.route('/export_redemptions', methods=['POST'])
def export_redemptions():
    """
    Export redemptions to Excel with optional summary statistics block.
    """
    try:
        import io
        from openpyxl.styles import Font, Alignment
        from openpyxl.utils import get_column_letter
        if pd is None:
            return jsonify({'success': False, 'error': 'Pandas not installed on server'}), 500

        data = request.get_json() or {}
        teacher_id = data.get('teacher_id') or data.get('user_id')
        if not teacher_id:
            return jsonify({'success': False, 'error': 'Missing teacher_id'}), 400
        try:
            teacher_id = int(teacher_id)
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid teacher_id'}), 400

        only_filtered = str(data.get('only_filtered') or data.get('onlyFiltered') or '0').lower() in ['1', 'true', 'yes']
        include_summary = str(data.get('include_summary') or data.get('includeSummary') or '0').lower() in ['1', 'true', 'yes']
        filters = data.get('filters') or {}

        # Get rewards created by this teacher
        rewards_resp = safe_execute(
            supabase.table('rewards')
            .select('reward_id, reward_name, category, description')
            .eq('created_by', teacher_id)
        )
        reward_rows = rewards_resp.data if getattr(rewards_resp, 'data', None) else []
        reward_map = {r['reward_id']: r for r in reward_rows}
        reward_ids = list(reward_map.keys())

        out = []
        if reward_ids:
            redemptions_resp = safe_execute(
                supabase.table('reward_redemptions')
                .select('redemption_id, reward_id, student_id, points_deducted, status, processed_at, used_at, notes, remarks')
                .in_('reward_id', reward_ids)
                .order('processed_at', desc=True)
            )
            rows = redemptions_resp.data if getattr(redemptions_resp, 'data', None) else []

            # fetch student info + latest profile pictures
            student_ids = list({r.get('student_id') for r in rows if r.get('student_id')})
            students_map = {}
            pics_map = {}
            if student_ids:
                students_resp = safe_execute(
                    supabase.table('user_info')
                    .select('id, first_name, last_name, year_level, section')
                    .in_('id', student_ids)
                )
                for s in (students_resp.data if getattr(students_resp, 'data', None) else []):
                    students_map[s['id']] = s

                pics_resp = safe_execute(
                    supabase.table('profile_pictures')
                    .select('user_id, file_path, uploaded_at')
                    .in_('user_id', student_ids)
                    .order('uploaded_at', desc=True)
                )
                if getattr(pics_resp, 'data', None):
                    for p in pics_resp.data:
                        uid = p.get('user_id')
                        if uid not in pics_map:
                            pics_map[uid] = p.get('file_path', '')

            manila_tz = timezone('Asia/Manila')
            for r in rows:
                sid = r.get('student_id')
                student = students_map.get(sid, {}) or {}

                # processed date/time (manila)
                processed_at = r.get('processed_at') or ''
                p_date_disp = ''
                p_time_disp = ''
                try:
                    dt = parser.parse(str(processed_at))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    dt_manila = dt.astimezone(manila_tz)
                    p_date_disp = dt_manila.strftime('%b %d, %Y')    # e.g. Oct 26, 2025
                    p_time_disp = dt_manila.strftime('%I:%M:%S %p')  # e.g. 7:51:31 PM
                except Exception:
                    p_date_disp = (str(processed_at)[:10] if processed_at else '')
                    p_time_disp = ''

                # used at display
                used_at_raw = r.get('used_at') or ''
                used_disp = ''
                try:
                    if used_at_raw:
                        du = parser.parse(str(used_at_raw))
                        if du.tzinfo is None:
                            du = du.replace(tzinfo=UTC)
                        du_manila = du.astimezone(manila_tz)
                        used_disp = f"{du_manila.strftime('%b %d, %Y')} {du_manila.strftime('%I:%M:%S %p')}"
                    else:
                        used_disp = '-'
                except Exception:
                    used_disp = (str(used_at_raw)[:19] if used_at_raw else '-')

                reward = reward_map.get(r.get('reward_id'), {})
                pts = r.get('points_deducted') or 0
                try:
                    pts = int(pts)
                except Exception:
                    try:
                        pts = int(float(pts))
                    except Exception:
                        pts = 0

                out.append({
                    'Student Name': f"{student.get('first_name','')} {student.get('last_name','')}".strip(),
                    'Grade': student.get('year_level') or '',
                    'Section': student.get('section') or '',
                    'Reward': reward.get('reward_name') or '',
                    'Category': reward.get('category') or '',
                    'Points Used': pts,
                    'Status': r.get('status') or '',
                    'Date': p_date_disp,
                    'Time': p_time_disp,
                    'Used At': used_disp,
                    'Notes': r.get('notes') or (r.get('remarks') or '') or '-'
                })

            # Apply simple filters server-side if requested
            def matches_filters(rec):
                cls = filters.get('classroom') or ''
                if cls and cls not in ['All Grade and Section', 'All Classrooms', '', None]:
                    if cls != f"Grade {rec.get('Grade')} - {rec.get('Section')}":
                        return False
                cat = filters.get('category') or ''
                if cat and cat not in ['All Categories', '', None] and rec.get('Category') != cat:
                    return False
                st = filters.get('status') or ''
                if st and st not in ['All Status', '', None] and rec.get('Status') != st:
                    return False
                s = (filters.get('search') or '').strip().lower()
                if s:
                    if s not in str(rec.get('Student Name','')).lower() and s not in str(rec.get('Reward','')).lower():
                        return False
                return True

            if only_filtered and filters:
                out = [r for r in out if matches_filters(r)]

        # Build DataFrame with fixed column order
        cols = ['Student Name','Grade','Section','Reward','Category','Points Used','Status','Date','Time','Used At','Notes']
        df_export = pd.DataFrame.from_records(out, columns=cols)

        # Prepare summary statistics if requested
        summary = {}
        if include_summary:
            total_redemptions = len(out)
            total_points = sum([int(r.get('Points Used') or 0) for r in out]) if out else 0
            unique_students = len(set([r.get('Student Name') for r in out])) if out else 0
            avg_points = round(total_points / total_redemptions, 1) if total_redemptions else 0
            used_count = sum(1 for r in out if str(r.get('Status','')).lower() == 'used')
            unused_count = total_redemptions - used_count
            summary = {
                'Total Redemptions': total_redemptions,
                'Total Points Redeemed': total_points,
                'Unique Students': unique_students,
                'Average Points': avg_points,
                'Used Redemptions': used_count,
                'Unused Redemptions': unused_count
            }

        # Create Excel with header/title block and optional summary
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            sheet_name = 'Redemption History'
            # decide start row for the data table (pandas startrow is zero-based)
            # if summary is included, compute startrow so there's one blank row
            # between the summary block and the table header
            if include_summary and summary:
                summary_count = len(summary)
                # summary title is written at Excel row 5, summary rows start at row 6
                last_summary_row = 5 + summary_count
                # leave one blank row after the summary, then table header
                header_excel_row = last_summary_row + 2
                startrow = header_excel_row - 1  # pandas startrow is zero-based
            else:
                startrow = 4
            df_export.to_excel(writer, index=False, startrow=startrow, sheet_name=sheet_name)
            wb = writer.book
            ws = writer.sheets[sheet_name]

            # Header/title rows (rows 1-3)
            date_time_str = datetime.now().strftime('%B %d, %Y at %I:%M %p')
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(cols))
            ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(cols))
            ws.cell(row=1, column=1, value='Learn2Earn').font = Font(size=14, bold=True)
            ws.cell(row=2, column=1, value='Masico National High School').font = Font(size=11, bold=False)
            ws.cell(row=3, column=1, value=f'Reward Redemption History Report - {date_time_str}').font = Font(size=10, bold=False)
            for r in (1,2,3):
                ws.cell(row=r, column=1).alignment = Alignment(horizontal='left')

            # If requested, write summary block between header and table
            if include_summary and summary:
                ws.cell(row=5, column=1, value='SUMMARY STATISTICS').font = Font(bold=True)
                row_idx = 6
                for k, v in summary.items():
                    ws.cell(row=row_idx, column=1, value=f"{k}:")
                    ws.cell(row=row_idx, column=2, value=str(v))
                    row_idx += 1

            # Adjust column widths
            for i, col in enumerate(cols, start=1):
                max_len = max(
                    df_export[col].astype(str).map(len).max() if not df_export.empty else 10,
                    len(col)
                ) + 4
                ws.column_dimensions[get_column_letter(i)].width = min(max_len, 40)

            # make header row bold (header row is startrow+1 in Excel)
            header_row = startrow + 1
            for col_idx in range(1, len(cols)+1):
                cell = ws.cell(row=header_row, column=col_idx)
                cell.font = Font(bold=True)

        output.seek(0)
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"Learn2Earn_Redemption_History_{date_str}.xlsx"

        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        import traceback
        print('export_redemptions error:', traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500
    



# --- TEACHER AWARD POINTS PAGE DISPLAY CLASSROOMS AND STUDENTS ROUTE ---
@app.route('/teacher_award_points', methods=['GET'])
def teacher_award_points():
    """
    Returns classrooms, students and top_students for a teacher.
    Query param: user_id (teacher id) or uses session user_id.
    """
    teacher_id = request.args.get('user_id') or session.get('user_id')
    if not teacher_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        # 1) Get teacher assignments (classrooms)
        assignments_resp = safe_execute(
            supabase.table('teacher_class_assignments')
            .select('grade_level, section')
            .eq('teacher_id', teacher_id)
        )
        assignments = assignments_resp.data if getattr(assignments_resp, 'data', None) else []

        # Build unique classroom labels
        classroom_labels = []
        seen = set()
        for a in assignments:
            gy = a.get('grade_level')
            ss = a.get('section')
            if gy is None or ss is None:
                continue
            label = f"Grade {gy} - {ss}"
            if label not in seen:
                seen.add(label)
                classroom_labels.append(label)

        # 2) Fetch students for each assigned classroom
        students = []
        for a in assignments:
            gy = a.get('grade_level')
            ss = a.get('section')
            if gy is None or ss is None:
                continue
            students_resp = safe_execute(
                supabase.table('user_info')
                .select('id, first_name, last_name, year_level, section, total_points, streak')
                .eq('role', 'Student')
                .eq('year_level', gy)
                .eq('section', ss)
                .eq('status', 'Active')
            )
            if getattr(students_resp, 'data', None):
                students.extend(students_resp.data)

        # 3) Deduplicate students by id and normalize fields
        unique_map = {}
        for s in students:
            try:
                sid = int(s.get('id'))
            except Exception:
                continue
            if sid in unique_map:
                continue

            # latest profile picture
            pic = ''
            try:
                pic_resp = safe_execute(
                    supabase.table('profile_pictures')
                    .select('file_path')
                    .eq('user_id', sid)
                    .order('uploaded_at', desc=True)
                    .limit(1)
                )
                if getattr(pic_resp, 'data', None) and len(pic_resp.data) > 0:
                    pic = pic_resp.data[0].get('file_path', '') or ''
            except Exception:
                pic = ''

            # normalize numeric fields
            try:
                total_points = int(s.get('total_points') or 0)
            except Exception:
                total_points = 0
            try:
                streak = int(s.get('streak') or 0)
            except Exception:
                streak = 0

            unique_map[sid] = {
                'id': sid,
                'first_name': s.get('first_name', '') or '',
                'last_name': s.get('last_name', '') or '',
                'year_level': s.get('year_level', '') or '',
                'section': s.get('section', '') or '',
                'total_points': total_points,
                'streak': streak,
                'profile_picture': pic,
            }

        student_list = list(unique_map.values())

        # 4) Build top_students sorted by total_points desc (limit 5)
        # Build top_students sorted by total_points desc (NO LIMIT)
        top_students = sorted(student_list, key=lambda x: x.get('total_points', 0), reverse=True)

        return jsonify({
            'success': True,
            'classrooms': classroom_labels,
            'students': student_list,
            'top_students': top_students
        }), 200

    except Exception as e:
        import traceback
        print('teacher_award_points ERROR:', traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500



# --- TEACHER AWARD POINTS PAG CLICK NG AWARD BTN ROUTE ---
@app.route('/teacher_add_award_points', methods=['GET', 'POST'])
def teacher_add_award_points():
    try:
        # --- GET: if only teacher_id provided -> return classrooms + students ---
        if request.method == 'GET':
            teacher_id = request.args.get('teacher_id') or request.args.get('user_id')
            # If no teacher id provided -> unauthorized
            if not teacher_id:
                return jsonify({'success': False, 'message': 'Missing teacher_id'}), 401

            # Return classrooms and students for this teacher
            try:
                assignments_result = safe_execute(
                    supabase.table('teacher_class_assignments')
                    .select('grade_level, section')
                    .eq('teacher_id', teacher_id)
                )
                assignments = assignments_result.data if getattr(assignments_result, 'data', None) else []

                # Build unique classroom labels
                classroom_labels = []
                seen = set()
                for a in assignments:
                    gy = a.get('grade_level')
                    ss = a.get('section')
                    if gy is None or ss is None:
                        continue
                    label = f"Grade {gy} - {ss}"
                    if label not in seen:
                        seen.add(label)
                        classroom_labels.append(label)

                # Fetch students for each assigned classroom
                students = []
                for a in assignments:
                    gy = a.get('grade_level')
                    ss = a.get('section')
                    if gy is None or ss is None:
                        continue
                    students_resp = safe_execute(
                        supabase.table('user_info')
                        .select('id, first_name, last_name, year_level, section')
                        .eq('role', 'Student')
                        .eq('year_level', gy)
                        .eq('section', ss)
                        .eq('status', 'Active')
                    )
                    if getattr(students_resp, 'data', None):
                        students.extend(students_resp.data)

                # remove duplicates by id
                unique_students = {s['id']: s for s in students}.values()

                return jsonify({
                    'success': True,
                    'classrooms': classroom_labels,
                    'students': list(unique_students)
                }), 200
            except Exception as e:
                print(f"Error in teacher_add_award_points GET: {e}")
                return jsonify({'success': False, 'message': str(e)}), 500

        # --- POST: perform award (existing behavior) ---
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400

        teacher_id = data.get('teacher_id')
        student_id = data.get('student_id')
        points = data.get('points')
        point_category = data.get('category')
        note = data.get('note', '')

        # Validation
        if not student_id or not points or not point_category or not teacher_id:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400

        teacher_id = int(teacher_id)
        student_id = int(student_id)
        points = int(points)

        philippines_tz = pytz.timezone('Asia/Manila')
        now_ph = datetime.now(philippines_tz).isoformat()

        # Get student name for activity log
        student_info = safe_execute(
            supabase.table('user_info')
            .select('first_name, last_name')
            .eq('id', student_id)
        )
        student_name = f"Student ID {student_id}"
        if getattr(student_info, 'data', None) and len(student_info.data) > 0:
            first_name = student_info.data[0].get('first_name', '')
            last_name = student_info.data[0].get('last_name', '')
            if first_name or last_name:
                student_name = f"{first_name} {last_name}".strip()

        # Insert points
        result = safe_execute(
            supabase.table('points').insert({
                'teacher_id': teacher_id,
                'student_id': student_id,
                'points': points,
                'point_category': point_category,
                'note': note,
                'status': 'approved',
                'received_at': now_ph
            })
        )
        if not getattr(result, 'data', None):
            raise Exception('Failed to insert points record')

        point_id = result.data[0].get('point_id')

        # Update total points
        user_result = safe_execute(
            supabase.table('user_info').select('total_points').eq('id', student_id)
        )
        current_total = 0
        if getattr(user_result, 'data', None) and len(user_result.data) > 0:
            current_total = int(user_result.data[0].get('total_points') or 0)
        new_total = current_total + points
        safe_execute(
            supabase.table('user_info').update({'total_points': new_total}).eq('id', student_id)
        )

        # Activity log
        safe_execute(
            supabase.table('admin_activity_log').insert({
                'user_id': teacher_id,
                'user_role': 'Teacher',
                'action': 'Award Points',
                'activity': 'Points Management',
                'description': f"Awarded {points} points to {student_name} for '{point_category}'",
                'details': f"Note: {note}"
            })
        )

        # Send notification to student
        teacher_info = safe_execute(
            supabase.table('user_info').select('last_name, gender').eq('id', teacher_id)
        )
        teacher_last_name = ''
        teacher_gender = ''
        if getattr(teacher_info, 'data', None) and len(teacher_info.data) > 0:
            teacher_last_name = teacher_info.data[0].get('last_name', '')
            teacher_gender = (teacher_info.data[0].get('gender', '') or '').lower()
        prefix = 'Mr.'
        if teacher_gender == 'female':
            prefix = 'Mrs.'
        elif teacher_gender == 'other':
            prefix = 'Mx.'
        teacher_name = f"{prefix} {teacher_last_name}"

        safe_execute(
            supabase.table('notifications').insert({
                'user_id': student_id,
                'sender_id': teacher_id,
                'title': 'Points Awarded',
                'message': f"{teacher_name} has awarded you {points} points for {point_category}.",
                'notif_type': 'Points',
                'status': 'Unread',
                'point_id': point_id
            })
        )

        return jsonify({
            'success': True,
            'message': 'Points awarded successfully!',
            'data': {'point_id': point_id, 'new_total': new_total}
        }), 201

    except Exception as e:
        print(f"Error awarding points: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500



# --- TEACHER BULK AWARD POINTS ROUTE ---
@app.route('/teacher_bulk_award_points', methods=['POST'])
def teacher_bulk_award_points():
    if not request.is_json:
        return jsonify({'success': False, 'message': 'Request must be JSON'}), 400

    data = request.get_json() or {}
    teacher_id = session.get('user_id') or data.get('teacher_id')
    student_ids = data.get('student_ids') or []
    points = data.get('points')
    category = data.get('category')
    note = data.get('note', '')

    if not teacher_id:
        return jsonify({'success': False, 'message': 'Missing teacher_id'}), 401
    if not isinstance(student_ids, list) or len(student_ids) == 0:
        return jsonify({'success': False, 'message': 'student_ids must be a non-empty list'}), 400
    try:
        points = int(points)
        if points <= 0:
            return jsonify({'success': False, 'message': 'points must be > 0'}), 400
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid points value'}), 400
    if not category or not str(category).strip():
        return jsonify({'success': False, 'message': 'Missing category'}), 400

    try:
        # Manila time ISO
        manila = timezone('Asia/Manila')
        now_ph = datetime.now(manila).isoformat()

        # build inserts for points table
        inserts = []
        for sid_raw in student_ids:
            try:
                sid = int(sid_raw)
            except Exception:
                continue
            inserts.append({
                'teacher_id': int(teacher_id),
                'student_id': sid,
                'points': points,
                'point_category': category,
                'note': note,
                'status': 'approved',
                'received_at': now_ph
            })

        if not inserts:
            return jsonify({'success': False, 'message': 'No valid student ids provided'}), 400

        # insert all points in one batch
        result = safe_execute(supabase.table('points').insert(inserts))
        if getattr(result, 'error', None):
            raise Exception(str(result.error))

        inserted = result.data if getattr(result, 'data', None) else []
        point_ids = []
        for rec in inserted:
            # Supabase insert may return the created record; try point_id or id keys
            pid = rec.get('point_id') or rec.get('id') or None
            if pid:
                point_ids.append(pid)

        # For each student update total_points and send notification
        notif_title = "Points Awarded"
        # fetch teacher short name/gender for message
        teacher_info = safe_execute(supabase.table('user_info').select('last_name, gender').eq('id', int(teacher_id)))
        teacher_last = ''
        teacher_gender = ''
        if getattr(teacher_info, 'data', None) and len(teacher_info.data) > 0:
            teacher_last = teacher_info.data[0].get('last_name', '')
            teacher_gender = (teacher_info.data[0].get('gender','') or '').lower()
        prefix = 'Mr.'
        if teacher_gender == 'female':
            prefix = 'Mrs.'
        elif teacher_gender == 'other':
            prefix = 'Mx.'
        teacher_name_short = f"{prefix} {teacher_last}".strip()
        notif_message = f"{teacher_name_short} awarded you {points} points for {category}."

        awarded_count = 0
        for sid_raw in student_ids:
            try:
                sid = int(sid_raw)
            except Exception:
                continue

            # read current total_points
            user_resp = safe_execute(supabase.table('user_info').select('total_points').eq('id', sid))
            current_total = 0
            if getattr(user_resp, 'data', None) and len(user_resp.data) > 0:
                current_total = int(user_resp.data[0].get('total_points') or 0)
            new_total = current_total + points
            safe_execute(supabase.table('user_info').update({'total_points': new_total}).eq('id', sid))

            # insert notification
            safe_execute(supabase.table('notifications').insert({
                'user_id': sid,
                'sender_id': int(teacher_id),
                'title': notif_title,
                'message': notif_message,
                'notif_type': 'Points',
                'status': 'Unread',
            }))

            awarded_count += 1

        # admin activity log
        safe_execute(supabase.table('admin_activity_log').insert({
            'user_id': int(teacher_id),
            'user_role': 'Teacher',
            'action': 'Bulk Award Points',
            'activity': 'Points Management',
            'description': f"Awarded {points} points to {awarded_count} students for '{category}'.",
            'details': f"Note: {note}",
        }))

        return jsonify({
            'success': True,
            'message': 'Points awarded successfully',
            'count': awarded_count,
            'point_ids': point_ids
        }), 201

    except Exception as e:
        import traceback
        print('teacher_bulk_award_points ERROR:', traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500




# --- TEACHER AWARD HISTORY PAGE DISPLAY ROUTE ---
@app.route('/teacher_award_history', methods=['GET'])
def teacher_award_history():
    """
    Returns all points awarded by the logged-in teacher.
    Query param: user_id (teacher id) or uses session user_id.
    """
    teacher_id = request.args.get('user_id') or session.get('user_id')
    if not teacher_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        # 1. Get all points awarded by this teacher
        points_resp = safe_execute(
            supabase.table('points')
            .select('point_id, student_id, points, point_category, note, received_at')
            .eq('teacher_id', teacher_id)
            .eq('status', 'approved')
            .order('received_at', desc=True)
        )
        points = points_resp.data if points_resp.data else []

        # 2. Get student info for each award
        student_ids = list({p['student_id'] for p in points if p.get('student_id')})
        students_map = {}
        if student_ids:
            students_resp = safe_execute(
                supabase.table('user_info')
                .select('id, first_name, last_name, year_level, section')
                .in_('id', student_ids)
            )
            for s in students_resp.data if students_resp.data else []:
                students_map[s['id']] = s

        # 3. Get profile pictures
        pics_map = {}
        if student_ids:
            pics_resp = safe_execute(
                supabase.table('profile_pictures')
                .select('user_id, file_path')
                .in_('user_id', student_ids)
            )
            for p in pics_resp.data if pics_resp.data else []:
                pics_map[p['user_id']] = p['file_path']

        # 4. Timezone setup for Manila
        manila_tz = pytz.timezone('Asia/Manila')
        now_manila = datetime.now(manila_tz)
        start_of_week_manila = now_manila - timedelta(days=now_manila.weekday())
        start_of_week_manila = start_of_week_manila.replace(hour=0, minute=0, second=0, microsecond=0)

        # 5. Build award history list
        history = []
        total_awards = len(points)
        total_points_awarded = 0
        students_awarded_set = set()
        this_week_awards = 0

        for p in points:
            sid = p.get('student_id')
            student = students_map.get(sid, {})
            profile_picture = pics_map.get(sid, '')

            # Convert UTC to Manila time
            awarded_at_utc = p.get('received_at')
            awarded_at_manila = None
            is_this_week = False

            if awarded_at_utc:
                try:
                    dt_utc = parser.parse(awarded_at_utc)
                    if dt_utc.tzinfo is None:
                        dt_utc = pytz.UTC.localize(dt_utc)
                    awarded_at_manila = dt_utc.astimezone(manila_tz)
                    # Check if within this week (Manila time)
                    if awarded_at_manila >= start_of_week_manila:
                        this_week_awards += 1
                        is_this_week = True
                except Exception as e:
                    print(f"Error parsing date {awarded_at_utc}: {e}")
                    awarded_at_manila = None

            # Add to student count
            if sid:
                students_awarded_set.add(sid)

            # Add points to total
            total_points_awarded += p.get('points', 0)

            # Build history record
            history.append({
                'award_id': p.get('point_id'),
                'student_id': sid,
                'student_name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
                'grade': student.get('year_level', ''),
                'section': student.get('section', ''),
                'points': p.get('points', 0),
                'category': p.get('point_category', ''),
                'note': p.get('note', ''),
                'awarded_at': awarded_at_manila.strftime('%Y-%m-%d %H:%M:%S') if awarded_at_manila else awarded_at_utc,
                'date': awarded_at_manila.strftime('%Y-%m-%d') if awarded_at_manila else (awarded_at_utc[:10] if awarded_at_utc else ''),
                'time': awarded_at_manila.strftime('%H:%M:%S') if awarded_at_manila else (awarded_at_utc[11:19] if awarded_at_utc and len(awarded_at_utc) > 11 else ''),
                'profile_picture': profile_picture,
                'is_this_week': is_this_week
            })

        # 6. Get classrooms for dropdown filter
        classroom_labels = []
        assignments_resp = safe_execute(
            supabase.table('teacher_class_assignments')
            .select('grade_level, section')
            .eq('teacher_id', teacher_id)
        )
        assignments = assignments_resp.data if assignments_resp.data else []
        seen = set()
        for a in assignments:
            label = f"Grade {a.get('grade_level', '')} - {a.get('section', '')}"
            if label not in seen:
                seen.add(label)
                classroom_labels.append(label)

        return jsonify({
            'success': True,
            'total_awards': total_awards,
            'total_points_awarded': total_points_awarded,
            'students_awarded': len(students_awarded_set),
            'this_week_awards': this_week_awards,
            'classrooms': classroom_labels,
            'history': history
        }), 200

    except Exception as e:
        import traceback
        print('teacher_award_history ERROR:', traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

import io
try:
    import pandas as pd
except Exception:
    pd = None

@app.route('/export_awards', methods=['POST'])
def export_awards():
    """
    Export teacher award history to Excel (.xlsx) with optional summary statistics.
    """
    try:
        from openpyxl.styles import Font, Alignment
        from openpyxl.utils import get_column_letter
        if pd is None:
            return jsonify({'success': False, 'error': 'Pandas not installed on server'}), 500

        data = request.get_json() or {}
        teacher_id = data.get('teacher_id') or data.get('user_id')
        if not teacher_id:
            return jsonify({'success': False, 'error': 'Missing teacher_id'}), 400

        only_filtered = str(data.get('only_filtered') or data.get('onlyFiltered') or '0').lower() in ['1', 'true', 'yes']
        include_summary = str(data.get('include_summary') or data.get('includeSummary') or '0').lower() in ['1', 'true', 'yes']
        filters = data.get('filters') or {}

        # --- Get all awards given by this teacher ---
        awards_resp = safe_execute(
            supabase.table('points')
            .select('point_id, student_id, points, point_category, note, received_at')
            .eq('teacher_id', teacher_id)
            .eq('status', 'approved')
            .order('received_at', desc=True)
        )
        awards = awards_resp.data if awards_resp.data else []

        # --- Get student info ---
        student_ids = list({a['student_id'] for a in awards if a.get('student_id')})
        students_map = {}
        if student_ids:
            students_resp = safe_execute(
                supabase.table('user_info')
                .select('id, first_name, last_name, year_level, section')
                .in_('id', student_ids)
            )
            for s in students_resp.data if students_resp.data else []:
                students_map[s['id']] = s

        # --- Build export records ---
        manila_tz = timezone('Asia/Manila')
        out = []
        for a in awards:
            sid = a.get('student_id')
            student = students_map.get(sid, {})
            received_at = a.get('received_at')
            date_disp = ''
            time_disp = ''
            try:
                dt = parser.parse(str(received_at))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                dt_manila = dt.astimezone(manila_tz)
                date_disp = dt_manila.strftime('%b %d, %Y')
                time_disp = dt_manila.strftime('%I:%M:%S %p')
            except Exception:
                date_disp = (str(received_at)[:10] if received_at else '')
                time_disp = ''
            out.append({
                'Student Name': f"{student.get('first_name','')} {student.get('last_name','')}".strip(),
                'Grade': student.get('year_level', ''),
                'Section': student.get('section', ''),
                'Points': a.get('points', 0),
                'Category': a.get('point_category', ''),
                'Note': a.get('note', ''),
                'Date': date_disp,
                'Time': time_disp,
            })

        # --- Apply filters if requested ---
        def matches_filters(rec):
            cls = filters.get('classroom') or ''
            if cls and cls not in ['All Grade and Section', 'All Classrooms', '', None]:
                if cls != f"Grade {rec.get('Grade')} - {rec.get('Section')}":
                    return False
            cat = filters.get('category') or ''
            if cat and cat not in ['All Categories', '', None] and rec.get('Category') != cat:
                return False
            s = (filters.get('search') or '').strip().lower()
            if s:
                if s not in str(rec.get('Student Name','')).lower() and s not in str(rec.get('Note','')).lower():
                    return False
            return True

        if only_filtered and filters:
            out = [r for r in out if matches_filters(r)]

        # --- Build DataFrame ---
        cols = ['Student Name','Grade','Section','Points','Category','Note','Date','Time']
        df_export = pd.DataFrame.from_records(out, columns=cols)

        # --- Summary statistics ---
        summary = {}
        if include_summary:
            total_awards = len(out)
            total_points = sum([int(r.get('Points') or 0) for r in out]) if out else 0
            unique_students = len(set([r.get('Student Name') for r in out])) if out else 0
            avg_points = round(total_points / total_awards, 1) if total_awards else 0
            summary = {
                'Total Awards': total_awards,
                'Total Points Awarded': total_points,
                'Unique Students': unique_students,
                'Average Points': avg_points,
            }

        # --- Create Excel file ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            sheet_name = 'Award History'
            if include_summary and summary:
                summary_count = len(summary)
                last_summary_row = 5 + summary_count
                header_excel_row = last_summary_row + 2
                startrow = header_excel_row - 1
            else:
                startrow = 4
            df_export.to_excel(writer, index=False, startrow=startrow, sheet_name=sheet_name)
            wb = writer.book
            ws = writer.sheets[sheet_name]

            # Header/title rows
            date_time_str = datetime.now().strftime('%B %d, %Y at %I:%M %p')
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(cols))
            ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(cols))
            ws.cell(row=1, column=1, value='Learn2Earn').font = Font(size=14, bold=True)
            ws.cell(row=2, column=1, value='Masico National High School').font = Font(size=11, bold=False)
            ws.cell(row=3, column=1, value=f'Award History Report - {date_time_str}').font = Font(size=10, bold=False)
            for r in (1,2,3):
                ws.cell(row=r, column=1).alignment = Alignment(horizontal='left')

            # Write summary block
            if include_summary and summary:
                ws.cell(row=5, column=1, value='SUMMARY STATISTICS').font = Font(bold=True)
                row_idx = 6
                for k, v in summary.items():
                    ws.cell(row=row_idx, column=1, value=f"{k}:")
                    ws.cell(row=row_idx, column=2, value=str(v))
                    row_idx += 1

            # Adjust column widths
            for i, col in enumerate(cols, start=1):
                max_len = max(
                    df_export[col].astype(str).map(len).max() if not df_export.empty else 10,
                    len(col)
                ) + 4
                ws.column_dimensions[get_column_letter(i)].width = min(max_len, 40)

            # Bold header row
            header_row = startrow + 1
            for col_idx in range(1, len(cols)+1):
                cell = ws.cell(row=header_row, column=col_idx)
                cell.font = Font(bold=True)

        output.seek(0)
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"Learn2Earn_Award_History_{date_str}.xlsx"

        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        import traceback
        print('export_awards error:', traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


# --- TEACHER TASKS PAGKUHA NG GRADE & SECTION AT MGA CURRENT AT FINISH ACT ROUTE ---
@app.route('/teacher_tasks', methods=['GET'])
def get_teacher_tasks():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id'}), 400

    # 1. Get classrooms assigned to teacher
    classroom_resp = safe_execute(
        supabase.table('teacher_class_assignments')
        .select('grade_level, section, subject')
        .eq('teacher_id', user_id)
    )
    classrooms = classroom_resp.data if classroom_resp.data else []

    # Remove duplicates
    unique_classrooms = []
    seen = set()
    for c in classrooms:
        key = (c['grade_level'], c['section'])
        if key not in seen:
            seen.add(key)
            unique_classrooms.append(c)

    # 2. Get tasks (current and finished)
    today = datetime.now().date().isoformat()

    # Fetch all tasks for this teacher
    all_tasks_resp = safe_execute(
        supabase.table('task_assignments')
        .select('task_id, task, points, description, due_date, priority, status, grade_level, section, image_urls, template, student_id, user_info!task_assignments_student_id_fkey(first_name, last_name)')
        .eq('teacher_id', user_id)
    )
    all_tasks = all_tasks_resp.data if all_tasks_resp.data else []

    # Group by (task, grade_level, section, due_date, etc) for activity, and collect students per activity
    from collections import defaultdict
    activity_map = {}
    students_map = defaultdict(list)
    for row in all_tasks:
        # Key for unique activity
        key = (
            row.get('task'),
            row.get('grade_level'),
            row.get('section'),
            row.get('due_date'),
        )
        # Save activity info (one per key)
        if key not in activity_map:
            activity_map[key] = {
                'task_id': row.get('task_id'),
                'task': row.get('task'),
                'points': row.get('points'),
                'description': row.get('description'),
                'due_date': row.get('due_date'),
                'priority': row.get('priority'),
                'status': row.get('status'),
                'grade_level': row.get('grade_level'),
                'section': row.get('section'),
                'image_urls': row.get('image_urls'),
                'template': row.get('template'),
                'students': []  # to be filled
            }
        # Build student info
        student_id = row.get('student_id')
        name = ''
        if row.get('user_info'):
            name = f"{row['user_info'].get('first_name', '')} {row['user_info'].get('last_name', '')}".strip()
        # Optionally, fetch proof_files here if needed (can batch if required)
        students_map[key].append({
            'student_id': student_id,
            'name': name,
            'status': row.get('status'),
            'proof_files': row.get('proof_files', []),  # If you want to fetch proof_files, batch fetch here
        })

    # Attach students to each activity
    for key, activity in activity_map.items():
        activity['students'] = students_map[key]

    # Split into current and finished based on status and due_date
    current_tasks = []
    finished_tasks = []
    for activity in activity_map.values():
        # If any student is still Assigned or Pending and due_date >= today, it's current
        is_current = False
        try:
            due_date = activity.get('due_date')
            if due_date:
                due_date_val = due_date
                if isinstance(due_date, str):
                    due_date_val = due_date
                else:
                    due_date_val = str(due_date)
                if due_date_val >= today:
                    for s in activity['students']:
                        if s.get('status') in ['Assigned', 'Pending']:
                            is_current = True
                            break
        except Exception:
            pass
        if is_current:
            current_tasks.append(activity)
        else:
            finished_tasks.append(activity)

    return jsonify({
        'classrooms': unique_classrooms,
        'current_tasks': current_tasks,
        'finished_tasks': finished_tasks
    }), 200

def get_students_for_activity(task, grade_level, section, due_date):
    query = supabase.table('task_assignments') \
        .select('task_id, student_id, status, user_info!task_assignments_student_id_fkey(first_name, last_name)') \
        .eq('task', task) \
        .eq('grade_level', grade_level) \
        .eq('section', section)
    if due_date:
        query = query.eq('due_date', due_date)
    resp = safe_execute(query)
    
    students = []
    for row in resp.data if resp.data else []:
        name = ''
        if row.get('user_info'):
            name = f"{row['user_info'].get('first_name', '')} {row['user_info'].get('last_name', '')}".strip()
        
        task_id = row.get('task_id')
        student_id = row.get('student_id')
        proof_files = []
        
        if task_id and student_id:
            try:
                files_resp = safe_execute(
                    supabase.table('task_file_submissions')
                    .select('*')  # ✅ Get ALL fields
                    .eq('task_id', task_id)
                    .eq('student_id', student_id)
                )
                if files_resp.data:
                    # ✅ Return full file objects, not just URLs
                    proof_files = files_resp.data
                    
                    print(f"[DEBUG] Task {task_id}, Student {student_id}: Found {len(proof_files)} files")
                    for f in proof_files:
                        print(f"  - {f.get('original_filename', 'unknown')}: {f.get('file_url', 'no url')}")
                        
            except Exception as e:
                print(f"Error fetching proof files for task {task_id}, student {student_id}: {e}")
                proof_files = []
        
        student_data = {
            'student_id': student_id,
            'name': name,
            'status': row['status'],
            'proof_files': proof_files,  # ✅ Full objects with metadata
        }
        students.append(student_data)
    
    return students


@app.route('/approve_activity_submissions', methods=['POST'])
def approve_activity_submissions():
    try:
        data = request.get_json()
        
        # ✅ USE user_id DIRECTLY FROM FRONTEND
        user_id = data.get('user_id')
        task_name = data.get('task_name')
        grade_level = data.get('grade_level')
        section = data.get('section')
        selected_students = data.get('selected_students', [])
        denied_students = data.get('denied_students', [])

        # ✅ DEBUG: Check teacher_id from frontend
        print(f"[DEBUG] Teacher ID from frontend: {user_id} (type: {type(user_id)})")

        # ✅ VALIDATE user_id
        if not user_id or not task_name or not grade_level or not section:
            return jsonify({'success': False, 'message': 'Missing required parameters'}), 400

        teacher_id = int(user_id)  # Convert to int
            
        # Get task info
        task_result = supabase.table('task_assignments') \
            .select('points') \
            .eq('task', task_name) \
            .eq('grade_level', grade_level) \
            .eq('section', section) \
            .limit(1).execute()
        
        if not task_result.data:
            return jsonify({'success': False, 'message': 'Task not found'}), 404
        
        points = int(task_result.data[0].get('points', 0))

        # Get teacher info for notification
        teacher_info = supabase.table('user_info') \
            .select('last_name, gender') \
            .eq('id', teacher_id).execute()
        
        teacher_last_name = ''
        teacher_gender = ''
        if teacher_info.data and len(teacher_info.data) > 0:
            teacher_last_name = teacher_info.data[0].get('last_name', '')
            teacher_gender = (teacher_info.data[0].get('gender', '') or '').lower()
        
        prefix = 'Mr.'
        if teacher_gender == 'female':
            prefix = 'Mrs.'
        elif teacher_gender == 'other':
            prefix = 'Mx.'
        teacher_name = f"{prefix} {teacher_last_name}"

        # ===== PROCESS SELECTED STUDENTS =====
        for student_id in selected_students:
            try:
                student_id_int = int(student_id) if isinstance(student_id, str) else student_id
                
                # Find assignment
                assignment = supabase.table('task_assignments') \
                    .select('task_id, status') \
                    .eq('task', task_name) \
                    .eq('student_id', student_id_int) \
                    .eq('grade_level', grade_level) \
                    .eq('section', section) \
                    .limit(1).execute()
                
                if assignment.data:
                    assignment_id = assignment.data[0]['task_id']
                    current_status = assignment.data[0].get('status')
                    
                    point_id = None
                    
                    if current_status == 'Pending':
                        # Insert points with FRONTEND teacher_id
                        point_result = supabase.table('points').insert({
                            'teacher_id': teacher_id,  # ✅ FROM FRONTEND
                            'student_id': student_id_int,
                            'points': points,
                            'point_category': 'Task',
                            'note': f"Completed Activity: {task_name}",
                            'status': 'approved'
                        }).execute()
                        
                        if point_result.data and len(point_result.data) > 0:
                            point_id = point_result.data[0].get('point_id')
                        
                        # Update user total points
                        user_result = supabase.table('user_info') \
                            .select('total_points') \
                            .eq('id', student_id_int).execute()
                        
                        current_total = 0
                        if user_result.data and 'total_points' in user_result.data[0] and user_result.data[0]['total_points'] is not None:
                            current_total = int(user_result.data[0]['total_points'])
                        
                        new_total = current_total + points
                        
                        supabase.table('user_info').update({'total_points': new_total}).eq('id', student_id_int).execute()
                    
                    # Update task status to Completed
                    supabase.table('task_assignments').update({
                        'status': 'Completed'
                    }).eq('task_id', assignment_id).execute()

                    # Send notification
                    notif_title = "Activity Approved"
                    notif_message = f"{teacher_name} has approved your activity '{task_name}' and awarded you {points} points."
                    supabase.table('notifications').insert({
                        'user_id': student_id_int,
                        'sender_id': teacher_id,  # ✅ FROM FRONTEND
                        'title': notif_title,
                        'message': notif_message,
                        'notif_type': 'Task',
                        'status': 'Unread',
                        'point_id': point_id,
                        'task_id': assignment_id
                    }).execute()
            except Exception as e:
                print(f"[DEBUG] ERROR processing student {student_id}: {e}")
                continue

        # ===== PROCESS DENIED STUDENTS =====
        for student_id in denied_students:
            try:
                student_id_int = int(student_id) if isinstance(student_id, str) else student_id
                
                assignment = supabase.table('task_assignments') \
                    .select('task_id') \
                    .eq('task', task_name) \
                    .eq('student_id', student_id_int) \
                    .eq('grade_level', grade_level) \
                    .eq('section', section) \
                    .limit(1).execute()
                
                if assignment.data:
                    assignment_id = assignment.data[0]['task_id']
                    
                    supabase.table('task_assignments').update({
                        'status': 'Denied'
                    }).eq('task_id', assignment_id).execute()
                    
                    notif_title = "Task Submission Denied"
                    notif_message = f"{teacher_name} has denied your submission for '{task_name}'. Please review and resubmit if needed."
                    supabase.table('notifications').insert({
                        'user_id': student_id_int,
                        'sender_id': teacher_id,  # ✅ FROM FRONTEND
                        'title': notif_title,
                        'message': notif_message,
                        'notif_type': 'Task',
                        'status': 'Unread',
                        'task_id': assignment_id
                    }).execute()
            except Exception as e:
                print(f"[DEBUG] ERROR processing denied student {student_id}: {e}")
                continue

        return jsonify({'success': True, 'message': 'Task submissions processed.'}), 200

    except Exception as e:
        print(f"[DEBUG] CRITICAL EXCEPTION: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500



# --- MOBILE VERSION: CREATE ACTIVITY/ASSIGN TASK ---
@app.route('/create_activity', methods=['POST'])
def create_activity():
    """
    Mobile version: assign activity/task to classroom.
    Accepts teacher_id in JSON (no session required).
    """
    data = request.get_json()

    # --- DEBUG: Print incoming payload for troubleshooting ---
    print("=== /create_activity DEBUG PAYLOAD ===")
    print(json.dumps(data, indent=2))
    print("======================================")

    teacher_id = data.get('teacher_id')
    grade_level = data.get('grade_level')
    section = data.get('section')
    task = data.get('task')
    points = data.get('points', 0)
    description = data.get('description', '')
    due_date = data.get('due_date', None)
    priority = data.get('priority', 'medium')
    template = data.get('template', 'default')
    image_urls = data.get('image_urls', [])

    # Validate required fields
    if not teacher_id or not grade_level or not section or not task:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    # Get all students in the selected classroom
    students_result = safe_execute(
        supabase.table('user_info')
        .select('id')
        .eq('role', 'Student')
        .eq('year_level', grade_level)
        .eq('section', section)
    )
    print(f"DEBUG: Searching students with year_level={grade_level}, section={section}")
    print(f"DEBUG: Students found: {students_result.data}")

    students = students_result.data if students_result.data else []

    assignments = []
    for student in students:
        assignments.append({
            'teacher_id': teacher_id,
            'student_id': student['id'],
            'grade_level': grade_level,
            'section': section,
            'task': task,
            'points': points,
            'description': description,
            'due_date': due_date,
            'priority': priority,
            'template': template,
           
            'status': 'Assigned',
            'assigned_at': datetime.now().isoformat(),
        })

    if assignments:
        result = safe_execute(supabase.table('task_assignments').insert(assignments))
        if hasattr(result, 'error') and result.error:
            return jsonify({'success': False, 'message': str(result.error)}), 400

        # --- ACTIVITY LOG: Create Activities ---
        safe_execute(supabase.table('admin_activity_log').insert({
            'user_id': teacher_id,
            'user_role': 'Teacher',
            'action': 'Create Activities',
            'activity': 'Activities Management',
            'description': f"Assigned Activity '{task}' for Grade {grade_level} Section {section} (Points: {points})",
            'details': '',
        }))

        # --- SEND NOTIFICATION TO STUDENTS ---
        teacher_info = safe_execute(
            supabase.table('user_info').select('last_name', 'gender').eq('id', teacher_id)
        )
        teacher_last_name = ''
        teacher_gender = ''
        if teacher_info.data and len(teacher_info.data) > 0:
            teacher_last_name = teacher_info.data[0].get('last_name', '')
            teacher_gender = (teacher_info.data[0].get('gender', '') or '').lower()
        prefix = 'Mr.'
        if teacher_gender == 'female':
            prefix = 'Mrs.'
        elif teacher_gender == 'other':
            prefix = 'Mx.'
        teacher_name = f"{prefix} {teacher_last_name}"

        notif_title = "New Activity Assigned"
        notif_message = f"{teacher_name} has assigned you a new activity: '{task}'."

        if result.data:
            for i, student in enumerate(students):
                try:
                    task_record = result.data[i]
                    assigned_task_id = task_record.get('task_id')
                    safe_execute(supabase.table('notifications').insert({
                        'user_id': student['id'],
                        'sender_id': teacher_id,
                        'title': notif_title,
                        'message': notif_message,
                        'notif_type': 'Task',
                        'status': 'Unread',
                        'task_id': assigned_task_id
                    }))
                except (IndexError, KeyError) as e:
                    print(f"Error sending notification to student {student['id']}: {e}")
                    safe_execute(supabase.table('notifications').insert({
                        'user_id': student['id'],
                        'sender_id': teacher_id,
                        'title': notif_title,
                        'message': notif_message,
                        'notif_type': 'Activities',
                        'status': 'Unread'
                    }))

        return jsonify({'success': True, 'message': 'Activities assigned to classroom.'}), 200

    return jsonify({'success': False, 'message': 'No students found in classroom.'}), 400


# --- TEACHER ANALYTICS PAGE ROUTE (MOBILE VERSION) ---
@app.route('/teacher_analytics', methods=['GET'])
def teacher_analytics():
    """
    Returns analytics data for a teacher.
    Query param: user_id (teacher_id)
    Returns JSON with stats, distributions, and trends.
    """
    teacher_id = request.args.get('user_id')
    if not teacher_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        # 1. Get classrooms assigned to this teacher
        assignments_result = safe_execute(
            supabase.table('teacher_class_assignments')
            .select('grade_level, section')
            .eq('teacher_id', teacher_id)
        )
        assignments = assignments_result.data if assignments_result.data else []

        # 2. Get all students in these classrooms
        students = []
        for assignment in assignments:
            grade_level = assignment['grade_level']
            section = assignment['section']
            students_result = safe_execute(
                supabase.table('user_info')
                .select('id')
                .eq('role', 'Student')
                .eq('year_level', grade_level)
                .eq('section', section)
            )
            if students_result.data:
                students.extend(students_result.data)
        
        unique_students = {student['id']: student for student in students}.values()
        student_ids = [student['id'] for student in unique_students]

        # 3. Initialize analytics data
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        total_points = 0
        category_distribution = {}
        active_students = set()

        # 4. Get all points awarded by this teacher
        if student_ids:
            points_result = safe_execute(
                supabase.table('points')
                .select('student_id, points, received_at, point_category')
                .eq('teacher_id', teacher_id)
                .in_('student_id', student_ids)
            )
            
            if points_result.data:
                for row in points_result.data:
                    pts = row.get('points', 0)
                    total_points += pts

                    # Category distribution
                    cat = row.get('point_category', 'Other')
                    category_distribution[cat] = category_distribution.get(cat, 0) + pts

                    # Track active students this month
                    received_at = row.get('received_at')
                    if received_at:
                        try:
                            dt = datetime.fromisoformat(str(received_at).replace('Z', '+00:00'))
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            else:
                                dt = dt.astimezone(timezone.utc)
                            
                            # Track active students this month
                            if dt >= start_of_month:
                                active_students.add(row['student_id'])
                        except Exception:
                            continue

        # 5. Average points per student
        avg_points = round(total_points / len(student_ids), 2) if student_ids else 0

        # 6. Task completion rate
        task_result = safe_execute(
            supabase.table('task_assignments')
            .select('student_id, status')
            .eq('teacher_id', teacher_id)
            .in_('student_id', student_ids)
        )
        
        total_tasks = 0
        completed_tasks = 0
        if task_result.data:
            for row in task_result.data:
                total_tasks += 1
                if row['status'].lower() == 'completed':
                    completed_tasks += 1
        
        task_completion_rate = round((completed_tasks / total_tasks) * 100, 2) if total_tasks else 0

        # 7. Monthly points trend (last 6 months)
        months = []
        month_labels = []
        for i in range(5, -1, -1):  # Last 6 months
            month = (now.replace(day=1) - timedelta(days=30*i)).replace(day=1)
            months.append(month)
            month_labels.append(month.strftime('%b %Y'))

        from collections import OrderedDict
        monthly_points = OrderedDict((label, 0) for label in month_labels)
        
        points_result_teacher = safe_execute(
            supabase.table('points')
            .select('points, received_at')
            .eq('teacher_id', teacher_id)
        )
        
        if points_result_teacher.data:
            for row in points_result_teacher.data:
                received_at = row.get('received_at')
                pts = row.get('points', 0)
                if received_at:
                    try:
                        dt = datetime.fromisoformat(str(received_at).replace('Z', '+00:00'))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        else:
                            dt = dt.astimezone(timezone.utc)
                        for i, month in enumerate(months):
                            if dt.year == month.year and dt.month == month.month:
                                monthly_points[month_labels[i]] += pts
                                break
                    except Exception:
                        continue

        # 8. Weekly points trend (last 4 weeks)
        week_labels = []
        weekly_points = []
        for i in range(3, -1, -1):
            week_start = (now - timedelta(days=now.weekday())) - timedelta(weeks=i)
            week_end = week_start + timedelta(days=6)
            week_label = f"{week_start.strftime('%b %d')}-{week_end.strftime('%b %d')}"
            week_labels.append(week_label)
            weekly_points.append(0)
        
        if points_result_teacher.data:
            for row in points_result_teacher.data:
                received_at = row.get('received_at')
                pts = row.get('points', 0)
                if received_at:
                    try:
                        dt = datetime.fromisoformat(str(received_at).replace('Z', '+00:00'))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        else:
                            dt = dt.astimezone(timezone.utc)
                        for i in range(4):
                            week_start = (now - timedelta(days=now.weekday())) - timedelta(weeks=3-i)
                            week_end = week_start + timedelta(days=6)
                            if week_start <= dt <= week_end:
                                weekly_points[i] += pts
                                break
                    except Exception:
                        continue

        # 9. Return analytics data - MATCHING WEB ROUTE STRUCTURE
        return jsonify({
            'success': True,
            'analytics': {
                'points_all_time': total_points,  # CHANGED: points_this_month to points_all_time
                'average_points_per_student': avg_points,
                'activity_completion_rate': task_completion_rate,
                'active_students': len(active_students),
                'total_points_awarded': total_points,
                'total_tasks_assigned': total_tasks,
                'total_tasks_completed': completed_tasks,
            },
            'category_distribution': category_distribution,
            'monthly_trend': {
                'labels': list(monthly_points.keys()),
                'data': list(monthly_points.values())
            },
            'weekly_trend': {
                'labels': week_labels,  # CHANGED: Now uses date range format like web
                'data': weekly_points
            }
        }), 200

    except Exception as e:
        import traceback
        print(f"Error fetching teacher analytics: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': str(e),
            'analytics': {
                'points_all_time': 0,  # CHANGED: points_this_month to points_all_time
                'average_points_per_student': 0,
                'activity_completion_rate': 0,
                'active_students': 0,
                'total_points_awarded': 0,
                'total_tasks_assigned': 0,
                'total_tasks_completed': 0,
            },
            'category_distribution': {},
            'monthly_trend': {'labels': [], 'data': []},
            'weekly_trend': {'labels': [], 'data': []}
        }), 500


# --- TEACHER PROFILE INFO ROUTE (NEW) ---
@app.route('/teacher_personal_info', methods=['GET'])
def teacher_personal_info():
    """
    Fetch teacher's personal information from database.
    Query param: user_id (teacher_id)
    Returns: first_name, last_name, email, mobile_no, subject, gender
    """
    user_id = request.args.get('user_id')
    
    # ✅ DEBUG: Log incoming request
    print(f"=== /teacher_personal_info DEBUG ===")
    print(f"✅ Received user_id: {user_id}")
    print(f"✅ Type: {type(user_id)}")
    print(f"=== END DEBUG ===")
    
    if not user_id:
        print("❌ ERROR: Missing user_id")
        return jsonify({'error': 'Missing user_id'}), 400

    try:
        # Fetch teacher info from user_info table
        teacher_resp = safe_execute(
            supabase.table('user_info').select(
                'id, first_name, middle_name, last_name, gender, email, mobile_no, subject, role'
            ).eq('id', user_id).eq('role', 'Teacher')
        )
        
        print(f"✅ Database response: {teacher_resp.data if teacher_resp.data else 'No data'}")
        
        if not teacher_resp.data or len(teacher_resp.data) == 0:
            print(f"❌ ERROR: Teacher not found for user_id: {user_id}")
            return jsonify({'error': 'Teacher not found'}), 404

        teacher = teacher_resp.data[0]
        
        print(f"✅ Teacher found: {teacher.get('first_name')} {teacher.get('last_name')}")
        
        return jsonify({
            'success': True,
            'id': teacher.get('id'),
            'first_name': teacher.get('first_name', ''),
            'middle_name': teacher.get('middle_name', ''),
            'last_name': teacher.get('last_name', ''),
            'gender': teacher.get('gender', ''),
            'email': teacher.get('email', ''),
            'mobile_no': teacher.get('mobile_no', ''),
            'subject': teacher.get('subject', ''),
            'role': teacher.get('role', '')
        }), 200

    except Exception as e:
        print(f"❌ EXCEPTION: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    

# --- UPDATE TEACHER PROFILE ROUTE (COMBINED) ---
@app.route('/update_teacher_profile', methods=['POST'])
def update_teacher_profile():
    """
    Update teacher's profile information and/or profile picture.
    Expects either JSON body with: user_id, first_name, last_name, email, mobile_no
    OR multipart form with: user_id, image (file)
    """
    try:
        # Check if it's a file upload (profile picture) or JSON data (profile info)
        if 'image' in request.files:
            return _handle_profile_picture_upload()
        else:
            return _handle_profile_info_update()
    except Exception as e:
        print(f"Error in update_teacher_profile: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

def _handle_profile_picture_upload():
    """Handle profile picture upload"""
    user_id = request.form.get('user_id')
    if 'image' not in request.files or not user_id:
        return jsonify({'success': False, 'message': 'Missing image or user_id'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Invalid file'}), 400

    from datetime import datetime
    filename = f"user_{user_id}_image_{datetime.now().strftime('%Y-%m-%d_%H%M%S%f')}.png"

    # Upload to Supabase Storage
    file_bytes = file.read()
    storage_resp = supabase.storage.from_('profile-pictures').upload(filename, file_bytes, {"content-type": file.mimetype})

    if hasattr(storage_resp, 'error') and storage_resp.error is not None:
        return jsonify({'success': False, 'message': str(storage_resp.error)}), 500

    public_url = f"https://bdcmzatfoaocnsfdpudv.supabase.co/storage/v1/object/public/profile-pictures/{filename}"

    # ✅ ONLY update profile_pictures (current picture)
    existing = safe_execute(supabase.table('profile_pictures').select('pic_id').eq('user_id', user_id))
    if existing.data and len(existing.data) > 0:
        # Update existing record
        safe_execute(supabase.table('profile_pictures').update({
            'file_path': public_url,
            'uploaded_at': datetime.now().isoformat()
        }).eq('user_id', user_id))
    else:
        # Insert new record
        safe_execute(supabase.table('profile_pictures').insert({
            'user_id': int(user_id),
            'file_path': public_url,
            'uploaded_at': datetime.now().isoformat()
        }))

    # ✅ ALWAYS insert to profile_picture_history (for history/recent avatars)
    safe_execute(supabase.table('profile_picture_history').insert({
        'user_id': int(user_id),
        'file_path': public_url,
        'uploaded_at': datetime.now().isoformat()
    }))

    # ✅ Insert to admin_activity_log (ONLY ONCE)
    user_resp = safe_execute(supabase.table('user_info').select('role, first_name, last_name').eq('id', user_id))
    user = user_resp.data[0] if user_resp.data else {}
    user_role = user.get('role', 'Student')
    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()

    safe_execute(supabase.table('admin_activity_log').insert({
        'user_id': int(user_id),
        'user_role': user_role,
        'action': 'Change Avatar',
        'activity': 'Profile Management',
        'description': 'Changed profile picture.',
    }))

    return jsonify({'success': True, 'profile_picture': public_url}), 200

def _handle_profile_info_update():
    """Handle profile information update with validation"""
    import re
    
    data = request.get_json()
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'success': False, 'message': 'Missing user_id'}), 400

    # Only allow updating these fields
    update_fields = {
        'first_name': data.get('first_name', '').strip(),
        'last_name': data.get('last_name', '').strip(),
        'email': data.get('email', '').strip(),
        'mobile_no': data.get('mobile_no', '').strip()
    }

    # Basic validation - check required fields
    if not update_fields['first_name']:
        return jsonify({'success': False, 'message': 'First name is required.'}), 400
    if not update_fields['last_name']:
        return jsonify({'success': False, 'message': 'Last name is required.'}), 400
    if not update_fields['email']:
        return jsonify({'success': False, 'message': 'Email is required.'}), 400

    # Validate names: only letters and spaces
    if not re.match(r'^[A-Za-z\s]+$', update_fields['first_name']):
        return jsonify({'success': False, 'message': 'First name must contain only letters and spaces.'}), 400
    if not re.match(r'^[A-Za-z\s]+$', update_fields['last_name']):
        return jsonify({'success': False, 'message': 'Last name must contain only letters and spaces.'}), 400

    # Validate email format
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, update_fields['email']):
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400

    # Validate mobile_no: must start with 09 and be 11 digits
    if update_fields['mobile_no'] and not re.match(r'^09\d{9}$', update_fields['mobile_no']):
        return jsonify({'success': False, 'message': 'Mobile number must start with 09 and be 11 digits.'}), 400

    # Check if email already exists (for other users)
    email_check = safe_execute(
        supabase.table('user_info')
        .select('id')
        .eq('email', update_fields['email'])
    )
    if email_check.data and len(email_check.data) > 0:
        # Check if it's the same user
        if email_check.data[0]['id'] != int(user_id):
            return jsonify({'success': False, 'message': 'Email already exists'}), 409

    try:
        # Update teacher info
        result = safe_execute(
            supabase.table('user_info')
            .update(update_fields)
            .eq('id', user_id)
        )

        if hasattr(result, 'error') and result.error:
            return jsonify({'success': False, 'message': 'Error updating profile.'}), 500

        if not result.data or len(result.data) == 0:
            return jsonify({'success': False, 'message': 'Update failed'}), 500

        # Log activity
        teacher = result.data[0]
        user_name = f"{teacher.get('first_name', '')} {teacher.get('last_name', '')}".strip()
        
        safe_execute(
            supabase.table('admin_activity_log').insert({
                'user_id': int(user_id),
                'user_role': 'Teacher',
                'action': 'Update Profile',
                'activity': 'Profile Management',
                'description': 'Updated profile information.',
            })
        )

        return jsonify({
            'success': True,
            'message': 'Profile updated successfully',
            'data': result.data[0]
        }), 200

    except Exception as e:
        print(f"Error updating profile: {e}")
        return jsonify({'success': False, 'message': 'Server error occurred while updating profile.'}), 500
    
# --- TEACHER CHANGE PASSWORD ROUTE ---
@app.route('/teacher_change_password', methods=['POST'])
def teacher_change_password():
    """
    Change password for teacher or student.
    Expects JSON body with: user_id, current_password, new_password
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    user_id = data.get('user_id')
    current_password = data.get('current_password', '').strip()
    new_password = data.get('new_password', '').strip()

    if not user_id:
        return jsonify({'success': False, 'message': 'Missing user_id'}), 400

    if not current_password or not new_password:
        return jsonify({'success': False, 'message': 'Current and new password are required.'}), 400

    if current_password == new_password:
        return jsonify({'success': False, 'message': 'New password must be different from current password.'}), 400

    # Password strength validation (min 8 chars, upper/lower/digit/special including underscore)
    import re
    password_regex = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?])[A-Za-z\d!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]{8,}$'
    if not re.match(password_regex, new_password):
        return jsonify({
            'success': False,
            'message': 'Password must be at least 8 characters and include uppercase letters, lowercase letters, numbers, and special characters.'
        }), 400

    try:
        # Fetch user info
        user_result = safe_execute(
            supabase.table('user_info')
            .select('id, password, role, first_name, last_name')
            .eq('id', user_id)
        )

        if not user_result.data or len(user_result.data) == 0:
            return jsonify({'success': False, 'message': 'User not found.'}), 404

        user = user_result.data[0]

        # Verify current password
        if user.get('password') != current_password:
            return jsonify({'success': False, 'message': 'Current password is incorrect.'}), 401

        # Update password
        update_result = safe_execute(
            supabase.table('user_info')
            .update({'password': new_password})
            .eq('id', user_id)
        )

        if not update_result.data or len(update_result.data) == 0:
            return jsonify({'success': False, 'message': 'Failed to update password.'}), 500

        # Log activity to admin_activity_log with correct format
        safe_execute(
            supabase.table('admin_activity_log').insert({
                'user_id': int(user_id),
                'action': 'Change Password',
                'activity': 'Profile Management',
                'description': 'Changed account password.',
                'user_role': user.get('role', 'Student')
            })
        )

        return jsonify({
            'success': True,
            'message': 'Password changed successfully.'
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Server error occurred while changing password.'
        }), 500

# --- SAFELY EXECUTE QUERIES WITH RETRY LOGIC ---
def safe_execute(query, retries=3, delay=1):
    for attempt in range(retries):
        try:
            return query.execute()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(delay)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)