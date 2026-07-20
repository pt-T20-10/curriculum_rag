# AI Textbook Generator

Runtime-only repository for the AI Textbook Generator app.

This branch keeps the code needed to run the server application:

- FastAPI backend in `backend/app`
- Alembic migrations in `backend/alembic`
- React/Vite frontend in `frontend/src`
- Runtime dependency files and environment examples

Docker, deployment helper scripts, tests, and experiment artifacts have been removed from tracked source.

## Requirements

- Python 3.11+
- Node.js 20+
- MySQL 8+
- Redis, if shared task coordination or rate limiting is enabled

## Environment

Create a local `.env` from one of the examples:

```powershell
Copy-Item .env.example .env
```

At minimum, configure database credentials and the API keys required by your generation mode.

Important defaults:

- Backend URL: `http://localhost:8000`
- Frontend URL: `http://localhost:5173`
- MySQL host: `localhost:3306`
- Database name: `ai_textbook_db`

## Backend

Install Python dependencies:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run migrations:

```powershell
Set-Location backend
alembic upgrade head
```

Start the API:

```powershell
python run_api.py
```

The API will listen on `http://localhost:8000`. Interactive API docs are available at `http://localhost:8000/docs`.

Alternative uvicorn command from inside `backend`:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Frontend

Install JavaScript dependencies:

```powershell
Set-Location frontend
npm install
```

Start the development server:

```powershell
npm run dev
```

Build the production frontend:

```powershell
npm run build
```

The Vite dev server uses `http://localhost:5173` and calls the backend at `http://localhost:8000` by default. Override with `VITE_API_URL` when needed.

## Runtime Checks

Compile backend Python files:

```powershell
python -m compileall backend/app backend/run_api.py backend/run_cli.py
```

Build frontend assets:

```powershell
Set-Location frontend
npm run build
```

Import the FastAPI app from inside `backend` when dependencies and environment are available:

```powershell
python -c "from app.main import app; print(app.title)"
```
