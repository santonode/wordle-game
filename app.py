from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import random
from datetime import date, datetime
import os
import io
import base64
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import hashlib
import psycopg  # Updated to psycopg3

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Get database URL and admin password from environment
DATABASE_URL = os.environ.get('DATABASE_URL')
ADMIN_PASS = os.environ.get('ADMIN_PASS')
if not DATABASE_URL or not ADMIN_PASS:
    raise ValueError("DATABASE_URL and ADMIN_PASS environment variables must be set")

# Initialize Postgres database
def init_db():
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Ensure daily_word table exists
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS daily_word (
                        date TEXT PRIMARY KEY,
                        word TEXT NOT NULL
                    )
                ''')
                # Ensure game_logs table exists
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS game_logs (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMP,
                        ip_address TEXT,
                        username TEXT,
                        win INTEGER,
                        guesses INTEGER
                    )
                ''')
                # Ensure users table exists with id as primary key
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        ip_address TEXT,
                        username TEXT UNIQUE,
                        user_type TEXT DEFAULT 'Guest',
                        points INTEGER DEFAULT 0,
                        password TEXT
                    )
                ''')
                # Ensure user_stats table exists with foreign key on id
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS user_stats (
                        user_id INTEGER PRIMARY KEY,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0,
                        total_guesses INTEGER DEFAULT 0,
                        games_played INTEGER DEFAULT 0,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    )
                ''')
                conn.commit()
        print(f"Database initialized successfully with URL: {DATABASE_URL}")
    except psycopg.Error as e:
        print(f"Database initialization error: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error during initialization: {str(e)}")
        raise

# Load word list
try:
    with open('words.txt', 'r') as f:
        WORDS = [word.strip().upper() for word in f.readlines()]
except FileNotFoundError:
    print("Error: words.txt not found")
    WORDS = ['APPLE', 'BREAD', 'CLOUD', 'DREAM']  # Fallback list

# Get or set daily word
def get_daily_word():
    today = str(date.today())
    print(f"Attempting to connect to database with URL: {DATABASE_URL}")  # Debug
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT word FROM daily_word WHERE date = %s', (today,))
                result = cur.fetchone()
                if result:
                    print(f"Found word for {today}: {result[0]}")
                    return result[0]
                else:
                    word = random.choice(WORDS)
                    cur.execute('INSERT INTO daily_word (date, word) VALUES (%s, %s)', (today, word))
                    conn.commit()
                    print(f"Inserted new word for {today}: {word}")
                    return word
    except psycopg.Error as e:
        print(f"Database error in get_daily_word: {str(e)}")
        return random.choice(WORDS)  # Fallback to random word
    except Exception as e:
        print(f"Unexpected error in get_daily_word: {str(e)}")
        return random.choice(WORDS)  # Fallback to random word

# Generate username based on IP and session data
def generate_username(ip_address):
    seed = f"{ip_address}{datetime.now().microsecond}{random.randint(1000, 9999)}"
    hash_object = hashlib.md5(seed.encode())
    hash_hex = hash_object.hexdigest()[:8]  # Take first 8 characters for brevity
    username = ''.join(c for c in hash_hex if c.isalnum()).upper()[:12]
    return username

# Hash password for storage
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Initialize database on app startup
init_db()

# Global error handler
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {str(e)}")
    return "An error occurred. Please try again later.", 500

@app.route('/')
def index():
    today = str(date.today())
    last_played = session.get('last_played_date')
    username = session.get('username')
    
    # Clear session if no guesses or new day
    if not session.get('guesses') or (last_played and last_played != today):
        session.clear()
        session['guesses'] = []
        session['game_over'] = False
        session['hard_mode'] = False
        session['last_played_date'] = today if not last_played else None

    # Block only if the game was completed today for the current user
    if username and session.get('last_played_date') == today and session.get('game_over', False):
        return render_template('index.html', game_blocked=True, message="You've already played today's puzzle. Use 'Clear Session' to test again!")
    
    return render_template('index.html', game_blocked=False)

