import os
from azure.cosmos import CosmosClient, PartitionKey
from fastapi import HTTPException
from dotenv import load_dotenv
from app.config import (
    COSMOS_CONTAINER_USERS,
    COSMOS_CONTAINER_USER_GROUPS,
    COSMOS_CONTAINER_INSTITUTIONS,
    COSMOS_CONTAINER_MENU,
    COSMOS_CONTAINER_PASSWORD_RESETS,
    REQUIRED_CONTAINERS,
    COSMOS_API_URI,
    COSMOS_API_PRIMARY_KEY,
    COSMOS_DATABASE
)

load_dotenv()

# Cosmos DB configuration - use values from config.py
COSMOS_URI = COSMOS_API_URI
COSMOS_KEY = COSMOS_API_PRIMARY_KEY
DATABASE_NAME = COSMOS_DATABASE

# Container configuration
CONTAINER_CONFIG = {
    COSMOS_CONTAINER_USERS: {"partition_key": "/id"},
    COSMOS_CONTAINER_USER_GROUPS: {"partition_key": "/id"},
    COSMOS_CONTAINER_INSTITUTIONS: {"partition_key": "/id"},
    COSMOS_CONTAINER_MENU: {"partition_key": "/id"},
    COSMOS_CONTAINER_PASSWORD_RESETS: {"partition_key": "/id"}
}

if not COSMOS_URI or not COSMOS_KEY:
    raise HTTPException(
        status_code=500,
        detail="Cosmos DB credentials not found. Please check your .env file."
    )

try:
    # Initialize Cosmos DB client
    client = CosmosClient(COSMOS_URI, COSMOS_KEY)
    database = client.get_database_client(DATABASE_NAME)
except Exception as e:
    raise HTTPException(
        status_code=500,
        detail=f"Failed to connect to Cosmos DB: {str(e)}"
    )

def ensure_database_exists():
    """Ensure the database exists, create if it doesn't."""
    try:
        client.get_database_client(DATABASE_NAME).read()
    except Exception:
        # Database doesn't exist, create it
        client.create_database(DATABASE_NAME)

def ensure_container_exists(container_name: str):
    """Ensure a container exists, create if it doesn't."""
    try:
        database.get_container_client(container_name).read()
    except Exception:
        # Container doesn't exist, create it
        partition_key_definition = PartitionKey(path=CONTAINER_CONFIG[container_name]["partition_key"])
        database.create_container(
            id=container_name,
            partition_key=partition_key_definition
        )

def initialize_database():
    """Initialize the database and all required containers."""
    try:
        ensure_database_exists()
        
        for container_name in REQUIRED_CONTAINERS:
            ensure_container_exists(container_name)
            
        return {"message": "Database initialized successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize database: {str(e)}"
        )

def get_container(container_name: str):
    """Get a container client, ensuring it exists first."""
    try:
        # Ensure container exists before returning client
        ensure_container_exists(container_name)
        return database.get_container_client(container_name)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get container {container_name}: {str(e)}"
        )

def get_database_info():
    """Get information about the current database setup."""
    try:
        db_info = database.read()
        containers = []
        for container_name in REQUIRED_CONTAINERS:
            try:
                container = database.get_container_client(container_name)
                container_info = container.read()
                containers.append({
                    "name": container_name,
                    "exists": True,
                    "id": container_info["id"]
                })
            except Exception:
                containers.append({
                    "name": container_name,
                    "exists": False,
                    "id": None
                })
        
        return {
            "database": {
                "name": DATABASE_NAME,
                "id": db_info["id"]
            },
            "containers": containers
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get database info: {str(e)}"
        ) 