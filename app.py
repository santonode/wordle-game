from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import random
from datetime import date, datetime
import os
import io
import base64
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import hashlib
import psycopg
import re

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
                # Check if key tables exist and have data
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'memes'
                    )
                """)
                table_exists = cur.fetchone()[0]
                
                if table_exists:
                    cur.execute("SELECT COUNT(*) FROM memes")
                    meme_count = cur.fetchone()[0]
                    if meme_count > 0:
                        print(f"Memes table already contains {meme_count} records, skipping full reinitialization.")
                    else:
                        print("Memes table exists but is empty, initializing with default data.")
                        cur.execute('DROP TABLE IF EXISTS memes')
                        cur.execute('''
                            CREATE TABLE IF NOT EXISTS memes (
                                meme_id INTEGER PRIMARY KEY,
                                meme_url TEXT NOT NULL,
                                meme_description TEXT NOT NULL,
                                meme_download_counts INTEGER DEFAULT 0,
                                type TEXT DEFAULT 'Other' CHECK (type IN ('Other', 'GM', 'GN', 'Crypto', 'Grawk')),
                                owner INTEGER DEFAULT 3
                            )
                        ''')
                        # Insert default meme with owner
                        cur.execute('''
                            INSERT INTO memes (meme_id, meme_url, meme_description, meme_download_counts, type, owner)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (meme_id) DO NOTHING
                        ''', (1, 'https://drive.google.com/file/d/1rKLbOKw88TKBLKhxnrAVEqxy4ZTB0gLv/view?usp=drive_link', 'Good Morning Good Morning 3', 0, 'GM', 3))
                        conn.commit()
                else:
                    print("Memes table does not exist, creating and initializing.")
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS memes (
                            meme_id INTEGER PRIMARY KEY,
                            meme_url TEXT NOT NULL,
                            meme_description TEXT NOT NULL,
                            meme_download_counts INTEGER DEFAULT 0,
                            type TEXT DEFAULT 'Other' CHECK (type IN ('Other', 'GM', 'GN', 'Crypto', 'Grawk')),
                            owner INTEGER DEFAULT 3
                        )
                    ''')
                    # Insert default meme with owner
                    cur.execute('''
                        INSERT INTO memes (meme_id, meme_url, meme_description, meme_download_counts, type, owner)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (meme_id) DO NOTHING
                    ''', (1, 'https://drive.google.com/file/d/1rKLbOKw88TKBLKhxnrAVEqxy4ZTB0gLv/view?usp=drive_link', 'Good Morning Good Morning 3', 0, 'GM', 3))
                    conn.commit()

                # Initialize other tables (daily_word, game_logs, users, user_stats) only if they don't exist
                cur.execute('DROP TABLE IF EXISTS daily_word')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS daily_word (
                        date TEXT NOT NULL,
                        word_list TEXT NOT NULL,
                        word TEXT NOT NULL,
                        PRIMARY KEY (date, word_list)
                    )
                ''')
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
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        ip_address TEXT,
                        username TEXT UNIQUE,
                        user_type TEXT DEFAULT 'Guest',
                        points INTEGER DEFAULT 0,
                        password TEXT,
                        word_list TEXT DEFAULT 'words.txt'
                    )
                ''')
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

# Load word lists
try:
    with open('words.txt', 'r') as f:
        WORDS_ALL = [word.strip().upper() for word in f.readlines()]
    with open('words-pets.txt', 'r') as f:
        WORDS_PETS = [word.strip().upper() for word in f.readlines()]
except FileNotFoundError as e:
    print(f"Error: {str(e)}")
    WORDS_ALL = ['APPLE', 'BREAD', 'CLOUD', 'DREAM']  # Fallback list
    WORDS_PETS = ['DOG', 'CAT', 'BIRD', 'FISH']  # Fallback list

# Get or set daily word based on selected word list
def get_daily_word():
    today = str(date.today())
    word_list = session.get('word_list', 'words.txt')  # Default to words.txt
    available_words = WORDS_ALL if word_list == 'words.txt' else WORDS_PETS
    print(f"Attempting to get daily word for {today} with list {word_list}")
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT word FROM daily_word WHERE date = %s AND word_list = %s', (today, word_list))
                result = cur.fetchone()
                if result:
                    word = result[0]
                    print(f"Found existing word: {word}")
                    return word
                else:
                    word = random.choice(available_words)
                    cur.execute('INSERT INTO daily_word (date, word_list, word) VALUES (%s, %s, %s)', (today, word_list, word))
                    conn.commit()
                    print(f"Inserted new word: {word}")
                    return word
    except psycopg.Error as e:
        print(f"Database error in get_daily_word: {str(e)}")
        return random.choice(available_words)  # Fallback to random word
    except Exception as e:
        print(f"Unexpected error in get_daily_word: {str(e)}")
        return random.choice(available_words)  # Fallback to random word

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

# Get next available ID for a table
def get_next_id(table_name):
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Use the actual primary key column name (e.g., meme_id for memes table)
                column_name = {'memes': 'meme_id', 'users': 'id'}.get(table_name.split('_')[0], f"{table_name.split('_')[0]}_id")
                cur.execute(f'SELECT COALESCE(MAX({column_name}), 0) + 1 FROM {table_name}')
                return cur.fetchone()[0]
    except psycopg.Error as e:
        print(f"Database error getting next {table_name.split('_')[0]} ID: {str(e)}")
        return 1  # Fallback to 1 if error occurs

# Custom filter to transform Google Drive URL to download link
def get_download_url(url):
    if url and 'drive.google.com/file/d/' in url:
        match = re.search(r'https://drive.google.com/file/d/([^/]+)/view\?usp=drive_link', url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

# Register the custom filter
app.jinja_env.filters['get_download_url'] = get_download_url

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
    user_type = session.get('user_type', 'Guest')  # Default from session
    points = 0  # Default points
    word_list = session.get('word_list', 'words.txt')  # Default to words.txt
    
    # Clear session if no guesses or new day, but preserve username if it exists
    if not session.get('guesses') or (last_played and last_played != today):
        session['guesses'] = []
        session['game_over'] = False
        session['hard_mode'] = False
        session['last_played_date'] = today if not last_played else None
        if not username:
            ip_address = request.remote_addr
            username = generate_username(ip_address)
            session['username'] = username
            print(f"Debug - New username generated: {username}")  # Debug
            # No database write here, only set in session
        else:
            # Fetch user_type, points, and word_list for existing username if already in DB
            try:
                with psycopg.connect(DATABASE_URL) as conn:
                    with conn.cursor() as cur:
                        cur.execute('SELECT user_type, points, word_list FROM users WHERE username = %s', (username,))
                        result = cur.fetchone()
                        if result:
                            user_type, points, db_word_list = result
                            session['user_type'] = user_type  # Update session
                            session['word_list'] = db_word_list  # Update session with word list
                            print(f"Debug - Fetched user_type: {user_type}, points: {points}, word_list: {db_word_list} for {username}")
            except psycopg.Error as e:
                print(f"Database error fetching user_type: {str(e)}")

    # Block only if the game was completed today for the current user, pass share_text
    share_text = session.get('share_text') if session.get('game_over') else None
    print(f"Debug - Session guesses: {session.get('guesses')}, game_over: {session.get('game_over')}")  # Debug
    if username and session.get('last_played_date') == today and session.get('game_over', False):
        return render_template('index.html', game_blocked=True, message="You've already played today's puzzle. Use 'Clear Session' to test again!", username=username, user_type=user_type, points=points if user_type != 'Guest' else None, share_text=share_text, guesses=session.get('guesses', []), game_over=session.get('game_over', False), word_list=word_list)
    
    return render_template('index.html', game_blocked=False, username=username, user_type=user_type, points=points if user_type != 'Guest' else None, share_text=share_text, guesses=session.get('guesses', []), game_over=session.get('game_over', False), word_list=word_list)

@app.route('/wordlist')
def wordlist():
    username = session.get('username')
    if username:
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT id, user_type FROM users WHERE username = %s', (username,))
                    result = cur.fetchone()
                    if result:
                        user_id, user_type = result
                        if user_type != 'Guest':  # Deduct points only for non-guest users
                            cur.execute('UPDATE users SET points = GREATEST(points - 1, 0) WHERE id = %s', (user_id,))
                            conn.commit()
                            print(f"Debug - Deducted 1 point for user {username}, new points: {cur.execute('SELECT points FROM users WHERE id = %s', (user_id,)).fetchone()[0]}")
        except psycopg.Error as e:
            print(f"Database error deducting point for wordlist: {str(e)}")
    word_list = session.get('word_list', 'words.txt')
    words = WORDS_ALL if word_list == 'words.txt' else WORDS_PETS
    return render_template('wordlist.html', words=words)

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
    username = session.get('username')
    user_type = session.get('user_type', 'Guest')  # Default from session
    points = 0  # Default points
    word_list = session.get('word_list', 'words.txt')  # Default to words.txt

    if not username:
        username = generate_username(ip_address)
        session['username'] = username
        # No database write here, only set in session
    else:
        # Fetch user_type, points, and word_list for existing username if already in DB
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT user_type, points, word_list FROM users WHERE username = %s', (username,))
                    result = cur.fetchone()
                    if result:
                        user_type, points, db_word_list = result
                        session['user_type'] = user_type  # Update session
                        session['word_list'] = db_word_list  # Update session with word list
        except psycopg.Error as e:
            print(f"Database error fetching user_type: {str(e)}")

    wins = 0
    losses = 0
    total_guesses = 0
    games_played = 0
    avg_guesses = 0.0
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM users WHERE username = %s', (username,))
                user_id = cur.fetchone()
                if user_id:
                    user_id = user_id[0]
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
            session['user_type'] = user_type  # Preserve user_type
            session['word_list'] = word_list  # Preserve word_list
            session['guesses'] = []
            session['game_over'] = False
            session['hard_mode'] = False
            message = "Session data cleared. Please return to the game."
        elif 'login' in request.form:
            username = request.form.get('login_username', '').strip()
            password = request.form.get('login_password', '')
            if username and password:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            hashed_password = hash_password(password)
                            print(f"Attempting login for {username} with hashed password: {hashed_password}")
                            cur.execute('SELECT user_type, points, password, word_list FROM users WHERE username = %s', (username,))
                            result = cur.fetchone()
                            if result:
                                stored_user_type, stored_points, stored_password, stored_word_list = result
                                if stored_password == hashed_password:
                                    session.clear()  # Always clear session on login
                                    session['username'] = username  # Update to registered username
                                    session['user_type'] = stored_user_type  # Set to 'Member' for registered users
                                    session['word_list'] = stored_word_list  # Set to stored word list
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
                                cur.execute('INSERT INTO users (ip_address, username, password, user_type, points, word_list) VALUES (%s, %s, %s, %s, %s, %s)', 
                                          (ip_address, new_username, hash_password(new_password), 'Member', 0, 'words.txt'))
                                cur.execute('INSERT INTO user_stats (user_id) VALUES (currval(\'users_id_seq\'))')
                                conn.commit()
                                session.clear()  # Clear session on registration
                                session['username'] = new_username  # Update to registered username
                                session['user_type'] = 'Member'
                                session['word_list'] = 'words.txt'  # Default word list for new users
                                user_type = 'Member'
                                points = 0
                                message = "Registration successful! You are now a Member."
                except psycopg.Error as e:
                    print(f"Database error during registration: {str(e)}")
                    message = "Error during registration."
        elif 'change_word_list' in request.form:
            new_word_list = request.form.get('word_list')
            if new_word_list in ['words.txt', 'words-pets.txt']:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            cur.execute('UPDATE users SET word_list = %s WHERE username = %s', (new_word_list, username))
                            conn.commit()
                            session['word_list'] = new_word_list  # Update session
                            session['guesses'] = []  # Clear guesses to reset game
                            session['game_over'] = False
                            session['last_played_date'] = None  # Allow new game
                            message = f"Word list changed to {new_word_list.split('-')[0] if '-' in new_word_list else new_word_list}. Game reset!"
                except psycopg.Error as e:
                    print(f"Database error changing word list: {str(e)}")
                    message = "Error changing word list."

    return render_template('profile.html', username=session['username'], user_type=user_type, points=points, message=message, wins=wins, losses=losses, avg_guesses=avg_guesses, word_list=word_list)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    message = None
    authenticated = session.get('admin_authenticated', False)

    # Get next available meme ID for the template
    next_meme_id = get_next_id('memes')

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
            new_points = request.form.get('new_points', 0, type=int)
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
        elif 'delete_meme' in request.form:
            delete_meme_id = request.form.get('delete_meme_id', type=int)
            try:
                with psycopg.connect(DATABASE_URL) as conn:
                    with conn.cursor() as cur:
                        cur.execute('DELETE FROM memes WHERE meme_id = %s', (delete_meme_id,))
                        if cur.rowcount > 0:
                            conn.commit()
                            message = f"Meme with ID {delete_meme_id} deleted successfully."
                        else:
                            message = f"Meme with ID {delete_meme_id} not found."
            except psycopg.Error as e:
                print(f"Database error during meme delete: {str(e)}")
                message = f"Error deleting meme with ID {delete_meme_id}: {str(e)}"
        elif 'save_meme' in request.form:
            meme_id = request.form.get('edit_meme_id' if 'edit_meme_id' in request.form else 'new_meme_id', type=int)
            new_type = request.form.get('new_type').strip()
            new_description = request.form.get('new_description').strip()
            new_meme_url = request.form.get('new_meme_url')
            new_owner = request.form.get('new_owner', type=int)
            new_download_counts = request.form.get('new_download_counts', 0, type=int)
            if new_meme_url is None:
                new_meme_url = ''
            new_meme_url = new_meme_url.strip() if new_meme_url else ''
            valid_types = ['Other', 'GM', 'GN', 'Crypto', 'Grawk']
            if new_type in valid_types and new_description and new_meme_url and new_owner is not None:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            if 'edit_meme_id' in request.form:
                                cur.execute('UPDATE memes SET type = %s, meme_description = %s, meme_url = %s, owner = %s, meme_download_counts = %s WHERE meme_id = %s',
                                          (new_type, new_description, new_meme_url, new_owner, new_download_counts, meme_id))
                                if cur.rowcount > 0:
                                    conn.commit()
                                    message = f"Meme with ID {meme_id} updated successfully."
                                else:
                                    message = f"Meme with ID {meme_id} not found."
                            elif 'add_meme' in request.form:
                                cur.execute('SELECT 1 FROM memes WHERE meme_id = %s', (meme_id,))
                                if cur.fetchone():
                                    message = f"Meme ID {meme_id} already exists."
                                else:
                                    cur.execute('INSERT INTO memes (meme_id, meme_url, meme_description, meme_download_counts, type, owner) VALUES (%s, %s, %s, %s, %s, %s)',
                                              (meme_id, new_meme_url, new_description, new_download_counts, new_type, new_owner))
                                    conn.commit()
                                    message = f"Meme added successfully with ID {meme_id}."
                except psycopg.Error as e:
                    print(f"Database error during meme update/add: {str(e)}")
                    message = f"Error {'updating' if 'edit_meme_id' in request.form else 'adding'} meme with ID {meme_id}: {str(e)}"
            else:
                message = "Invalid type, empty description, empty URL, or invalid owner ID. Type must be one of: Other, GM, GN, Crypto, Grawk. Owner ID must be a valid integer."
        elif 'save_user' in request.form and 'add_user' in request.form:
            new_username = request.form.get('new_username').strip()
            new_password = request.form.get('new_password')
            new_points = request.form.get('new_points', 0, type=int)
            if new_username and new_password and all(c.isalnum() for c in new_username) and 1 <= len(new_username) <= 12:
                try:
                    with psycopg.connect(DATABASE_URL) as conn:
                        with conn.cursor() as cur:
                            cur.execute('SELECT 1 FROM users WHERE username = %s', (new_username,))
                            if cur.fetchone():
                                message = "Username already taken."
                            else:
                                new_user_id = get_next_id('users')
                                cur.execute('INSERT INTO users (id, ip_address, username, password, user_type, points, word_list) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                                          (new_user_id, request.remote_addr, new_username, hash_password(new_password), 'Member', new_points, 'words.txt'))
                                cur.execute('INSERT INTO user_stats (user_id) VALUES (%s)', (new_user_id,))
                                conn.commit()
                                message = f"User {new_username} added successfully with ID {new_user_id}."
                except psycopg.Error as e:
                    print(f"Database error during user add: {str(e)}")
                    message = f"Error adding user {new_username}: {str(e)}"
            else:
                message = "Username must be 1-12 alphanumeric characters."

    if not authenticated:
        return render_template('admin.html', authenticated=False, message=message)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id, username, password, points FROM users')
                users = [{'id': row[0], 'username': row[1], 'password': row[2], 'points': row[3]} for row in cur.fetchall()]
                cur.execute('SELECT meme_id, type, meme_description, meme_download_counts, meme_url, owner FROM memes ORDER BY meme_id')
                memes = [{'meme_id': row[0], 'type': row[1], 'meme_description': row[2], 'meme_download_counts': row[3], 'meme_url': row[4], 'owner': row[5]} for row in cur.fetchall()]
                print(f"Debug - Memes fetched in admin: {memes}")
        return render_template('admin.html', authenticated=True, users=users, memes=memes, message=message, next_meme_id=next_meme_id)
    except psycopg.Error as e:
        print(f"Database error in admin: {str(e)}")
        message = "Error fetching user or meme data."
        return render_template('admin.html', authenticated=True, users=[], memes=[], message=message, next_meme_id=next_meme_id)

@app.route('/guess', methods=['POST'])
def guess():
    today = str(date.today())
    print(f"Debug - Guess route called, session: {session}")  # Add debugging
    username = session.get('username')
    user_type = session.get('user_type', 'Guest')  # Preserve user_type from session
    ip_address = request.remote_addr  # Define ip_address at the start of the route
    word_list = session.get('word_list', 'words.txt')  # Get current word list
    
    # Initialize guest user in database only if not already present
    if not username:
        username = generate_username(ip_address)
        session['username'] = username
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT 1 FROM users WHERE username = %s', (username,))
                if not cur.fetchone():
                    cur.execute('INSERT INTO users (ip_address, username, user_type, points, word_list) VALUES (%s, %s, %s, %s, %s)',
                              (ip_address, username, 'Guest', 0, word_list))
                    cur.execute('INSERT INTO user_stats (user_id) VALUES (currval(\'users_id_seq\'))')
                    conn.commit()
                else:
                    cur.execute('SELECT user_type, word_list FROM users WHERE username = %s', (username,))
                    user_type, db_word_list = cur.fetchone()
                    session['user_type'] = user_type  # Update session
                    session['word_list'] = db_word_list  # Update session with word list
    except psycopg.Error as e:
        print(f"Database error creating or fetching guest user: {str(e)}")
        return jsonify({'error': 'Database error. Please try again later.'})

    if session.get('last_played_date') == today and session.get('game_over', False):
        return jsonify({'error': 'You have already played today. Use \'Clear Session\' to test again!'})

    if session.get('game_over'):
        return jsonify({'error': 'Game is over. Start a new game.'})

    guess = request.json.get('guess', '').upper()
    print(f"Debug - Received guess: {guess}, username: {username}")  # Add debugging
    hard_mode = session.get('hard_mode', False)
    target = get_daily_word()
    print(f"Debug - Target word: {target}, username: {username}")  # Add target for debugging

    available_words = WORDS_ALL if word_list == 'words.txt' else WORDS_PETS
    if len(guess) != 5 or guess not in available_words:
        print(f"Debug - Invalid guess: {guess}, length: {len(guess)}, in WORDS: {guess in available_words}, username: {username}")  # Add debugging
        return jsonify({'error': 'Invalid word. Must be a 5-letter word from the selected list.'})

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
    print(f"Debug - After first pass, result: {result}, all_green: {all_green}, username: {username}")  # Debug after first pass

    # Second pass: Mark yellow letters only if not all green
    if not all_green:
        for i, (g, t) in enumerate(zip(guess, target)):
            if result[i] == 'gray' and g in target and guess_counts.get(g, 0) < target_counts.get(g, 0):
                result[i] = 'yellow'
                guess_counts[g] = guess_counts.get(g, 0) + 1
    print(f"Debug - After second pass, result: {result}, username: {username}")  # Debug after second pass

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
                    cur.execute('SELECT id, user_type FROM users WHERE username = %s', (username,))
                    db_result = cur.fetchone()
                    if db_result:
                        user_id, user_type = db_result
                    else:
                        cur.execute('INSERT INTO users (ip_address, username, user_type, points, word_list) VALUES (%s, %s, %s, %s, %s)',
                                  (ip_address, username, user_type, 0, word_list))
                        cur.execute('INSERT INTO user_stats (user_id) VALUES (currval(\'users_id_seq\'))')
                        conn.commit()
                        cur.execute('SELECT id, user_type FROM users WHERE username = %s', (username,))
                        user_id, user_type = cur.fetchone()
                    session['user_type'] = user_type  # Update session to match DB
                    if user_type != 'Guest':  # Ensure points are updated only for the intended user
                        cur.execute('INSERT INTO game_logs (timestamp, ip_address, username, win, guesses) VALUES (%s, %s, %s, %s, %s)', 
                                  (datetime.now(), ip_address, username, win, len(session['guesses'])))
                        cur.execute('''
                            INSERT INTO user_stats (user_id, wins, losses, total_guesses, games_played)
                            VALUES (%s, %s, %s, %s, 1)
                            ON CONFLICT (user_id) DO UPDATE
                            SET wins = user_stats.wins + EXCLUDED.wins,
                                losses = user_stats.losses + EXCLUDED.losses,
                                total_guesses = user_stats.total_guesses + EXCLUDED.total_guesses,
                                games_played = user_stats.games_played + EXCLUDED.games_played
                        ''', (user_id, win, 1-win, len(session['guesses'])))
                        cur.execute('UPDATE users SET points = GREATEST(points + %s, 0) WHERE id = %s', (points_change, user_id))
                        conn.commit()
                        print(f"Debug - Game logged: user_id={user_id}, win={win}, guesses={len(session['guesses'])}, points_change={points_change}, username={username}, user_type={user_type}")
                    else:
                        print(f"Debug - Skipping points update for guest user: {username}")
        except psycopg.Error as e:
            print(f"Database logging error: {str(e)}")

    # Generate and store shareable result in session
    share_text = f"Wurdle {date.today().strftime('%Y-%m-%d')} {len(session['guesses'])}/6\n"
    for g in session['guesses']:
        share_text += ''.join({
            'green': '🟩', 'yellow': '🟨', 'gray': '⬜'
        }[color] for color in g['result']) + '\n'
    session['share_text'] = share_text  # Store for display

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

# Handle favicon request to prevent 500 error (optional, add static file for best practice)
@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')  # Ensure static/favicon.ico exists

@app.route('/leader')
def leader():
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Fetch users sorted by points in descending order
                cur.execute('SELECT id, username, points FROM users ORDER BY points DESC')
                leaders = [{'id': row[0], 'username': row[1], 'points': row[2]} for row in cur.fetchall()]
        return render_template('leader.html', leaders=leaders)
    except psycopg.Error as e:
        print(f"Database error in leader: {str(e)}")
        return render_template('leader.html', leaders=[])
    except Exception as e:
        print(f"Unexpected error in leader: {str(e)}")
        return render_template('leader.html', leaders=[])

@app.route('/memes')
def memes():
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT meme_id, meme_url, meme_description, meme_download_counts, type, owner FROM memes ORDER BY meme_id')
                memes = [{'meme_id': row[0], 'meme_url': row[1], 'meme_description': row[2], 'meme_download_counts': row[3], 'type': row[4], 'owner': row[5]} for row in cur.fetchall()]
                cur.execute('SELECT id, username FROM users')
                users = [{'id': row[0], 'username': row[1]} for row in cur.fetchall()]
                # Calculate total meme count and total downloads
                cur.execute('SELECT COUNT(*) FROM memes')
                meme_count = cur.fetchone()[0]
                # Verify count against fetched data for debugging
                verified_count = len(memes)
                if meme_count != verified_count:
                    print(f"Warning: Meme count mismatch - SQL COUNT: {meme_count}, Fetched rows: {verified_count}")
                    meme_count = verified_count  # Use fetched count if mismatch
                cur.execute('SELECT SUM(meme_download_counts) FROM memes')
                total_downloads = cur.fetchone()[0] or 0  # Default to 0 if NULL
                print(f"Debug - Memes fetched: {memes}, users: {users}, meme_count: {meme_count}, total_downloads: {total_downloads}")
        
        # Retrieve session data for username display
        username = session.get('username')
        user_type = session.get('user_type', 'Guest')  # Default to 'Guest'
        points = 0  # Default points
        if username:
            try:
                with psycopg.connect(DATABASE_URL) as conn:
                    with conn.cursor() as cur:
                        cur.execute('SELECT user_type, points FROM users WHERE username = %s', (username,))
                        result = cur.fetchone()
                        if result:
                            user_type, points = result
                            session['user_type'] = user_type  # Update session
            except psycopg.Error as e:
                print(f"Database error fetching user_type for memes: {str(e)}")

        return render_template('memes.html', memes=memes, users=users, meme_count=meme_count, total_downloads=total_downloads, username=username, user_type=user_type, points=points if user_type != 'Guest' else None, message=None)
    except psycopg.Error as e:
        print(f"Database error in memes: {str(e)}")
        return render_template('memes.html', memes=[], users=[], message="Error fetching meme data.", meme_count=0, total_downloads=0, username=None, user_type='Guest', points=0)
    except Exception as e:
        print(f"Unexpected error in memes: {str(e)}")
        return render_template('memes.html', memes=[], users=[], message="Error fetching meme data.", meme_count=0, total_downloads=0, username=None, user_type='Guest', points=0)

@app.route('/add_point_and_redirect/<int:meme_id>/<path:url>')
def add_point_and_redirect(meme_id, url):
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Update download count for the specific meme_id
                cur.execute(
                    'UPDATE memes SET meme_download_counts = meme_download_counts + 1 WHERE meme_id = %s',
                    (meme_id,)
                )
                conn.commit()
                print(f"Debug - Incremented download count for meme_id {meme_id} to {cur.rowcount}")
        # Redirect to the original URL
        return redirect(url, code=302)
    except psycopg.Error as e:
        print(f"Database error in add_point_and_redirect: {str(e)}")
        return "Error updating download count", 500
    except Exception as e:
        print(f"Unexpected error in add_point_and_redirect: {str(e)}")
        return "Error updating download count", 500

@app.route('/increment_download/<int:meme_id>', methods=['POST'])
def increment_download(meme_id):
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Update download count for the specific meme_id
                cur.execute(
                    'UPDATE memes SET meme_download_counts = meme_download_counts + 1 WHERE meme_id = %s',
                    (meme_id,)
                )
                conn.commit()
                print(f"Debug - Incremented download count for meme_id {meme_id} to {cur.rowcount}")
        return jsonify({'success': True})
    except psycopg.Error as e:
        print(f"Database error in increment_download: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        print(f"Unexpected error in increment_download: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
