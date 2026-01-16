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
from cuid2 import cuid_wrapper

cuid = cuid_wrapper()

load_dotenv()

app = Flask(__name__, static_folder='public', static_url_path='/static')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
UPLOADS_DIR = os.environ.get('UPLOADS_DIR', os.path.join(os.path.dirname(__file__), 'uploads'))
CLOUDFRONT_URL = os.environ.get('NEXT_PUBLIC_CLOUDFRONT_URL', '')
BASE_URL = "https://knokr-base-production.up.railway.app"

# Ensure uploads directory exists
os.makedirs(UPLOADS_DIR, exist_ok=True)

client = Anthropic()


def get_festival_image_url(image_url):
    """Get the full URL for a festival image."""
    if not image_url:
        return None
    trimmed = image_url.strip()
    if trimmed.startswith('http'):
        return trimmed
    if trimmed.startswith('media/') or '/media/' in trimmed:
        clean_path = trimmed.lstrip('/')
        return f"{CLOUDFRONT_URL}/{clean_path}"
    if trimmed.endswith('.webp'):
        return f"{CLOUDFRONT_URL}/transformed/festivals/images/{trimmed}"
    filename = trimmed.split('.')[0]
    return f"{CLOUDFRONT_URL}/transformed/festivals/images/{filename}.webp"


def get_artist_image_url(image_url):
    """Get the full URL for an artist image."""
    if not image_url or image_url == 'a-few-moments-later.png':
        return None
    trimmed = image_url.strip()
    # Only allow CloudFront URLs - external URLs won't work reliably
    if trimmed.startswith('http'):
        if CLOUDFRONT_URL and trimmed.startswith(CLOUDFRONT_URL):
            return trimmed
        # Return None for non-CloudFront URLs to show placeholder
        return None
    # New format: full relative path (e.g., media/artists/slug/filename.jpg)
    if trimmed.startswith('media/') or trimmed.startswith('/media/'):
        path = trimmed if trimmed.startswith('/') else f'/{trimmed}'
        return f"{CLOUDFRONT_URL}{path}"
    # Old format: just filename → transformed/artists/images/{filename}.webp
    filename = trimmed.split('.')[0]
    return f"{CLOUDFRONT_URL}/transformed/artists/images/{filename}.webp"


def format_date(date_value):
    """Format a date for display."""
    if not date_value:
        return None
    if isinstance(date_value, str):
        date_value = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
    return date_value.strftime('%b %d, %Y')


def format_location(city, country, region=None):
    """Format location as city, country or city, region for US/UK."""
    if not city:
        return country or ''

    # For US and UK, use city, region format
    if country in ('United States', 'USA', 'US', 'United Kingdom', 'UK', 'England', 'Scotland', 'Wales', 'Northern Ireland'):
        if region:
            return f"{city}, {region}"
        return city

    # For other countries, use city, country format
    if country:
        return f"{city}, {country}"
    return city


def format_genre(genre):
    """Normalize genre spelling for display."""
    if not genre:
        return ''

    # Special case mappings (lowercase key -> display value)
    special_cases = {
        'edm': 'EDM',
        'dj': 'DJ',
        'r&b': 'R&B',
        'rnb': 'R&B',
        'hip-hop': 'Hip-Hop',
        'hip hop': 'Hip-Hop',
        'hiphop': 'Hip-Hop',
        'k-pop': 'K-Pop',
        'kpop': 'K-Pop',
        'j-pop': 'J-Pop',
        'jpop': 'J-Pop',
        'uk garage': 'UK Garage',
        'uk bass': 'UK Bass',
        'drum and bass': 'Drum & Bass',
        'drum & bass': 'Drum & Bass',
        'dnb': 'Drum & Bass',
        'd&b': 'Drum & Bass',
        'lo-fi': 'Lo-Fi',
        'lofi': 'Lo-Fi',
        'synthwave': 'Synthwave',
        'synthpop': 'Synthpop',
        'post-punk': 'Post-Punk',
        'post punk': 'Post-Punk',
        'neo-soul': 'Neo-Soul',
        'neo soul': 'Neo-Soul',
        'afrobeats': 'Afrobeats',
        'afrobeat': 'Afrobeats',
        'latin': 'Latin',
        'reggaeton': 'Reggaeton',
        'uk drill': 'UK Drill',
    }

    lower_genre = genre.lower().strip()
    if lower_genre in special_cases:
        return special_cases[lower_genre]

    # Default: title case
    return genre.strip().title()


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


