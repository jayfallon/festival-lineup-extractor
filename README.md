# Festival Lineup Extractor

A web app by [Knokr](https://knokr.com) that extracts artist names from festival lineup poster images using Claude's vision API and exports them to CSV.

## Features

- Upload festival lineup images (PNG, JPG, JPEG, GIF, WebP)
- Automatically extracts artist/performer names using AI vision
- Normalizes artist name capitalization
- Orders artists by prominence (headliners first)
- Checks extracted artists against a PostgreSQL database
- Displays artist cards with images for known artists (linked to artist pages)
- New artists automatically added to PendingArtist queue for review
- Exports to CSV with festival name and year
- Persists uploaded images and generated CSVs

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

## Deployment

The app is configured for Railway deployment with gunicorn.

### Environment Variables

- `ANTHROPIC_API_KEY` - Required. Your Anthropic API key
- `DATABASE_URL` - Optional. PostgreSQL connection string for artist lookup
- `NEXT_PUBLIC_CLOUDFRONT_URL` - Optional. CloudFront URL for artist images
- `UPLOADS_DIR` - Optional. Directory for persistent file storage (default: ./uploads)
- `PORT` - Optional. Server port (default: 5000)
- `FLASK_DEBUG` - Optional. Set to `true` for development hot reload

### Railway Setup

1. Create a new Railway project
2. Add the environment variables above
3. Optionally attach a volume mounted to `/app/uploads` and set `UPLOADS_DIR=/app/uploads`

## Pages

- `/` - Main app for uploading and extracting lineups
- `/terms` - Terms of Service
- `/privacy` - Privacy & Data Policy
