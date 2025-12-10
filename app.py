import os
import csv
import io
import base64
from flask import Flask, request, render_template, Response
from anthropic import Anthropic
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

client = Anthropic()


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
    return render_template('index.html')


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

        # Generate CSV
        csv_content = generate_csv(festival_name, year, artists)

        # Return as downloadable CSV
        filename = f"{festival_name.lower().replace(' ', '_')}_{year}_lineup.csv"

        return Response(
            csv_content,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )

    except Exception as e:
        return {'error': f'Failed to process image: {str(e)}'}, 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