def insert_pending_artist(cursor, name):
    """Insert a new artist into the PendingArtist table."""
    cursor.execute("""
        INSERT INTO "PendingArtist" (id, name, genres, "addedById", "createdAt", "updatedAt")
        VALUES (%s, %s, %s, 'system-poster-extractor', NOW(), NOW())
        ON CONFLICT DO NOTHING
    """, (cuid(), name, []))


def check_existing_artists(artist_names: list[str]) -> dict:
    """Check which artists exist in the database and return their details."""
    conn = None
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"Database connection failed: {e}")
        return {'existing': [], 'new': artist_names, 'db_error': True, 'genre_breakdown': []}

    if not conn:
        return {'existing': [], 'new': artist_names, 'db_error': False, 'genre_breakdown': []}

    try:
        cursor = conn.cursor()
        # Use case-insensitive matching, return name, slug, imageUrl, and genres
        query = f"""
            SELECT name, slug, "imageUrl", genres FROM "Artist"
            WHERE LOWER(name) IN ({','.join(['LOWER(%s)'] * len(artist_names))})
        """
        cursor.execute(query, artist_names)
        existing_map = {
            row[0].lower(): {'name': row[0], 'slug': row[1], 'imageUrl': row[2], 'genres': row[3] or []}
            for row in cursor.fetchall()
        }

        existing = []
        new = []
        genre_counts = {}

        for name in artist_names:
            if name.lower() in existing_map:
                artist = existing_map[name.lower()]
                existing.append(artist)
                # Count genres
                for genre in artist['genres']:
                    genre_counts[genre] = genre_counts.get(genre, 0) + 1
            else:
                new.append(name)
                # Insert new artist into PendingArtist table
                insert_pending_artist(cursor, name)

        # Calculate genre breakdown as percentages
        total_genre_tags = sum(genre_counts.values())
        genre_breakdown = []
        if total_genre_tags > 0:
            for genre, count in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True):
                genre_breakdown.append({
                    'genre': genre,
                    'count': count,
                    'percentage': round((count / len(existing)) * 100, 1)
                })

        conn.commit()
        return {'existing': existing, 'new': new, 'db_error': False, 'genre_breakdown': genre_breakdown}
    except Exception as e:
        print(f"Database query failed: {e}")
        if conn:
            conn.rollback()
        return {'existing': [], 'new': artist_names, 'db_error': True, 'genre_breakdown': []}
    finally:
        if conn:
            conn.close()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_artists_from_image(image_data: bytes, media_type: str) -> dict:
    """Use Claude Vision to extract artist names and dates from a festival lineup image."""
    import json as json_module
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
                        "text": """Analyze this festival lineup image and extract:
1. ALL artist/performer names you can see
2. The festival dates (start and end date)

Rules for artists:
- Extract only artist/band/performer names
- Do NOT include stage names, dates, times, or other text
- Normalize capitalization to the artist's official/proper spelling (e.g., "Skrillex" not "SKRILLEX", "Four Tet" not "FOUR TET")
- Keep acronyms and stylized names correct (e.g., "SG Lewis", "RÜFÜS DU SOL", "DJ Trixie Mattel", "Aly & AJ")
- If a name appears multiple times, only list it once
- Order them roughly by how prominently they appear (headliners first, then smaller acts)

Rules for dates:
- Extract the start date and end date of the festival
- Use ISO format: YYYY-MM-DD
- If only one date is shown, use it for both start and end
- If no dates are visible, use null for both

Return your response as JSON in this exact format:
{
  "artists": ["Artist 1", "Artist 2", ...],
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD"
}

Return ONLY the JSON, no other text."""
                    }
                ],
            }
        ],
    )

    # Parse the JSON response
    response_text = message.content[0].text.strip()
    # Handle potential markdown code blocks
    if response_text.startswith('```'):
        response_text = response_text.split('\n', 1)[1]
        response_text = response_text.rsplit('```', 1)[0]

    result = json_module.loads(response_text)
    return {
        'artists': result.get('artists', []),
        'start_date': result.get('start_date'),
        'end_date': result.get('end_date')
    }


