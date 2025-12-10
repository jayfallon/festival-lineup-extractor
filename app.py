import os
import csv
import io
import base64
from datetime import datetime
from flask import Flask, request, render_template, Response, send_from_directory, jsonify
from anthropic import Anthropic
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import pg8000
from urllib.parse import urlparse

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
UPLOADS_DIR = os.environ.get('UPLOADS_DIR', os.path.join(os.path.dirname(__file__), 'uploads'))

# Ensure uploads directory exists
os.makedirs(UPLOADS_DIR, exist_ok=True)

client = Anthropic()


def get_db_connection():
    """Get a connection to the PostgreSQL database."""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        return None

    # Parse the URL for pg8000
    result = urlparse(database_url)
    return pg8000.connect(
        host=result.hostname,
        port=result.port or 5432,
        database=result.path[1:],
        user=result.username,
        password=result.password
    )


def check_existing_artists(artist_names: list[str]) -> dict:
    """Check which artists exist in the database and return their details."""
    conn = get_db_connection()
    if not conn:
        return {'existing': [], 'new': artist_names}

    try:
        cursor = conn.cursor()
        # Use case-insensitive matching, return name, slug, and imageUrl
        query = f"""
            SELECT name, slug, "imageUrl" FROM "Artist"
            WHERE LOWER(name) IN ({','.join(['LOWER(%s)'] * len(artist_names))})
        """
        cursor.execute(query, artist_names)
        existing_map = {
            row[0].lower(): {'name': row[0], 'slug': row[1], 'imageUrl': row[2]}
            for row in cursor.fetchall()
        }

        existing = []
        new = []
        for name in artist_names:
            if name.lower() in existing_map:
                existing.append(existing_map[name.lower()])
            else:
                new.append(name)

        return {'existing': existing, 'new': new}
    finally:
        conn.close()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_artists_from_image(image_data: bytes, media_type: str) -> list[str]:
    """Use Claude Vision to extract artist names from a festival lineup image."""
    base64_image = base64.b64encode(image_data).decode('utf-8')

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64_image,
                        },
                    },
                    {
                        "type": "text",
                        "text": """Analyze this festival lineup image and extract ALL artist/performer names you can see.

Rules:
- Extract only artist/band/performer names
- Do NOT include stage names, dates, times, or other text
- List each artist on a new line
- Normalize capitalization to the artist's official/proper spelling (e.g., "Skrillex" not "SKRILLEX", "Four Tet" not "FOUR TET")
- Keep acronyms and stylized names correct (e.g., "SG Lewis", "RÜFÜS DU SOL", "DJ Trixie Mattel", "Aly & AJ")
- If a name appears multiple times, only list it once
- Order them roughly by how prominently they appear (headliners first, then smaller acts)

Return ONLY the list of names, one per line, with no additional text or formatting."""
                    }
                ],
            }
        ],
    )

    # Parse the response - each line is an artist name
    response_text = message.content[0].text
    artists = [line.strip() for line in response_text.strip().split('\n') if line.strip()]
    return artists


def generate_csv(festival_name: str, year: str, artists: list[str]) -> str:
    """Generate CSV content from extracted artist data."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['festival_name', 'edition', 'artist_name'])

    for artist in artists:
        writer.writerow([festival_name, year, artist])

    return output.getvalue()


@app.route('/', methods=['GET'])
def index():
    cloudfront_url = os.environ.get('NEXT_PUBLIC_CLOUDFRONT_URL', '')
    return render_template('index.html', cloudfront_url=cloudfront_url)


@app.route('/uploads', methods=['GET'])
def list_uploads():
    """List all uploaded files."""
    files = []
    for filename in os.listdir(UPLOADS_DIR):
        filepath = os.path.join(UPLOADS_DIR, filename)
        stat = os.stat(filepath)
        files.append({
            'name': filename,
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    files.sort(key=lambda x: x['modified'], reverse=True)
    return {'files': files}


@app.route('/uploads/<filename>', methods=['GET'])
def get_upload(filename):
    """Download a specific uploaded file."""
    return send_from_directory(UPLOADS_DIR, filename)


@app.route('/extract', methods=['POST'])
def extract():
    # Validate file upload
    if 'image' not in request.files:
        return {'error': 'No image file provided'}, 400

    file = request.files['image']
    if file.filename == '':
        return {'error': 'No file selected'}, 400

    if not allowed_file(file.filename):
        return {'error': 'Invalid file type. Allowed: png, jpg, jpeg, gif, webp'}, 400

    # Get form data
    festival_name = request.form.get('festival_name', 'Unknown Festival')
    year = request.form.get('year', '2026')

    # Read image data
    image_data = file.read()

    # Determine media type
    extension = file.filename.rsplit('.', 1)[1].lower()
    media_type_map = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'webp': 'image/webp'
    }
    media_type = media_type_map.get(extension, 'image/jpeg')

    try:
        # Extract artists using Claude Vision
        artists = extract_artists_from_image(image_data, media_type)

        if not artists:
            return {'error': 'No artists found in the image'}, 400

        # Check which artists exist in the database
        artist_check = check_existing_artists(artists)

        # Generate CSV with all artists
        csv_content = generate_csv(festival_name, year, artists)

        # Save uploaded image and CSV to uploads directory
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_festival = secure_filename(festival_name)
        base_filename = f"{safe_festival}_{year}_{timestamp}"

        # Save image
        image_filename = f"{base_filename}.{extension}"
        image_path = os.path.join(UPLOADS_DIR, image_filename)
        with open(image_path, 'wb') as f:
            f.write(image_data)

        # Save CSV
        csv_filename = f"{base_filename}.csv"
        csv_path = os.path.join(UPLOADS_DIR, csv_filename)
        with open(csv_path, 'w', newline='') as f:
            f.write(csv_content)

        # Return JSON with artist breakdown and CSV download path
        return jsonify({
            'success': True,
            'festival_name': festival_name,
            'year': year,
            'existing_artists': artist_check['existing'],
            'new_artists': artist_check['new'],
            'total_artists': len(artists),
            'csv_filename': csv_filename,
            'csv_download': f'/uploads/{csv_filename}'
        })

    except Exception as e:
        return {'error': f'Failed to process image: {str(e)}'}, 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