@app.route('/wordlist')
def wordlist():
    username = session.get('username')
    if username:
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT id FROM users WHERE username = %s', (username,))
                    user_id = cur.fetchone()
                    if user_id:
                        user_id = user_id[0]
                        cur.execute('UPDATE users SET points = GREATEST(points - 1, 0) WHERE id = %s', (user_id,))
                        conn.commit()
                        print(f"Debug - Deducted 1 point for user {username}, new points: {cur.fetchone()[0]}")
        except psycopg.Error as e:
            print(f"Database error deducting point for wordlist: {str(e)}")
    return render_template('wordlist.html', words=WORDS)

@app.route('/stats')
def stats():
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT date(timestamp) as day, 
                           SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
                           SUM(CASE WHEN win = 0 THEN 1 ELSE 0 END) as losses
                    FROM game_logs GROUP BY day ORDER BY day
                ''')
                data = cur.fetchall()
                cur.execute('SELECT COUNT(*) FROM game_logs')
                total_games = cur.fetchone()[0]
        
        if not data:
            return render_template('stats.html', chart=None, table_data=None)
        
        days = [row[0] for row in data]
        wins = [row[1] for row in data]
        losses = [row[2] for row in data]
        
        fig, ax = plt.subplots(figsize=(9, 6))  # Set width to ~900px (9 inches at 100dpi)
        ax.bar(days, wins, label='Wins', color='green')
        ax.bar(days, losses, bottom=wins, label='Losses', color='red')
        ax.set_xlabel('Date')
        ax.set_ylabel('Count')
        ax.set_title(f'Historical Wins and Losses (Total Games: {total_games})')
        ax.legend()
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.tick_params(axis='x', labelsize=8, rotation=45)
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)  # Ensure 900px width with dpi=100
        buf.seek(0)
        chart = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close(fig)
        
        # Prepare table data
        table_data = data
        
        return render_template('stats.html', chart=chart, table_data=table_data)
    except psycopg.Error as e:
        print(f"Database error in stats: {str(e)}")
        return render_template('stats.html', chart=None, table_data=None)
    except Exception as e:
        print(f"Unexpected error in stats: {str(e)}")
        return render_template('stats.html', chart=None, table_data=None)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    ip_address = request.remote_addr
    user_type = 'Guest'
    points = 0
    if 'username' not in session or not session.get('username'):
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT username, user_type, points FROM users WHERE ip_address = %s LIMIT 1', (ip_address,))
                    result = cur.fetchone()
                    if result:
                        session['username'], user_type, points = result
                    else:
                        username = generate_username(ip_address)
                        session['username'] = username
                        cur.execute('INSERT INTO users (ip_address, username, user_type, points) VALUES (%s, %s, %s, %s)', 
                                  (ip_address, username, 'Guest', 0))
                        cur.execute('INSERT INTO user_stats (user_id) VALUES (currval(\'users_id_seq\'))')
                        conn.commit()
                        user_type = 'Guest'
                        points = 0
        except psycopg.Error as e:
            print(f"Database error initializing user: {str(e)}")
            session['username'] = generate_username(ip_address)

    wins = 0
    losses = 0
    total_guesses = 0
    games_played = 0
    avg_guesses = 0.0
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM users WHERE username = %s', (session['username'],))
                user_id = cur.fetchone()[0]
                cur.execute('SELECT wins, losses, total_guesses, games_played FROM user_stats WHERE user_id = %s', (user_id,))
                stats = cur.fetchone()
                if stats:
                    wins, losses, total_guesses, games_played = stats
                    avg_guesses = round(total_guesses / games_played, 1) if games_played > 0 else 0.0
                else:
                    cur.execute('INSERT INTO user_stats (user_id) VALUES (%s)', (user_id,))
                    conn.commit()
    except psycopg.Error as e:
        print(f"Database error fetching stats: {str(e)}")

    message = None
    if request.method == 'POST':
        if 'clear_session' in request.form:
            current_username = session.get('username')
            session.clear()
            session['username'] = current_username
            session['guesses'] = []
            session['game_over'] = False
            session['hard_mode'] = False
            message = "Session data cleared. Please return to the game."
        elif 'login' in request.form:
            username = request.form.get('login_username', '').strip()
            password = request.form.get('login_password', '')
            switch_user = request.form.get('switch_user', '0') == '1'  # Check for hidden switch_user field
            if username and password:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            hashed_password = hash_password(password)
                            print(f"Attempting login for {username} with hashed password: {hashed_password}")
                            cur.execute('SELECT user_type, points, password FROM users WHERE username = %s', (username,))
                            result = cur.fetchone()
                            if result:
                                stored_user_type, stored_points, stored_password = result
                                if stored_password == hashed_password:
                                    session.clear()  # Always clear session on login
                                    session['username'] = username  # Update to registered username
                                    user_type = stored_user_type  # Update user type to Member
                                    points = stored_points
                                    message = "Login successful!"
                                else:
                                    message = "Invalid username or password."
                            else:
                                message = "Invalid username or password."
                except psycopg.Error as e:
                    print(f"Database error during login: {str(e)}")
                    message = "Error during login."
        elif 'register' in request.form:
            new_username = request.form.get('register_username', '').strip()
            new_password = request.form.get('register_password', '')
            if new_username and new_password and all(c.isalnum() for c in new_username) and 1 <= len(new_username) <= 12:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            cur.execute('SELECT 1 FROM users WHERE username = %s', (new_username,))
                            if cur.fetchone():
                                message = "Username already taken."
                            else:
                                cur.execute('INSERT INTO users (ip_address, username, password, user_type, points) VALUES (%s, %s, %s, %s, %s)', 
                                          (ip_address, new_username, hash_password(new_password), 'Member', 0))
                                cur.execute('INSERT INTO user_stats (user_id) VALUES (currval(\'users_id_seq\'))')
                                conn.commit()
                                session.clear()  # Clear session on registration
                                session['username'] = new_username  # Update to registered username
                                user_type = 'Member'
                                points = 0
                                message = "Registration successful! You are now a Member."
                except psycopg.Error as e:
                    print(f"Database error during registration: {str(e)}")
                    message = "Error during registration."
        else:
            new_username = request.form.get('username', '').strip()
            if new_username and all(c.isalnum() for c in new_username) and 1 <= len(new_username) <= 12:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            cur.execute('UPDATE users SET username = %s, user_type = %s WHERE ip_address = %s AND username = %s', 
                                      (new_username, 'Member', ip_address, session['username']))
                            if cur.rowcount > 0:
                                session['username'] = new_username
                                user_type = 'Member'
                                message = "Username updated successfully!"
                            else:
                                message = "No user found to update with this IP and username."
                        conn.commit()
                except psycopg.Error as e:
                    print(f"Database error updating username: {str(e)}")
                    message = f"Error updating username: {str(e)}"
            else:
                message = "Username must be 1-12 alphanumeric records."

    return render_template('profile.html', username=session['username'], message=message, wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    message = None
    authenticated = session.get('admin_authenticated', False)

    if request.method == 'POST':
        if 'admin_pass' in request.form:
            admin_pass = request.form.get('admin_pass', '')
            if admin_pass == ADMIN_PASS:
                session['admin_authenticated'] = True
                authenticated = True
            else:
                message = "Incorrect admin password."
        elif 'delete' in request.form:
            delete_username = request.form.get('delete_username')
            try:
                with psycopg.connect(DATABASE_URL) as conn:
                    with conn.cursor() as cur:
                        cur.execute('DELETE FROM users WHERE username = %s RETURNING id', (delete_username,))
                        user_id = cur.fetchone()
                        if user_id:
                            cur.execute('DELETE FROM user_stats WHERE user_id = %s', (user_id[0],))
                            conn.commit()
                            message = f"User {delete_username} deleted successfully."
                        else:
                            message = f"User {delete_username} not found."
            except psycopg.Error as e:
                print(f"Database error during delete: {str(e)}")
                message = f"Error deleting user {delete_username}: {str(e)}"
        elif 'save' in request.form:
            edit_username = request.form.get('edit_username')
            new_username = request.form.get('new_username').strip()
            new_password = request.form.get('new_password')
            new_points = request.form.get('new_points', 0, type=int)  # Get points with default 0
            if new_username and new_password and all(c.isalnum() for c in new_username) and 1 <= len(new_username) <= 12:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            cur.execute('SELECT 1 FROM users WHERE username = %s AND username != %s', (new_username, edit_username))
                            if cur.fetchone():
                                message = "Username already taken."
                            else:
                                cur.execute('UPDATE users SET username = %s, password = %s, points = %s WHERE username = %s',
                                          (new_username, hash_password(new_password), new_points, edit_username))
                                conn.commit()
                                message = f"User {edit_username} updated to {new_username} successfully."
                except psycopg.Error as e:
                    print(f"Database error during update: {str(e)}")
                    message = f"Error updating user {edit_username}: {str(e)}"
            else:
                message = "Username must be 1-12 alphanumeric characters."

    if not authenticated:
        return render_template('admin.html', authenticated=False, message=message)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id, username, password, points FROM users')
                users = [{'id': row[0], 'username': row[1], 'password': row[2], 'points': row[3]} for row in cur.fetchall()]
        return render_template('admin.html', authenticated=True, users=users, message=message)
    except psycopg.Error as e:
        print(f"Database error in admin: {str(e)}")
        message = "Error fetching user data."
        return render_template('admin.html', authenticated=True, users=[], message=message)

@app.route('/guess', methods=['POST'])
def guess():
    today = str(date.today())
    print(f"Debug - Guess route called, session: {session}")  # Add debugging
    username = session.get('username')
    if not username:
        ip_address = request.remote_addr
        username = generate_username(ip_address)
        session['username'] = username
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute('INSERT INTO users (ip_address, username, user_type, points) VALUES (%s, %s, %s, %s) ON CONFLICT (username) DO NOTHING',
                              (ip_address, username, 'Guest', 0))
                    conn.commit()
        except psycopg.Error as e:
            print(f"Database error creating guest user: {str(e)}")

    if session.get('last_played_date') == today and session.get('game_over', False):
        return jsonify({'error': 'You have already played today. Use \'Clear Session\' to test again!'})

    if session.get('game_over'):
        return jsonify({'error': 'Game is over. Start a new game.'})

    guess = request.json.get('guess', '').upper()
    print(f"Debug - Received guess: {guess}")  # Add debugging
    hard_mode = session.get('hard_mode', False)
    target = get_daily_word()
    print(f"Debug - Target word: {target}")  # Add target for debugging

    if len(guess) != 5 or guess not in WORDS:
        print(f"Debug - Invalid guess: {guess}, length: {len(guess)}, in WORDS: {guess in WORDS}")  # Add debugging
        return jsonify({'error': 'Invalid word. Must be a 5-letter word from the list.'})

    # Hard Mode: Check if guess uses all known green/yellow letters
    if hard_mode:
        known_letters = {}
        for g in session.get('guesses', []):
            for i, (letter, color) in enumerate(zip(g['guess'], g['result'])):
                if color in ['green', 'yellow']:
                    known_letters[letter] = known_letters.get(letter, 0) + 1
        guess_letters = {}
        for letter in guess:
            guess_letters[letter] = guess_letters.get(letter, 0) + 1
        for letter, count in known_letters.items():
            if guess_letters.get(letter, 0) < count:
                return jsonify({'error': f'Hard Mode: Must use all known letters ({letter}).'})

    # Evaluate guess
    result = ['gray'] * 5  # Initialize with 5 gray elements
    target_counts = {}
    for letter in target:
        target_counts[letter] = target_counts.get(letter, 0) + 1
    guess_counts = {}

    # First pass: Mark green letters
    all_green = True
    for i, (g, t) in enumerate(zip(guess, target)):
        if g == t:
            result[i] = 'green'
            guess_counts[g] = guess_counts.get(g, 0) + 1
        else:
            all_green = False
    print(f"Debug - After first pass, result: {result}, all_green: {all_green}")  # Debug after first pass

    # Second pass: Mark yellow letters only if not all green
    if not all_green:
        for i, (g, t) in enumerate(zip(guess, target)):
            if result[i] == 'gray' and g in target and guess_counts.get(g, 0) < target_counts.get(g, 0):
                result[i] = 'yellow'
                guess_counts[g] = guess_counts.get(g, 0) + 1
    print(f"Debug - After second pass, result: {result}")  # Debug after second pass

    session['guesses'].append({'guess': guess, 'result': result})
    session.modified = True

    # Check win/lose conditions
    game_over = False
    message = None
    win = 0
    points_change = 0
    if guess == target:
        game_over = True
        session['game_over'] = True
        session['last_played_date'] = today
        message = f'Congratulations! You solved it in {len(session["guesses"])} guesses!'
        win = 1
        points_change = 10  # Add 10 points for a win
        print(f"Debug - Win condition met: guess={guess}, target={target}, guesses={len(session['guesses'])}, username={username}")
    elif len(session['guesses']) >= 6:
        game_over = True
        session['game_over'] = True
        session['last_played_date'] = today
        message = f'Game over! The word was {target}.'
        win = 0
        points_change = -10  # Subtract 10 points for a loss
        print(f"Debug - Lose condition met: guesses={len(session['guesses'])}, target={target}, username={username}")

    if game_over:
        # Log the game session and update user stats and points
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT id FROM users WHERE username = %s', (username,))
                    db_result = cur.fetchone()
                    if db_result is None:
                        ip_address = request.remote_addr
                        new_username = generate_username(ip_address)
                        session['username'] = new_username
                        cur.execute('INSERT INTO users (ip_address, username, user_type, points) VALUES (%s, %s, %s, %s)', 
                                  (ip_address, new_username, 'Guest', 0))
                        cur.execute('SELECT id FROM users WHERE username = %s', (new_username,))
                        db_result = cur.fetchone()
                        conn.commit()
                    if db_result:
                        user_id = db_result[0]
                        cur.execute('INSERT INTO game_logs (timestamp, ip_address, username, win, guesses) VALUES (%s, %s, %s, %s, %s)', 
                                  (datetime.now(), request.remote_addr, username, win, len(session['guesses'])))
                        cur.execute('''
                            INSERT INTO user_stats (user_id, wins, losses, total_guesses, games_played)
                            VALUES (%s, %s, %s, %s, 1)
                            ON CONFLICT (user_id) DO UPDATE
                            SET wins = user_stats.wins + EXCLUDED.wins,
                                losses = user_stats.losses + EXCLUDED.losses,
                                total_guesses = user_stats.total_guesses + EXCLUDED.total_guesses,
                                games_played = user_stats.games_played + EXCLUDED.games_played
                        ''', (user_id, win, 1-win, len(session['guesses'])))
                        # Update points based on game outcome
                        cur.execute('UPDATE users SET points = GREATEST(points + %s, 0) WHERE id = %s', (points_change, user_id))
                        conn.commit()
                        print(f"Debug - Game logged: user_id={user_id}, win={win}, guesses={len(session['guesses'])}, points_change={points_change}, username={username}")
                    else:
                        print(f"Debug - Failed to retrieve user_id after creation")
        except psycopg.Error as e:
            print(f"Database logging error: {str(e)}")

    # Generate shareable result
    share_text = f"Wurdle {date.today().strftime('%Y-%m-%d')} {len(session['guesses'])}/6\n"
    for g in session['guesses']:
        share_text += ''.join({
            'green': '🟩', 'yellow': '🟨', 'gray': '⬜'
        }[color] for color in g['result']) + '\n'

    print(f"Debug - Final result before jsonify: {result}, game_over: {game_over}, message: {message}, username={username}")  # Add debugging
    return jsonify({
        'guess': guess,
        'result': result,
        'game_over': game_over,
        'message': message,
        'share_text': share_text
    })

@app.route('/toggle_hard_mode', methods=['POST'])
def toggle_hard_mode():
    if session.get('last_played_date') == str(date.today()):
        return jsonify({'error': 'Cannot change settings. You have already played today.'})
    session['hard_mode'] = not session.get('hard_mode', False)
    session.modified = True
    return jsonify({'hard_mode': session['hard_mode']})

if __name__ == '__main__':
    app.run(debug=True)
