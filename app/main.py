from fastapi import FastAPI
from app.foundation_kit.routers import auth, dashboard, database
from fastapi.middleware.cors import CORSMiddleware
from app.medofficehq.router import patients, rules, athena, filters
from app.medofficehq.core.config import settings
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Med Office HQ API",
    description="API for medical office management and rule processing",
    version="1.0.0"
)

@app.get("/")
async def root():
    return {
        "message": "Welcome to Med Office HQ API",
        "version": "1.0.0",
        "endpoints": {
            "auth": "/api/auth",
            "dashboard": "/api/dashboard", 
            "database": "/api/database",
            "patients": "/api/patients",
            "rules": "/api/rules",
            "filters": "/api/filters",
            "athena": "/api/medofficehq/athena"
        }
    }

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])

app.include_router(database.router, prefix="/api/database", tags=["database"])

#Medoffice
app.include_router(
    patients.router,
    prefix="/api/patients",
    tags=["patients"]
)

app.include_router(
    rules.router,
    prefix="/api/rules",
    tags=["rules"]
)

app.include_router(
    filters.router,
    prefix="/api/filters",
    tags=["filters"]
)

# Athena Health API
app.include_router(
    athena.router,
    prefix="/api/medofficehq/athena",
    tags=["athena"]
)

origins = [
    "http://localhost:3000",
    "http://localhost:8000",
    # Azure Static Web App Frontend
    "https://jolly-rock-0894e830f.6.azurestaticapps.net",
    # GHL (Go High Level) webhook domains
    "https://hooks.gohighlevel.com",
    "https://api.gohighlevel.com",
    "https://app.gohighlevel.com",
    "https://webhooks.gohighlevel.com",
]

if os.getenv("FRONTEND_URL"):
    origins.append(os.getenv("FRONTEND_URL"))

if os.getenv("PUBLIC_URL"):  # use PUBLIC_URL instead of BACKEND_URL
    origins.append(os.getenv("PUBLIC_URL"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*", "Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With", "User-Agent"],
    expose_headers=["*"],
    max_age=3600,
)