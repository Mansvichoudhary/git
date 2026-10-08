from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from app.core.database import init_db
from app.api.routes_ingestion import router as ingestion_router

# Initialize FastAPI App
app = FastAPI(
    title="FinAgent — Data Ingestion & Parse Engine (Part 1)",
    description="Automated multi-bank financial statement parsing, intelligent schema mapping, and canonical normalization.",
    version="1.0.0"
)

# Enable CORS for local UI and microservices
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup Event
@app.on_event("startup")
def startup_event():
    init_db()

# Include API Router
app.include_router(ingestion_router)

# Mount frontend if present
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if (FRONTEND_DIR / "index.html").exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def serve_ui():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "module": "FinAgent Data Ingestion & Parse Engine",
        "version": "1.0.0"
    }
