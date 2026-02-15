# VideoSplit API

A fast, simple REST API for splitting videos into equal-length segments. Built with FastAPI and FFmpeg.

## Features

- **Fast Processing**: Uses FFmpeg's copy codec (no re-encoding)
- **Simple API**: Upload video, get download links
- **Flexible Segments**: Split into any duration (1 second to 1 hour)
- **RESTful Design**: Clean, predictable endpoints
- **Auto Documentation**: Interactive API docs at `/docs`

## Quick Start

### Prerequisites

- Python 3.8+
- FFmpeg installed

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/YOUR_USERNAME/videosplit-api.git
cd videosplit-api
```

2. **Create virtual environment**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Run the server**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

5. **Open your browser**
```
http://localhost:8000/docs
```

## 📖 API Usage

### Split a Video

**Endpoint:** `POST /api/v1/split`

**Parameters:**
- `file`: Video file to upload
- `segment_duration`: Length of each segment in seconds (default: 60)

**Example (cURL):**
```bash
curl -X POST "http://localhost:8000/api/v1/split?segment_duration=30" \
  -F "file=@my_video.mp4"
```

**Response:**
```json
{
  "job_id": "abc-123-def",
  "status": "completed",
  "segments_count": 3,
  "segments": [
    {
      "filename": "segment_000.mp4",
      "duration": 30.0,
      "size_bytes": 5242880,
      "download_url": "/api/v1/download/abc-123/segment_000.mp4"
    }
  ],
  "original_filename": "my_video.mp4",
  "total_duration": 75.5
}
```

### Download a Segment

**Endpoint:** `GET /api/v1/download/{job_id}/{filename}`

**Example:**
```
http://localhost:8000/api/v1/download/abc-123/segment_000.mp4
```

### Get Job Info

**Endpoint:** `GET /api/v1/job/{job_id}`

**Example:**
```bash
curl http://localhost:8000/api/v1/job/abc-123
```

### Delete a Job

**Endpoint:** `DELETE /api/v1/job/{job_id}`

**Example:**
```bash
curl -X DELETE http://localhost:8000/api/v1/job/abc-123
```

## Project Structure
```
videosplit-api/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app & configuration
│   ├── models/
│   │   └── schemas.py       # Pydantic models
│   ├── routes/
│   │   └── video.py         # API endpoints
│   └── services/
│       └── ffmpeg_service.py # FFmpeg wrapper
├── uploads/                 # Temporary upload storage
├── outputs/                 # Processed video segments
├── requirements.txt
└── README.md
```

## Configuration

The API can be configured via environment variables:
```bash
HOST=0.0.0.0
PORT=8000
MAX_FILE_SIZE_MB=500
```

## Docker (Optional)
```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Video processing by [FFmpeg](https://ffmpeg.org/)
