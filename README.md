# festival-lineup-extractor

A web app that extracts artist names from festival lineup poster images using Claude's vision API and exports them to CSV.

## Features

- Upload festival lineup images (PNG, JPG, JPEG, GIF, WebP)
- Automatically extracts artist/performer names using AI vision
- Normalizes artist name capitalization
- Orders artists by prominence (headliners first)
- Exports to CSV with festival name and year

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set your Anthropic API key:
   ```bash
   export ANTHROPIC_API_KEY=your_key_here
   ```
4. Run the app:
   ```bash
   python app.py
   ```

## Deployment

The app is configured for Railway deployment with gunicorn. Set `ANTHROPIC_API_KEY` as an environment variable in your Railway project.
