from flask import Flask, render_template, request, jsonify, session
import random
from datetime import date, datetime
import sqlite3
import os
import io
import base64
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import hashlib

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize SQLite database
def init_db():
    try:
        with sqlite3.connect('wordle.db') as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS daily_word (
                date TEXT PRIMARY KEY,
                word TEXT NOT NULL
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS game_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                ip_address TEXT,
                win INTEGER,
                guesses INTEGER
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                ip_address TEXT PRIMARY KEY,
                username TEXT NOT NULL
            )''')
            conn.commit()
    except sqlite3.Error as e:
        print(f"Database initialization error: {e}")

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
    try:
        with sqlite3.connect('wordle.db') as conn:
            c = conn.cursor()
            c.execute('SELECT word FROM daily_word WHERE date = ?', (today,))
            result = c.fetchone()
            if result:
                return result[0]
            else:
                word = random.choice(WORDS)
                c.execute('INSERT INTO daily_word (date, word) VALUES (?, ?)', (today, word))
                conn.commit()
                return word
    except sqlite3.Error as e:
        print(f"Database error in get_daily_word: {e}")
        return random.choice(WORDS)  # Fallback to random word

# Generate username based on IP and session data
def generate_username(ip_address):
    seed = f"{ip_address}{datetime.now().microsecond}{random.randint(1000, 9999)}"
    hash_object = hashlib.md5(seed.encode())
    hash_hex = hash_object.hexdigest()[:8]  # Take first 8 characters for brevity
    # Convert to alphanumeric by mapping to base36 and filtering
    username = ''.join(c for c in hash_hex if c.isalnum()).upper()[:12]
    return username

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
    
    # Check if user has already played today
    if last_played == today:
        return render_template('index.html', game_blocked=True, message="You've already played today's puzzle. Come back tomorrow for a new one!")
    
    # Initialize session safely
    if 'guesses' not in session:
        session['guesses'] = []
    if 'game_over' not in session:
        session['game_over'] = False
    if 'hard_mode' not in session:
        session['hard_mode'] = session.get('hard_mode', False)
    return render_template('index.html', game_blocked=False)

@app.route('/wordlist')
def wordlist():
    return render_template('wordlist.html', words=WORDS)

@app.route('/stats')
def stats():
    try:
        with sqlite3.connect('wordle.db') as conn:
            c = conn.cursor()
            c.execute('''SELECT date(timestamp) as day, 
                         SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
                         SUM(CASE WHEN win = 0 THEN 1 ELSE 0 END) as losses
                         FROM game_logs GROUP BY day ORDER BY day''')
            data = c.fetchall()
            c.execute('SELECT COUNT(*) FROM game_logs')
            total_games = c.fetchone()[0]
        
        if not data:
            return render_template('stats.html', chart=None)
        
        days = [row[0] for row in data]
        wins = [row[1] for row in data]
        losses = [row[2] for row in data]
        
        fig, ax = plt.subplots(figsize=(12, 6))
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
        plt.savefig(buf, format='png')
        buf.seek(0)
        chart = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close(fig)
        
        return render_template('stats.html', chart=chart)
    except sqlite3.Error as e:
        print(f"Database error in stats: {e}")
        return render_template('stats.html', chart=None)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    ip_address = request.remote_addr
    if 'username' not in session or not session.get('username'):
        try:
            with sqlite3.connect('wordle.db') as conn:
                c = conn.cursor()
                c.execute('SELECT username FROM users WHERE ip_address = ?', (ip_address,))
                result = c.fetchone()
                if result:
                    session['username'] = result[0]
                else:
                    username = generate_username(ip_address)
                    session['username'] = username
                    c.execute('INSERT INTO users (ip_address, username) VALUES (?, ?)', (ip_address, username))
                    conn.commit()
        except sqlite3.Error as e:
            print(f"Database error in profile: {e}")
            session['username'] = generate_username(ip_address)  # Fallback

    if request.method == 'POST':
        new_username = request.form.get('username', '').strip()
        if new_username and all(c.isalnum() for c in new_username) and 1 <= len(new_username) <= 12:
            try:
                with sqlite3.connect('wordle.db') as conn:
                    c = conn.cursor()
                    c.execute('UPDATE users SET username = ? WHERE ip_address = ?', (new_username, ip_address))
                    conn.commit()
                session['username'] = new_username
                return render_template('profile.html', username=new_username, message="Username updated successfully!")
            except sqlite3.Error as e:
                print(f"Database error updating username: {e}")
                return render_template('profile.html', username=session['username'], message="Error updating username.")
        else:
            return render_template('profile.html', username=session['username'], message="Username must be 1-12 alphanumeric characters.")

    return render_template('profile.html', username=session['username'])

@app.route('/guess', methods=['POST'])
def guess():
    today = str(date.today())
    if session.get('last_played_date') == today:
        return jsonify({'error': 'You have already played today. Come back tomorrow!'})

    if session.get('game_over'):
        return jsonify({'error': 'Game is over. Start a new game.'})

    guess = request.json.get('guess', '').upper()
    hard_mode = session.get('hard_mode', False)
    target = get_daily_word()

    if len(guess) != 5 or guess not in WORDS:
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
        # Log the game session
        try:
            with sqlite3.connect('wordle.db') as conn:
                c = conn.cursor()
                c.execute('''INSERT INTO game_logs (timestamp, ip_address, win, guesses)
                             VALUES (?, ?, ?, ?)''', 
                          (datetime.now(), request.remote_addr, win, len(session['guesses'])))
                conn.commit()
        except sqlite3.Error as e:
            print(f"Database logging error: {e}")

    # Generate shareable result
    share_text = f"Wurdle {date.today().strftime('%Y-%m-%d')} {len(session['guesses'])}/6\n"
    for g in session['guesses']:
        share_text += ''.join({
            'green': '🟩', 'yellow': '🟨', 'gray': '⬜'
        }[color] for color in g['result']) + '\n'

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
