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

# Get database URL from environment, no fallback to avoid local SQLite confusion
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

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
                        win INTEGER,
                        guesses INTEGER
                    )
                ''')
                # Ensure users table exists
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        ip_address TEXT PRIMARY KEY,
                        username TEXT,
                        user_type TEXT DEFAULT 'Guest'
                    )
                ''')
                # Add missing columns if they don't exist
                cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS points INTEGER DEFAULT 0')
                cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS password TEXT')
                # Ensure user_stats table exists with foreign key
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS user_stats (
                        ip_address TEXT PRIMARY KEY,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0,
                        total_guesses INTEGER DEFAULT 0,
                        games_played INTEGER DEFAULT 0,
                        FOREIGN KEY (ip_address) REFERENCES users(ip_address) ON DELETE CASCADE
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
    
    # Clear session if no guesses or new day
    if not session.get('guesses') or (last_played and last_played != today):
        session.clear()
        session['guesses'] = []
        session['game_over'] = False
        session['hard_mode'] = False
        session['last_played_date'] = today if not last_played else None

    # Block only if the game was completed today
    if session.get('last_played_date') == today and session.get('game_over', False):
        return render_template('index.html', game_blocked=True, message="You've already played today's puzzle. Come back tomorrow for a new one!")
    
    return render_template('index.html', game_blocked=False)

@app.route('/wordlist')
def wordlist():
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
    user_type = 'Guest'  # Default initialization
    points = 0  # Default initialization
    if 'username' not in session or not session.get('username'):
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT username, user_type, points FROM users WHERE ip_address = %s', (ip_address,))
                    result = cur.fetchone()
                    if result:
                        session['username'], user_type, points = result
                    else:
                        username = generate_username(ip_address)
                        session['username'] = username
                        cur.execute('INSERT INTO users (ip_address, username, user_type, points) VALUES (%s, %s, %s, %s)', 
                                  (ip_address, username, 'Guest', 0))
                        conn.commit()
                        user_type = 'Guest'
                        points = 0
        except psycopg.Error as e:
            print(f"Database error initializing user: {str(e)}")
            session['username'] = generate_username(ip_address)  # Fallback

    # Fetch user stats from user_stats table
    wins = 0
    losses = 0
    total_guesses = 0
    games_played = 0
    avg_guesses = 0.0
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT wins, losses, total_guesses, games_played FROM user_stats WHERE ip_address = %s', (ip_address,))
                stats = cur.fetchone()
                if stats:
                    wins, losses, total_guesses, games_played = stats
                    avg_guesses = round(total_guesses / games_played, 1) if games_played > 0 else 0.0
                else:
                    # Ensure user exists in users before inserting into user_stats
                    cur.execute('SELECT 1 FROM users WHERE ip_address = %s', (ip_address,))
                    if not cur.fetchone():
                        username = generate_username(ip_address)
                        cur.execute('INSERT INTO users (ip_address, username, user_type, points) VALUES (%s, %s, %s, %s)', 
                                  (ip_address, username, 'Guest', 0))
                    cur.execute('INSERT INTO user_stats (ip_address) VALUES (%s)', (ip_address,))
                    conn.commit()
    except psycopg.Error as e:
        print(f"Database error fetching stats: {str(e)}")

    if request.method == 'POST':
        if 'clear_session' in request.form:
            current_username = session.get('username')
            session.clear()
            session['username'] = current_username
            session['guesses'] = []
            session['game_over'] = False
            session['hard_mode'] = False
            return render_template('profile.html', username=session['username'], message="Session data cleared. Please return to the game.", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)
        elif 'login' in request.form:
            username = request.form.get('login_username', '').strip()
            password = request.form.get('login_password', '')
            if username and password:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            hashed_password = hash_password(password)
                            print(f"Attempting login for {username} with hashed password: {hashed_password}")  # Debug
                            cur.execute('SELECT user_type, points, password FROM users WHERE username = %s', (username,))
                            result = cur.fetchone()
                            if result:
                                stored_user_type, stored_points, stored_password = result
                                print(f"Database entry: user_type={stored_user_type}, points={stored_points}, password={stored_password}")  # Debug
                                if stored_password == hashed_password:
                                    session['username'] = username
                                    cur.execute('UPDATE users SET ip_address = %s WHERE username = %s', (ip_address, username))
                                    conn.commit()
                                    return redirect(url_for('profile'))
                                else:
                                    print(f"Login failed for {username}: Password mismatch")  # Debug
                                    return render_template('profile.html', username=session['username'], message="Invalid username or password.", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)
                            else:
                                print(f"Login failed for {username}: User not found")  # Debug
                                return render_template('profile.html', username=session['username'], message="Invalid username or password.", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)
                except psycopg.Error as e:
                    print(f"Database error during login: {str(e)}")
                    return render_template('profile.html', username=session['username'], message="Error during login.", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)
        elif 'register' in request.form:
            new_username = request.form.get('register_username', '').strip()
            new_password = request.form.get('register_password', '')
            if new_username and new_password and all(c.isalnum() for c in new_username) and 1 <= len(new_username) <= 12:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            cur.execute('SELECT 1 FROM users WHERE username = %s', (new_username,))
                            if cur.fetchone():
                                return render_template('profile.html', username=session['username'], message="Username already taken.", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)
                            cur.execute('INSERT INTO users (ip_address, username, password, user_type, points) VALUES (%s, %s, %s, %s, %s)', 
                                      (ip_address, new_username, hash_password(new_password), 'Member', 0))
                            conn.commit()
                            session['username'] = new_username
                            user_type = 'Member'
                            return render_template('profile.html', username=new_username, message="Registration successful! You are now a Member.", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)
                except psycopg.Error as e:
                    print(f"Database error during registration: {str(e)}")
                    return render_template('profile.html', username=session['username'], message="Error during registration.", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)
        else:
            new_username = request.form.get('username', '').strip()
            if new_username and all(c.isalnum() for c in new_username) and 1 <= len(new_username) <= 12:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            cur.execute('SELECT 1 FROM users WHERE ip_address = %s', (ip_address,))
                            if not cur.fetchone():
                                username = generate_username(ip_address)
                                cur.execute('INSERT INTO users (ip_address, username, user_type, points) VALUES (%s, %s, %s, %s)', 
                                          (ip_address, username, 'Guest', 0))
                            cur.execute('UPDATE users SET username = %s, user_type = %s WHERE ip_address = %s', 
                                      (new_username, 'Member', ip_address))
                            conn.commit()
                    session['username'] = new_username
                    user_type = 'Member'
                    return render_template('profile.html', username=new_username, message="Username updated successfully!", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)
                except psycopg.Error as e:
                    print(f"Database error updating username: {str(e)}")
                    return render_template('profile.html', username=session['username'], message=f"Error updating username: {str(e)}", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)
            else:
                return render_template('profile.html', username=session['username'], message="Username must be 1-12 alphanumeric characters.", wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)

    return render_template('profile.html', username=session['username'], wins=wins, losses=losses, avg_guesses=avg_guesses, user_type=user_type, points=points)

@app.route('/guess', methods=['POST'])
def guess():
    today = str(date.today())
    print(f"Debug - Guess route called, session: {session}")  # Add debugging
    if session.get('last_played_date') == today and session.get('game_over', False):
        return jsonify({'error': 'You have already played today. Come back tomorrow!'})

    if session.get('game_over'):
        return jsonify({'error': 'Game is over. Start a new game.'})

    guess = request.json.get('guess', '').upper()
    print(f"Debug - Received guess: {guess}")  # Add debugging
    hard_mode = session.get('hard_mode', False)
    target = get_daily_word()

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
    result = []
    target_counts = {}
    for letter in target:
        target_counts[letter] = target_counts.get(letter, 0) + 1
    guess_counts = {}

    # First pass: Mark green letters
    for i, (g, t) in enumerate(zip(guess, target)):
        if g == t:
            result.append('green')
            guess_counts[g] = guess_counts.get(g, 0) + 1
        else:
            result.append(None)

    # Second pass: Mark yellow and gray letters
    for i, (g, t) in enumerate(zip(guess, target)):
        if result[i] is None:
            if g in target and guess_counts.get(g, 0) < target_counts.get(g, 0):
                result[i] = 'yellow'
                guess_counts[g] = guess_counts.get(g, 0) + 1
            else:
                result[i] = 'gray'

    session['guesses'].append({'guess': guess, 'result': result})
    session.modified = True

    # Check win/lose conditions
    game_over = False
    message = None
    win = 0
    if guess == target:
        game_over = True
        session['game_over'] = True
        session['last_played_date'] = today
        message = f'Congratulations! You solved it in {len(session["guesses"])} guesses!'
        win = 1
    elif len(session['guesses']) >= 6:
        game_over = True
        session['game_over'] = True
        session['last_played_date'] = today
        message = f'Game over! The word was {target}.'
        win = 0

    if game_over:
        # Log the game session and update user stats
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        INSERT INTO game_logs (timestamp, ip_address, win, guesses)
                        VALUES (%s, %s, %s, %s)
                    ''', (datetime.now(), request.remote_addr, win, len(session['guesses'])))
                    # Ensure user exists in users before updating user_stats
                    cur.execute('SELECT 1 FROM users WHERE ip_address = %s', (request.remote_addr,))
                    if not cur.fetchone():
                        username = generate_username(request.remote_addr)
                        cur.execute('INSERT INTO users (ip_address, username, user_type, points) VALUES (%s, %s, %s, %s)', 
                                  (request.remote_addr, username, 'Guest', 0))
                    # Update user_stats
                    cur.execute('''
                        INSERT INTO user_stats (ip_address, wins, losses, total_guesses, games_played)
                        VALUES (%s, %s, %s, %s, 1)
                        ON CONFLICT (ip_address) DO UPDATE
                        SET wins = user_stats.wins + %s,
                            losses = user_stats.losses + %s,
                            total_guesses = user_stats.total_guesses + %s,
                            games_played = user_stats.games_played + 1
                    ''', (request.remote_addr, win, 1-win, len(session['guesses']), win, 1-win, len(session['guesses'])))
                    conn.commit()
        except psycopg.Error as e:
            print(f"Database logging error: {str(e)}")

    # Generate shareable result
    share_text = f"Wurdle {date.today().strftime('%Y-%m-%d')} {len(session['guesses'])}/6\n"
    for g in session['guesses']:
        share_text += ''.join({
            'green': '🟩', 'yellow': '🟨', 'gray': '⬜'
        }[color] for color in g['result']) + '\n'

    print(f"Debug - Guess result: {result}, game_over: {game_over}, message: {message}")  # Add debugging
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
