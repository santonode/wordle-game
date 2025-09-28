import os
import base64
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import psycopg

# Environment variables
DATABASE_URL = os.environ.get('DATABASE_URL')
GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '1jAJuHGXxcrHgy9rb8EOOjWM2pn3o9xo4')
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')

# Subfolder mapping to type
SUBFOLDER_TO_TYPE = {
    'Crypto': 'Crypto',
    'GM': 'GM',
    'GN': 'GN',
    'Grawk': 'Grawk',
    'Other': 'Other'
}

def get_drive_service():
    """Authenticate and return Google Drive service."""
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable is required.")
    
    # Decode the service account JSON
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(base64.b64decode(GOOGLE_SERVICE_ACCOUNT_JSON).decode('utf-8')),
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    
    return build('drive', 'v3', credentials=credentials)

def fetch_files_from_folder(service, folder_id, folder_name=''):
    """Recursively fetch files from a folder and subfolders."""
    files = []
    try:
        # List files in the current folder
        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id, name, webViewLink, parents, mimeType)"
        ).execute()
        
        for file in results.get('files', []):
            if file['mimeType'] != 'application/vnd.google-apps.folder':  # Skip folders
                files.append({
                    'name': file['name'],
                    'url': file['webViewLink'],
                    'description': file['name'],  # Use name as description
                    'type': SUBFOLDER_TO_TYPE.get(folder_name, 'Other')
                })
            else:
                # Recurse into subfolder
                subfolder_files = fetch_files_from_folder(service, file['id'], file['name'])
                files.extend(subfolder_files)
    except Exception as e:
        print(f"Error fetching files from {folder_id}: {e}")
    
    return files

def preview_meme_sync(existing_meme_urls, new_files):
    """Display a preview of new memes to be added."""
    new_memes = [f for f in new_files if f['url'] not in existing_meme_urls]
    if not new_memes:
        print("No new memes to add. All files are already in the database.")
        return False
    
    print("\n=== Preview of New Memes to be Added ===")
    print("Date: 09:18 AM EDT, Sunday, September 28, 2025")
    print("The following memes will be added to the database:")
    print("------------------------------------------------")
    for meme in new_memes:
        print(f"ID: [Next Available], Type: {meme['type']}, Description: {meme['description']}, URL: {meme['url']}, Download Counts: 0")
    print("------------------------------------------------")
    print(f"Total new memes: {len(new_memes)}")
    
    # Prompt for confirmation
    confirm = input("\nDo you want to proceed with these changes? (yes/no): ").lower().strip()
    return confirm == 'yes'

def sync_meme_to_database(new_memes):
    """Add new memes to the database."""
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                for meme in new_memes:
                    # Get next meme_id
                    cur.execute('SELECT COALESCE(MAX(meme_id), 0) + 1 FROM memes')
                    next_id = cur.fetchone()[0]
                    
                    cur.execute('''
                        INSERT INTO memes (meme_id, meme_url, meme_description, meme_download_counts, type)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (next_id, meme['url'], meme['description'], 0, meme['type']))
                conn.commit()
                print(f"Successfully added {len(new_memes)} new memes to the database.")
    except psycopg.Error as e:
        print(f"Database error during sync: {e}")
        raise

def main():
    """Main function to sync memes from Google Drive."""
    # Initialize Drive service
    service = get_drive_service()
    
    # Fetch existing meme URLs from database
    existing_meme_urls = set()
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT meme_url FROM memes')
                existing_meme_urls = {row[0] for row in cur.fetchall()}
    except psycopg.Error as e:
        print(f"Error fetching existing memes: {e}")
        return

    # Fetch files from Google Drive
    files = fetch_files_from_folder(service, GOOGLE_DRIVE_FOLDER_ID)
    if not files:
        print("No files found in the specified Google Drive folder.")
        return

    # Preview and sync
    if preview_meme_sync(existing_meme_urls, files):
        new_memes = [f for f in files if f['url'] not in existing_meme_urls]
        if new_memes:
            sync_meme_to_database(new_memes)
        else:
            print("No new memes to sync after confirmation.")
    else:
        print("Sync aborted by user.")

if __name__ == '__main__':
    main()
