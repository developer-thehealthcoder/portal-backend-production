from fastapi import APIRouter, Security, HTTPException
from app.foundation_kit.database.cosmos import initialize_database, get_database_info
from app.foundation_kit.services.data_seeder import DataSeeder
from app.foundation_kit.services.auth_service import require_role, get_current_user

router = APIRouter()

@router.post("/initialize")
async def initialize_new_database():
    """Initialize a new database with all required containers."""
    try:
        result = initialize_database()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/info", dependencies=[Security(get_current_user)])
async def get_database_status():
    """Get information about the current database setup."""
    try:
        return get_database_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/seed/user-groups")
async def seed_user_groups():
    """Seed default user groups into the database."""
    try:
        return DataSeeder.seed_user_groups()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/seed/menu")
async def seed_menu():
    """Seed default menu structure into the database."""
    try:
        return DataSeeder.seed_menu()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/seed/all")
async def seed_all_data():
    """Seed all essential data into the database."""
    try:
        return DataSeeder.seed_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export/user-groups")
async def export_user_groups():
    """Export current user groups for backup or migration."""
    try:
        return DataSeeder.export_user_groups()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/setup-new-project")
async def setup_new_project():
    """Complete setup for a new project - initialize database and seed all data."""
    try:
        # Initialize database and containers
        init_result = initialize_database()
        
        # Seed all essential data
        seed_result = DataSeeder.seed_all()
        
        return {
            "message": "New project setup completed successfully",
            "initialization": init_result,
            "seeding": seed_result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 