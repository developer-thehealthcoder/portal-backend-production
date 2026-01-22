import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Secret key and algorithm
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

# Azure Cosmos DB Settings
COSMOS_API_URI = os.getenv("COSMOS_API_URI")
COSMOS_API_PRIMARY_KEY = os.getenv("COSMOS_API_PRIMARY_KEY")
COSMOS_DATABASE = os.getenv("COSMOS_DATABASE")

# Email configuration
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_PORT = int(os.getenv("MAIL_PORT", "465"))
MAIL_SERVER = os.getenv("MAIL_SERVER")
MAIL_FROM = os.getenv("MAIL_FROM")

COMPANY_NAME = os.getenv("COMPANY_NAME", "Med Office HQ")

# Container names - configurable but with sensible defaults
COSMOS_CONTAINER_USERS = os.getenv("COSMOS_CONTAINER_USERS", "users")
COSMOS_CONTAINER_USER_GROUPS = os.getenv("COSMOS_CONTAINER_USER_GROUPS", "user_groups")
COSMOS_CONTAINER_INSTITUTIONS = os.getenv("COSMOS_CONTAINER_INSTITUTIONS", "institutions")
COSMOS_CONTAINER_MENU = os.getenv("COSMOS_CONTAINER_MENU", "menu")
COSMOS_CONTAINER_PASSWORD_RESETS = os.getenv("COSMOS_CONTAINER_PASSWORD_RESETS", "password_resets")

# Required containers for the application to function
REQUIRED_CONTAINERS = [
    COSMOS_CONTAINER_USERS,
    COSMOS_CONTAINER_USER_GROUPS,
    COSMOS_CONTAINER_INSTITUTIONS,
    COSMOS_CONTAINER_MENU,
    COSMOS_CONTAINER_PASSWORD_RESETS
]

# Backend URL for AI telephone service
BACKEND_URL = os.getenv("BACKEND_URL")