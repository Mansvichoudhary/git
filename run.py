import sys
from pathlib import Path
import uvicorn

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.core.database import init_db

if __name__ == "__main__":
    print("=" * 70)
    print("Starting FinAgent — Data Ingestion & Parse Engine (Part 1)")
    print("Access Web UI & API at: http://127.0.0.1:8000")
    print("Interactive Swagger Docs at: http://127.0.0.1:8000/docs")
    print("=" * 70)
    
    init_db()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
