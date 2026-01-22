# Backend Base - Generic Foundation Kit

A generic, reusable backend foundation built with FastAPI and Azure Cosmos DB that can be easily adapted for different projects. This base provides user management, role-based access control, institution management, and menu systems.

## Features

- **Generic Database Configuration**: Configurable Cosmos DB connection and container names
- **Auto-Container Creation**: Automatically creates required containers in new databases
- **Role-Based Access Control**: System with user groups and permissions
- **Institution Management**: Multi-tenant support with institution-based access
- **Menu System**: Role-based menu filtering and display
- **Data Seeding**: Automatic seeding of essential data (user groups, menus)
- **Email Integration**: Welcome email functionality for new users

## Quick Start

### 1. Environment Setup

Create a `.env` file in your project root:

```env
# Required: Cosmos DB Configuration
COSMOS_API_URI=your_cosmos_db_uri
COSMOS_API_PRIMARY_KEY=your_cosmos_db_key
COSMOS_DATABASE=your_database_name

# Optional: Container Names (defaults provided)
COSMOS_CONTAINER_USERS=users
COSMOS_CONTAINER_USER_GROUPS=user_groups
COSMOS_CONTAINER_INSTITUTIONS=institutions
COSMOS_CONTAINER_MENU=menu

# Optional: Security
SECRET_KEY=your_secret_key
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Initialize New Project Database

For a new project, you need to initialize the database and seed essential data:

```bash
# Start the application
uvicorn app.main:app --reload

# Then make a POST request to initialize the database
curl -X POST "http://localhost:8000/foundation-kit/database/setup-new-project" \
  -H "Authorization: Bearer YOUR_SYSTEM_ADMIN_TOKEN"
```

Or use the individual endpoints:

```bash
# 1. Initialize database and containers
POST /foundation-kit/database/initialize

# 2. Seed user groups (roles)
POST /foundation-kit/database/seed/user-groups

# 3. Seed menu structure
POST /foundation-kit/database/seed/menu

# 4. Or seed everything at once
POST /foundation-kit/database/seed/all
```

## API Endpoints

### Authentication (`/foundation-kit/auth`)

- `POST /register` - Register new user
- `POST /login-with-institution` - Login with institution context
- `POST /refresh-token` - Refresh access token
- `GET /me` - Get current user info
- `GET /users` - Get all users
- `PATCH /users/{user_id}` - Update user
- `DELETE /users/{user_id}` - Delete user

### Dashboard (`/foundation-kit/dashboard`)

- `GET /menu/` - Get role-based menu
- `GET /institutions/` - Get institutions
- `POST /institutions/` - Create institution
- `GET /user-groups/` - Get user groups
- `POST /user-groups/` - Create user group
- `GET /count/` - Get entity counts

### Database Management (`/foundation-kit/database`)

- `POST /initialize` - Initialize database and containers
- `GET /info` - Get database status
- `POST /seed/user-groups` - Seed default user groups
- `POST /seed/menu` - Seed default menu
- `POST /seed/all` - Seed all essential data
- `GET /export/user-groups` - Export user groups
- `POST /setup-new-project` - Complete new project setup

## Default User Groups

The system comes with these default user groups:

1. **SystemAdmin** - Full system access
2. **InstitutionAdmin** - Institution-level administration
3. **User** - Standard user access
4. **Guest** - Limited access

## Default Menu Structure

The system includes a default menu with role-based access:

- **Dashboard** - Accessible by all authenticated users
- **Users** - User management (SystemAdmin, InstitutionAdmin)
- **Institutions** - Institution management (SystemAdmin only)
- **User Groups** - Role management (SystemAdmin only)

## Using in Downstream Projects

### 1. Copy the Base Project

Copy this entire project structure to your new project.

### 2. Configure Environment

Update the `.env` file with your new Cosmos DB credentials:

```env
COSMOS_API_URI=https://your-new-cosmos-account.documents.azure.com:443/
COSMOS_API_PRIMARY_KEY=your_new_key
COSMOS_DATABASE=your_new_database_name
```

### 3. Initialize the New Database

```bash
# Start the application
uvicorn app.main:app --reload

# Initialize the new database
curl -X POST "http://localhost:8000/foundation-kit/database/setup-new-project" \
  -H "Authorization: Bearer YOUR_SYSTEM_ADMIN_TOKEN"
```

### 4. Create Your First System Admin

Since the new database will be empty, you'll need to create a system admin user. You can either:

a) Temporarily modify the registration endpoint to allow admin creation
b) Use the database directly to create the first admin user
c) Create a setup script

### 5. Extend the Base

Add your project-specific functionality by:

- Creating new routers in `app/routers/`
- Adding new schemas in `app/schemas/`
- Creating new services in `app/services/`
- Updating the menu structure in the data seeder

## Customization

### Adding New Containers

1. Update `app/config.py`:

```python
COSMOS_CONTAINER_YOUR_NEW_CONTAINER = os.getenv("COSMOS_CONTAINER_YOUR_NEW_CONTAINER", "your_new_container")
REQUIRED_CONTAINERS.append(COSMOS_CONTAINER_YOUR_NEW_CONTAINER)
```

2. Update `app/database/cosmos.py`:

```python
CONTAINER_CONFIG[COSMOS_CONTAINER_YOUR_NEW_CONTAINER] = {"partition_key": "/id"}
```

### Customizing User Groups

Modify the `get_default_user_groups()` method in `app/services/data_seeder.py` to include your custom roles.

### Customizing Menu Structure

Update the `get_default_menu()` method in `app/services/data_seeder.py` to include your custom menu items.

## Security Considerations

- Always use environment variables for sensitive configuration
- Regularly rotate your Cosmos DB keys
- Use strong secret keys for JWT tokens
- Implement proper CORS policies for production
- Consider adding rate limiting for production use

## Development

### Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your values

# Run the application
uvicorn app.main:app --reload
```

### Testing

```bash
# Run tests (if available)
pytest

# Or test endpoints manually
curl http://localhost:8000/docs
```

## Deployment

### Docker

```bash
# Build the image
docker build -t backend-base .

# Run the container
docker run -p 8000:8000 --env-file .env backend-base
```

### Azure App Service

1. Deploy to Azure App Service
2. Configure environment variables in the App Service settings
3. Ensure your Cosmos DB firewall allows connections from the App Service

## Troubleshooting

### Common Issues

1. **Database Connection Failed**

   - Check your Cosmos DB URI and key
   - Ensure the database exists or auto-creation is enabled
   - Check firewall settings

2. **Container Not Found**

   - Run the database initialization endpoint
   - Check container names in configuration

3. **Permission Denied**
   - Ensure user has the required roles
   - Check JWT token validity

### Logs

Check application logs for detailed error information. The application includes comprehensive logging for debugging.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
