from flask import Flask, render_template, request, jsonify, session
import random
from datetime import date
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize SQLite database
def init_db():
with sqlite3.connect('wordle.db') as conn:
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS daily_word (
date TEXT PRIMARY KEY,
word TEXT NOT NULL
)''')
conn.commit()

# Load word list
with open('words.txt', 'r') as f:
WORDS = [word.strip().upper() for word in f.readlines()]

# Get or set daily word
def get_daily_word():
today = str(date.today())
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

@app.route('/')
def index():
session['guesses'] = []
session['game_over'] = False
session['hard_mode'] = False
return render_template('index.html')

@app.route('/guess', methods=['POST'])
def guess():
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
if guess == target:
game_over = True
session['game_over'] = True
message = f'Congratulations! You solved it in {len(session["guesses"])} guesses!'
elif len(session['guesses']) >= 6:
game_over = True
session['game_over'] = True
message = f'Game over! The word was {target}.'

# Generate shareable result
share_text = f"Wordle {date.today().strftime('%Y-%m-%d')} {len(session['guesses'])}/6\n"
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
session['hard_mode'] = not session.get('hard_mode', False)
session.modified = True
return jsonify({'hard_mode': session['hard_mode']})

if __name__ == '__main__':
init_db()
app.run(debug=True)
