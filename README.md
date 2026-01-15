# Lineups by Knokr

A web app by [Knokr](https://knokr.com) that uses AI vision to extract artist names from festival lineup poster images.

## Purpose

Festival lineup posters are visually rich but difficult to parse programmatically. This tool solves that by using Claude's vision capabilities to read lineup images and extract structured artist data. It's designed to help music industry professionals, festival organizers, and data teams quickly digitize lineup information for analysis, database population, or content creation.

## How It Works

1. **Upload** a festival lineup poster image (PNG, JPG, GIF, or WebP)
2. **Enter** the festival name and year
3. **Extract** - Claude's vision API analyzes the image and identifies all artist names
4. **Review** results with artist cards showing known artists from the database
5. **Export** to CSV or JSON, or copy the artist list to clipboard

## Features

- **AI-Powered Extraction**: Uses Claude Sonnet's vision capabilities to read and parse lineup posters
- **Smart Normalization**: Corrects artist name capitalization (e.g., "SKRILLEX" → "Skrillex") while preserving stylized names (e.g., "RÜFÜS DU SOL")
- **Prominence Ordering**: Returns artists ordered by visual prominence (headliners first)
- **Date Detection**: Automatically extracts festival dates when visible on the poster
- **Database Integration**: Cross-references extracted artists against a PostgreSQL artist database
- **Genre Analysis**: Shows genre breakdown percentages for known artists
- **Artist Cards**: Displays image cards for known artists with links to their profiles
- **Pending Queue**: New/unknown artists are automatically added to a review queue
- **Multiple Export Formats**: Download as CSV, JSON, or copy to clipboard
- **Responsive Design**: Works on desktop and mobile devices

## Tech Stack

- **Backend**: Python 3.13, Flask 3.0
- **AI**: Anthropic Claude API (claude-sonnet-4-20250514) for vision analysis
- **Database**: PostgreSQL via pg8000 driver
- **ID Generation**: cuid2 for unique identifiers
- **Production Server**: Gunicorn
- **Deployment**: Railway

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set your environment variables:
   ```bash
   export ANTHROPIC_API_KEY=your_key_here
   export DATABASE_URL=postgresql://user:pass@host:5432/dbname  # optional
   export NEXT_PUBLIC_CLOUDFRONT_URL=https://your-cloudfront.cloudfront.net  # optional
   ```
4. Run the app:
   ```bash
   python app.py
   ```

For development with hot reload:
```bash
FLASK_DEBUG=true python app.py
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key for Claude |
| `DATABASE_URL` | No | PostgreSQL connection string for artist lookup |
| `NEXT_PUBLIC_CLOUDFRONT_URL` | No | CloudFront URL for artist images |
| `UPLOADS_DIR` | No | Directory for file storage (default: ./uploads) |
| `PORT` | No | Server port (default: 5000) |
| `FLASK_DEBUG` | No | Set to `true` for development hot reload |

## Deployment

The app is configured for Railway deployment with Gunicorn.

### Railway Setup

1. Create a new Railway project
2. Add the environment variables above
3. Optionally attach a volume mounted to `/app/uploads` and set `UPLOADS_DIR=/app/uploads`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Main app interface |
| POST | `/extract` | Upload image and extract artists |
| GET | `/uploads` | List all uploaded files |
| GET | `/uploads/<filename>` | Download a specific file |
| GET | `/terms` | Terms of Service |
| GET | `/privacy` | Privacy & Data Policy |
