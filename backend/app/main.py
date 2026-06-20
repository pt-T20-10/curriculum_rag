"""
FastAPI application entry point.

This module initializes the FastAPI application with middleware, routers,
and health check endpoints. It serves as the main entry point for the
AI Textbook Generator backend.

Author: AI Textbook Generator Team
Date: 2026-04-26
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles 
from fastapi.responses import FileResponse  
from pathlib import Path  

from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine, Base
from app.routers import account_deletion, admin, auth, base, config, plans, site_info, support, textbook


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan context manager.
    
    Handles startup and shutdown events for the FastAPI application.
    
    Startup:
        - Create database tables if they don't exist
        - Initialize connections
        - Log startup message
    
    Shutdown:
        - Close database connections
        - Cleanup resources
        - Log shutdown message
    
    Args:
        app: FastAPI application instance
        
    Yields:
        None (yields control to the application)
    """
    # Startup
    print("🚀 Starting AI Textbook Generator API...")
    
    try:
        # Create database tables
        async with engine.begin() as conn:
            import app.models  # noqa: F401 - register all SQLAlchemy models
            await conn.run_sync(Base.metadata.create_all)
        print("✅ Database tables created/verified")

        from app.services.bootstrap import ensure_default_admin_user

        if await ensure_default_admin_user():
            print("✅ Default admin account created/verified")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        raise
    
    print(f"✅ API running on {settings.BACKEND_URL}")
    print(f"📚 Docs available at {settings.BACKEND_URL}/docs")
    
    yield
    
    # Shutdown
    print("🛑 Shutting down AI Textbook Generator API...")
    await engine.dispose()
    print("✅ Shutdown complete")


# Initialize FastAPI application
app = FastAPI(
    title="AI Textbook Generator API",
    description="Backend API for AI-powered textbook generation system",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",     # Vite dev server
        "http://127.0.0.1:5173",     # Alternative localhost
        "http://localhost:3000",     # React dev server
        "http://127.0.0.1:3000",     # Alternative
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],  
    allow_headers=["*"],
    expose_headers=["*"],       
    max_age=3600,                   
)
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)  # Create if doesn't exist

app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")

# Include routers
app.include_router(base.router, prefix="/api/v1", tags=["Base"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(plans.router, prefix="/api/v1", tags=["Plans"])
app.include_router(textbook.router, prefix="/api/v1", tags=["Textbooks"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(config.router, prefix="/api/v1", tags=["Config"])
app.include_router(site_info.router, prefix="/api/v1")
app.include_router(support.router, prefix="/api/v1")
app.include_router(account_deletion.router, prefix="/api/v1")

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """
    Global exception handler for uncaught exceptions.
    
    Logs the error and returns a standardized error response
    to prevent leaking internal details to clients.
    
    Args:
        request: The HTTP request that caused the exception
        exc: The exception that was raised
        
    Returns:
        JSONResponse with error details (sanitized in production)
    """
    # In production, log to monitoring service (Sentry, etc.)
    print(f"❌ Unhandled exception: {exc}")
    
    # Don't expose internal errors in production
    if settings.ENVIRONMENT == "production":
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "error_id": "contact_support"  # Would be a tracking ID
            }
        )
    
    # In development, show detailed error
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": type(exc).__name__
        }
    )


# Root endpoint
@app.get("/")
async def root():
    """
    Root endpoint - API status.
    
    Returns:
        dict: API status and version information
    """
    return {
        "message": "AI Textbook Generator API",
        "version": "1.0.0",
        "status": "running",
        "docs": f"{settings.BACKEND_URL}/docs"
    }


if __name__ == "__main__":
    # This block allows running the app directly with `python app/main.py`
    # For production, use `uvicorn app.main:app` or the run_api.py script
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
