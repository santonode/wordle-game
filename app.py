from flask import Flask
from wurdle import wurdle_bp
from memes import memes_bp, init_db
import os

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.urandom(24)

# Register blueprints
app.register_blueprint(wurdle_bp)
app.register_blueprint(memes_bp)

# Register the custom filter with the app's Jinja environment
def get_download_url(url):
    if url and 'drive.google.com/file/d/' in url:
        match = re.search(r'https://drive.google.com/file/d/([^/]+)/view\?usp=drive_link', url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

app.jinja_env.filters['get_download_url'] = get_download_url

# Initialize database within app context
with app.app_context():
    init_db()

# Configure port for Render
port = int(os.getenv("PORT", 5000))
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=port)
