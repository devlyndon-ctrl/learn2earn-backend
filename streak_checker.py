from supabase import create_client
import config
from datetime import datetime, timedelta
import time

def safe_execute(query, retries=3, delay=1):
    for attempt in range(retries):
        try:
            return query.execute()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(delay)

supabase = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

def check_and_reset_streaks():
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    # Get all active students
    users_resp = safe_execute(
        supabase.table('user_info')
        .select('id, streak, last_login_date')
        .eq('role', 'Student')
        .eq('status', 'Active')
    )
    users = users_resp.data if users_resp.data else []

    for user in users:
        last_login_str = user.get('last_login_date')
        streak = user.get('streak', 0) or 0
        user_id = user['id']

        try:
            last_login_date = datetime.strptime(last_login_str, '%Y-%m-%d').date() if last_login_str else None
        except Exception:
            last_login_date = None

        # If streak > 0 and last login is not yesterday or today, reset streak and notify
        if streak > 0 and (not last_login_date or last_login_date < yesterday):
            # Reset streak
            safe_execute(supabase.table('user_info').update({
                'streak': 0
            }).eq('id', user_id))

            # Insert notification for lost streak
            safe_execute(supabase.table('notifications').insert({
                'user_id': user_id,
                'title': 'Streak Lost',
                'message': 'You missed a day and your streak has been reset to 0. Start again to build your streak!',
                'notif_type': 'General',
                'status': 'Unread',
            }))
            print(f"Streak reset and notification sent for user_id {user_id}")

if __name__ == '__main__':
    check_and_reset_streaks()