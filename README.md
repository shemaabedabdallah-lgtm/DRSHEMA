# DR SHEMA Video Builder Service

Automated video builder for DR SHEMA Media Empire.
Combines Pexels footage + flite voice + FFmpeg + DR SHEMA watermark.

## Deploy to Render

1. Push this folder to GitHub
2. Go to render.com → New → Web Service
3. Connect your GitHub repo
4. Render auto-detects render.yaml and deploys

## Endpoints

GET  /health  → Check service is running
POST /build   → Build a video

## POST /build payload

{
  "title": "Breaking News Title",
  "script": "Full narration script...",
  "channel": "news",
  "clip1_url": "https://pexels.com/...",
  "clip2_url": "https://pexels.com/...",
  "clip3_url": "https://pexels.com/..."
}

## Response

{
  "success": true,
  "video": "base64_encoded_mp4..."
}