def generate_csv(festival_name: str, year: str, artists: list[str]) -> str:
    """Generate CSV content from extracted artist data."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['festival_name', 'edition', 'artist_name'])

    for artist in artists:
        writer.writerow([festival_name, year, artist])

    return output.getvalue()


def generate_json(festival_name: str, year: str, artists: list[str]) -> str:
    """Generate JSON content from extracted artist data."""
    import json
    data = {
        'festival_name': festival_name,
        'edition': year,
        'artists': artists
    }
    return json.dumps(data, indent=2)


@app.route('/', methods=['GET'])
def home():
    """Homepage - display upcoming and latest festivals."""
    upcoming_festivals = []
    latest_festivals = []
    conn = None
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()

            # Upcoming festivals (startDate >= today, ordered by startDate ASC)
            cursor.execute("""
                SELECT id, name, slug, "imageUrl", city, country, region, "startDate", "endDate", genres
                FROM "Festival"
                WHERE "isActive" = true AND "startDate" >= CURRENT_DATE
                ORDER BY "startDate" ASC
                LIMIT 12
            """)
            rows = cursor.fetchall()
            for row in rows:
                upcoming_festivals.append({
                    'id': row[0],
                    'name': row[1],
                    'slug': row[2],
                    'imageUrl': row[3],
                    'city': row[4],
                    'country': row[5],
                    'region': row[6],
                    'startDate': row[7],
                    'endDate': row[8],
                    'genres': row[9] or []
                })

            # Latest festivals (ordered by updatedAt DESC)
            cursor.execute("""
                SELECT id, name, slug, "imageUrl", city, country, region, "startDate", "endDate", genres
                FROM "Festival"
                WHERE "isActive" = true
                ORDER BY "updatedAt" DESC
                LIMIT 12
            """)
            rows = cursor.fetchall()
            for row in rows:
                latest_festivals.append({
                    'id': row[0],
                    'name': row[1],
                    'slug': row[2],
                    'imageUrl': row[3],
                    'city': row[4],
                    'country': row[5],
                    'region': row[6],
                    'startDate': row[7],
                    'endDate': row[8],
                    'genres': row[9] or []
                })
    except Exception as e:
        print(f"Error fetching festivals: {e}")
    finally:
        if conn:
            conn.close()

    return render_template('home.html',
                           upcoming_festivals=upcoming_festivals,
                           latest_festivals=latest_festivals,
                           current_year=datetime.now().year,
                           get_festival_image_url=get_festival_image_url,
                           format_date=format_date,
                           format_location=format_location,
                           format_genre=format_genre)


@app.route('/extractor', methods=['GET'])
def extractor():
    """Lineup extraction tool."""
    return render_template('extractor.html',
                           cloudfront_url=CLOUDFRONT_URL,
                           current_year=datetime.now().year)


@app.route('/festival/<slug>', methods=['GET'])
def festival_detail(slug):
    """Festival detail page with lineup."""
    festival = None
    artists = []
    conn = None
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            # Get festival details
            cursor.execute("""
                SELECT id, name, slug, "imageUrl", city, country, region, "startDate", "endDate",
                       genres, website, spotify, instagram, facebook, youtube, tiktok, "isCruise"
                FROM "Festival"
                WHERE slug = %s
            """, (slug,))
            row = cursor.fetchone()
            if row:
                festival = {
                    'id': row[0],
                    'name': row[1],
                    'slug': row[2],
                    'imageUrl': row[3],
                    'city': row[4],
                    'country': row[5],
                    'region': row[6],
                    'startDate': row[7],
                    'endDate': row[8],
                    'genres': row[9] or [],
                    'website': row[10],
                    'spotify': row[11],
                    'instagram': row[12],
                    'facebook': row[13],
                    'youtube': row[14],
                    'tiktok': row[15],
                    'isCruise': row[16]
                }

                # Get lineup artists with all fields for Orchestra-style cards
                cursor.execute("""
                    SELECT a.id, a.name, a.slug, a."imageUrl", a.genres,
                           a.city, a.region, a.country,
                           a.spotify, a.instagram, a.youtube, a.tiktok, a.soundcloud, a.website
                    FROM "Artist" a
                    JOIN "FestivalLineup" fl ON a.id = fl."artistId"
                    WHERE fl."festivalId" = %s
                    ORDER BY a.name
                """, (festival['id'],))
                artist_rows = cursor.fetchall()
                for artist_row in artist_rows:
                    # Build socials list like Orchestra
                    socials = []
                    if artist_row[8]:  # spotify
                        socials.append({'network': 'spotify', 'url': artist_row[8]})
                    if artist_row[9]:  # instagram
                        socials.append({'network': 'instagram', 'url': artist_row[9]})
                    if artist_row[10]:  # youtube
                        socials.append({'network': 'youtube', 'url': artist_row[10]})
                    if artist_row[11]:  # tiktok
                        socials.append({'network': 'tiktok', 'url': artist_row[11]})
                    if artist_row[12]:  # soundcloud
                        socials.append({'network': 'soundcloud', 'url': artist_row[12]})
                    if artist_row[13]:  # website
                        socials.append({'network': 'website', 'url': artist_row[13]})

                    artists.append({
                        'id': artist_row[0],
                        'name': artist_row[1],
                        'slug': artist_row[2],
                        'imageUrl': artist_row[3],
                        'genres': artist_row[4] or [],
                        'city': artist_row[5],
                        'region': artist_row[6],
                        'country': artist_row[7],
                        'socials': socials[:3]  # Max 3 like Orchestra
                    })
    except Exception as e:
        print(f"Error fetching festival: {e}")
    finally:
        if conn:
            conn.close()

    if not festival:
        return "Festival not found", 404

    return render_template('festival.html',
                           festival=festival,
                           artists=artists,
                           current_year=datetime.now().year,
                           base_url=BASE_URL,
                           get_festival_image_url=get_festival_image_url,
                           get_artist_image_url=get_artist_image_url,
                           format_date=format_date,
                           format_location=format_location,
                           format_genre=format_genre)


@app.route('/search', methods=['GET'])
def search():
    """Search festivals."""
    query = request.args.get('q', '').strip()
    festivals = []

    if query:
        conn = None
        try:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                search_term = f"%{query.lower()}%"
                cursor.execute("""
                    SELECT id, name, slug, "imageUrl", city, country, region, "startDate", "endDate", genres
                    FROM "Festival"
                    WHERE "isActive" = true
                      AND (LOWER(name) LIKE %s OR LOWER(city) LIKE %s OR LOWER(country) LIKE %s)
                    ORDER BY "startDate" DESC
                    LIMIT 50
                """, (search_term, search_term, search_term))
                rows = cursor.fetchall()
                for row in rows:
                    festivals.append({
                        'id': row[0],
                        'name': row[1],
                        'slug': row[2],
                        'imageUrl': row[3],
                        'city': row[4],
                        'country': row[5],
                        'region': row[6],
                        'startDate': row[7],
                        'endDate': row[8],
                        'genres': row[9] or []
                    })
        except Exception as e:
            print(f"Error searching festivals: {e}")
        finally:
            if conn:
                conn.close()

    return render_template('search.html',
                           festivals=festivals,
                           query=query,
                           current_year=datetime.now().year,
                           get_festival_image_url=get_festival_image_url,
                           format_date=format_date,
                           format_location=format_location,
                           format_genre=format_genre)


@app.route('/terms', methods=['GET'])
def terms():
    return render_template('terms.html', current_year=datetime.now().year)


@app.route('/privacy', methods=['GET'])
def privacy():
    return render_template('privacy.html', current_year=datetime.now().year)


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
        # Extract artists and dates using Claude Vision
        extraction = extract_artists_from_image(image_data, media_type)
        artists = extraction['artists']
        start_date = extraction['start_date']
        end_date = extraction['end_date']

        if not artists:
            return {'error': 'No artists found in the image'}, 400

        # Check which artists exist in the database
        artist_check = check_existing_artists(artists)

        # Generate CSV and JSON with all artists
        csv_content = generate_csv(festival_name, year, artists)
        json_content = generate_json(festival_name, year, artists)

        # Save uploaded image, CSV, and JSON to uploads directory
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

        # Save JSON
        json_filename = f"{base_filename}.json"
        json_path = os.path.join(UPLOADS_DIR, json_filename)
        with open(json_path, 'w') as f:
            f.write(json_content)

        # Return response with artist breakdown and download paths
        return jsonify({
            'success': True,
            'festival_name': festival_name,
            'year': year,
            'start_date': start_date,
            'end_date': end_date,
            'existing_artists': artist_check['existing'],
            'new_artists': artist_check['new'],
            'total_artists': len(artists),
            'all_artists': artists,
            'genre_breakdown': artist_check.get('genre_breakdown', []),
            'csv_filename': csv_filename,
            'csv_download': f'/uploads/{csv_filename}',
            'json_filename': json_filename,
            'json_download': f'/uploads/{json_filename}',
            'db_error': artist_check.get('db_error', False)
        })

    except Exception as e:
        return {'error': f'Failed to process image: {str(e)}'}, 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=port)
