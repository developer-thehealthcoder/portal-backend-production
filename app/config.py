# Secret key and algorithm
SECRET_KEY = "vKOXkQmiC_X676JCwBVXyr712kj643YZjNmc1Vd7aMpD4eRar-x451MqEcGbehDn0MMF0_qS3egfB-Y5Nw3J6g"
ALGORITHM = "HS256"

# Azure Cosmos DB Settings
COSMOS_API_URI = "https://medofficehq-db.documents.azure.com:443/"
COSMOS_API_PRIMARY_KEY = "TQQWhtZiIFUraLePCYMfl25PQR4HygOjMEl0Fezfb2zkjpoXw259bW3bVoSvc1FVDKj41UlTsVxgACDbX6O8bQ=="
COSMOS_DATABASE = "med-office-hq"

# Email configuration
MAIL_USERNAME = "emailadmin@tellurium.me"
MAIL_PASSWORD = "MbE8vbUvDTDfNCDP4qtU"
MAIL_PORT = 465
MAIL_SERVER = "wednesday.mxrouting.net"
MAIL_FROM = "Tellurium <emailadmin@tellurium.me>"

COMPANY_NAME = "Med Office HQ"

# Container names - configurable but with sensible defaults
COSMOS_CONTAINER_USERS = "users"
COSMOS_CONTAINER_USER_GROUPS = "user_groups"
COSMOS_CONTAINER_INSTITUTIONS = "institutions"
COSMOS_CONTAINER_MENU = "menu"
COSMOS_CONTAINER_PASSWORD_RESETS = "password_resets"

# Required containers for the application to function
REQUIRED_CONTAINERS = [
    COSMOS_CONTAINER_USERS,
    COSMOS_CONTAINER_USER_GROUPS,
    COSMOS_CONTAINER_INSTITUTIONS,
    COSMOS_CONTAINER_MENU,
    COSMOS_CONTAINER_PASSWORD_RESETS
]

# Backend URL for AI telephone service
BACKEND_URL = "https://medofficehq-backend-hjg4buhcd4b2hfab.canadacentral-01.azurewebsites.net"