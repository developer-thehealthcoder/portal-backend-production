from azure.cosmos import exceptions
from app.foundation_kit.services.auth_service import create_access_token, create_refresh_token, get_current_user, generate_password, get_user_roles, check_user_exists, send_welcome_email, conf, send_forgot_password_email, send_reset_password_email
from passlib.context import CryptContext
from app.foundation_kit.schemas.user import User, UserUpdate
from jose import JWTError, jwt
from datetime import datetime, timezone, UTC, timedelta
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import APIRouter, Request, HTTPException, Depends, Security, Body
from app.foundation_kit.database.cosmos import get_container
import uuid
from fastapi import BackgroundTasks
from typing import Dict, Any
from app.config import SECRET_KEY, ALGORITHM, COMPANY_NAME
from app.foundation_kit.schemas.auth import PasswordUpdate, AdminPasswordResetRequest
import secrets, hashlib

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.get("/me")
async def get_current_user(current_user: dict = Depends(get_current_user)):
    return current_user

@router.post("/register", dependencies=[Security(get_current_user)])
async def register(
    user: User,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    
    # Get user roles safely
    try:
        user_roles = get_user_roles(current_user)
    except Exception:
        # If we can't get user roles, just use the roles from the token
        user_roles = current_user.get("roles", [])
    
    container = get_container("users")
    email_sent = False

    # Handle institution admin case
    if "InstitutionAdmin" in user_roles:
        existing_users = check_user_exists(user.email)
        if existing_users:
            existing_user = existing_users[0]
            existing_user["institutions"].append(current_user["selected_institution"])
            container.replace_item(item=existing_user["id"], body=existing_user)
            return {"message": "Existing user added to institution successfully."}

    try:
        # Check for existing user
        existing_users = check_user_exists(user.email)
        if existing_users:
            raise HTTPException(
                status_code=400,
                detail="A user with this email already exists"
            )
        
        original_password = user.hashed_password
        
        if user.auto_generated_password:
            generated_password = generate_password()
            original_password = generated_password
            user.hashed_password = pwd_context.hash(generated_password)
        else:
            user.hashed_password = pwd_context.hash(user.hashed_password)

        # Prepare user data first
        now = datetime.now(timezone.utc)
        user.id = str(uuid.uuid4())
        user.created_at = now.isoformat()
        user.updated_at = now.isoformat()
        
        # Save user first
        container.create_item(body=user.model_dump())
        
        # Try to send welcome email
        try:
            email_sent = await send_welcome_email(user.email, original_password, background_tasks, COMPANY_NAME)
        except Exception:
            email_sent = False
        
        response = {
            "message": "User registered successfully.",
            "email_status": "queued" if email_sent else "failed",
            "email": user.email,
            "debug_info": {
                "email_server": conf.MAIL_SERVER,
                "email_port": conf.MAIL_PORT,
                "email_ssl": conf.MAIL_SSL_TLS,
                "email_starttls": conf.MAIL_STARTTLS
            }
        }
        
        return response
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
@router.patch("/users/{user_id}")
async def update_user(user_id: str, user: UserUpdate):
    container = get_container("users")
    try:
        existing_user = container.read_item(item=user_id, partition_key=user_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Convert existing user to dict for easier manipulation
    user_dict = existing_user
    
    # Update only provided fields
    update_data = user.model_dump(exclude_unset=True)
    
    # Handle password update if provided
    if "password_update" in update_data:
        password_update = update_data.pop("password_update")
        
        # Verify current password
        if not pwd_context.verify(password_update["current_password"], existing_user["hashed_password"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        
        # Hash and set new password
        update_data["hashed_password"] = pwd_context.hash(password_update["new_password"])
    
    # Update the timestamp
    update_data["updated_at"] = datetime.now(UTC).isoformat()
    
    # Update the user_dict with new values
    user_dict.update(update_data)
    
    # Save the updated user
    container.replace_item(item=user_id, body=user_dict)
    return {"message": "User updated successfully."}

@router.post("/change-password")
async def change_password(passwords: PasswordUpdate, current_user: dict = Depends(get_current_user)):
    container = get_container("users")
    user = container.read_item(item=current_user["id"], partition_key=current_user["id"])
    
    if not pwd_context.verify(passwords.current_password, user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Invalid credentials")
    
    user["hashed_password"] = pwd_context.hash(passwords.new_password)
    container.replace_item(item=current_user["id"], body=user)
    return {"message": "Password updated successfully."}

@router.get("/users")
async def get_users(current_user: dict = Depends(get_current_user)):
    container = get_container("users")
    user_roles = get_user_roles(current_user)
        
    # System admin can see all users
    if "SystemAdmin" in user_roles:
        query = "SELECT * FROM c"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        return items
    
    # Institution admin can only see users from their institution
    elif "InstitutionAdmin" in user_roles:
        institution_ids = current_user["institutions"]
        
        if not institution_ids:
            raise HTTPException(status_code=400, detail="Admin user has no associated institutions")
            
        institution_conditions = " OR ".join([f"ARRAY_CONTAINS(c.institutions, '{inst}')" for inst in institution_ids])
        query = f"SELECT * FROM c WHERE {institution_conditions}"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        return items
    
    else:
        raise HTTPException(status_code=403, detail="Insufficient permissions to view users")

@router.delete("/users/{user_id}", dependencies=[Security(get_current_user)])
async def delete_user(user_id: str, current_user: dict = Depends(get_current_user)):
    users_container = get_container("users")

    user_roles = get_user_roles(current_user)

    if "SystemAdmin" in user_roles:
        pass
    elif "InstitutionAdmin" in user_roles:
        user = users_container.read_item(item=user_id, partition_key=user_id)
        delete_user_roles = get_user_roles(user)

        if user_id == current_user["id"]:
            raise HTTPException(status_code=403, detail="Cannot delete yourself")
        elif "SystemAdmin" in delete_user_roles:
            raise HTTPException(status_code=403, detail="Cannot delete SystemAdmin")
        elif len(user["institutions"]) > 1:
            try:
                user["institutions"].remove(user["selected_institution"])
                users_container.replace_item(item=user_id, body=user)
                return {"message": "Institution removed from user successfully."}
            except Exception as e:
                raise HTTPException(status_code=500, detail="Institution not found in user")
        else:
            pass
    else:
        raise HTTPException(status_code=403, detail="Insufficient permissions to delete user")
    
    try:
        # First check if user exists
        users_container.read_item(item=user_id, partition_key=user_id)
        # If user exists, delete it
        users_container.delete_item(item=user_id, partition_key=user_id)
        return {"message": "User deleted successfully."}
    except Exception as e:
        if "NotFound" in str(e):
            raise HTTPException(status_code=404, detail="User not found")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/user-exists")
async def user_exists(form_data: OAuth2PasswordRequestForm = Depends()):
    users_container = get_container("users")
    institutions_container = get_container("institutions")
    institutions = []
    query = f"SELECT * FROM c WHERE c.email = '{form_data.username}'"
    items = list(users_container.query_items(query=query, enable_cross_partition_query=True))
    
    if not items:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    
    user = items[0]
    
    try:
        password_verified = pwd_context.verify(form_data.password, user['hashed_password'])   
        if not password_verified:
            raise HTTPException(status_code=400, detail="Invalid credentials")
        
        # Check if user has institutions before iterating
        if user.get('institutions'):
            for institution_id in user['institutions']:
                try:
                    institution = institutions_container.read_item(institution_id, partition_key=institution_id)
                    institutions.append({
                        "id": institution["id"],
                        "name": institution.get("name", "")
                    })
                except Exception as e:
                    continue

        return {"user_institutions": institutions}
    except Exception as e:
        print("error during password verification", e)
        raise HTTPException(status_code=500, detail="Error during password verification")

@router.post("/login-with-institution")
async def login_with_institution(institution_id: str = None, form_data: OAuth2PasswordRequestForm = Depends()):
    container = get_container("users")
    
    # Update user's selected institution
    query = f"SELECT * FROM c WHERE c.email = '{form_data.username}'"
    items = list(container.query_items(query=query, enable_cross_partition_query=True))
    if not items:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = items[0]
    
    # Handle case where institution_id is undefined/empty
    if not institution_id or institution_id == "undefined" or institution_id.strip() == "":
        # User has no institution, allow login without institution
        user['selected_institution'] = None
        user['last_login'] = datetime.now(UTC).isoformat()
        container.replace_item(item=user['id'], body=user)
        
        # Create token without institution
        token_data = {
            "id": user['id'],
            "sub": user['email'],
            "roles": user.get('roles', ['User']),
            "first_name": user.get('first_name'),
            "last_name": user.get('last_name'),
            "institutions": user.get('institutions', []),
            "selected_institution": None,
            "hashed_password": user.get('hashed_password', None)
        }
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "selected_institution": None,
        }
    
    # If institution_id is provided, validate it
    if institution_id not in user.get('institutions', []):
        raise HTTPException(status_code=400, detail="Invalid institution selection")

    user['selected_institution'] = institution_id
    user['last_login'] = datetime.now(UTC).isoformat()
    container.replace_item(item=user['id'], body=user)
    
    # Create new token with updated institution
    token_data = {
        "id": user['id'],
        "sub": user['email'],
        "roles": user.get('roles', ['User']),
        "first_name": user.get('first_name'),
        "last_name": user.get('last_name'),
        "institutions": user.get('institutions', []),
        "selected_institution": institution_id,
        "hashed_password": user.get('hashed_password', None)
    }
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "selected_institution": institution_id,
    }

@router.post("/refresh-token")
async def refresh_token(request: Request):
    body = await request.json()
    refresh_token = body.get("refresh_token")

    if not refresh_token:
        raise HTTPException(status_code=400, detail="Missing refresh token")

    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Get user data from database to include in new access token
        container = get_container("users")
        query = f"SELECT * FROM c WHERE c.email = '{user_id}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        
        if not items:
            raise HTTPException(status_code=404, detail="User not found")
            
        user = items[0]
        
        # Create new access token with all necessary user data
        token_data = {
            "id": user['id'],
            "sub": user['email'],
            "roles": user.get('roles', ['User']),
            "first_name": user.get('first_name'),
            "last_name": user.get('last_name'),
            "institutions": user.get('institutions', []),
            "selected_institution": user.get('selected_institution'),
            "hashed_password": user.get('hashed_password', None)
        }
        access_token = create_access_token(token_data)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token  # Return the same refresh token
        }

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

@router.post('/forgot-password')
async def forgot_password(email: str, background_tasks: BackgroundTasks):
    try:
        users_container = get_container("users")
        resets_container = get_container("password_resets")
        query = "SELECT * FROM c WHERE LOWER(c.email) = LOWER(@email)"

        items = list(users_container.query_items(
            query=query,
            parameters=[{"name": "@email", "value": email}],
            enable_cross_partition_query=True
        ))
        if not items:
            raise HTTPException(status_code=404, detail="User not found")
        user = items[0]

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        reset_doc = {
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "token_hash": token_hash,
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "used": False
        }
        resets_container.create_item(body=reset_doc)

        # Send email with raw token
        result = await send_forgot_password_email(user["email"], token, background_tasks, COMPANY_NAME)

        return {
            "message": "If that email exists, a reset link was sent.",
            "email_status": "sent" if result else "failed",
            "debug_info": {
                "email_server": conf.MAIL_SERVER,
                "email_port": conf.MAIL_PORT,
                "email_ssl": conf.MAIL_SSL_TLS,
                "email_starttls": conf.MAIL_STARTTLS
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reset-password")
async def reset_password(token: str = Body(...), new_password: str = Body(...)):
    resets_container = get_container("password_resets")
    users_container = get_container("users")

    # Hash incoming token
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # Look up token
    query = "SELECT * FROM c WHERE c.token_hash = @token_hash AND c.used = false"
    results = list(resets_container.query_items(
        query=query,
        parameters=[{"name": "@token_hash", "value": token_hash}],
        enable_cross_partition_query=True
    ))

    if not results:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    reset_entry = results[0]

    # Check expiry
    if datetime.fromisoformat(reset_entry["expires_at"]) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Token expired")

    # Fetch user
    user = users_container.read_item(item=reset_entry["user_id"], partition_key=reset_entry["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update password
    user["hashed_password"] = pwd_context.hash(new_password)
    users_container.replace_item(item=user["id"], body=user)

    # Mark reset entry as used
    reset_entry["used"] = True
    resets_container.replace_item(item=reset_entry["id"], body=reset_entry)

    return {"message": "Password reset successfully"}

@router.post("/reset-password-by-admin")
async def reset_password_by_admin(request_data: AdminPasswordResetRequest, background_tasks: BackgroundTasks = BackgroundTasks(), current_user: dict = Depends(get_current_user)):
    # Extract data from request body
    user_id = request_data.user_id
    new_password = request_data.new_password
    
    # Check if current user has admin privileges
    user_roles = get_user_roles(current_user)
    if "SystemAdmin" not in user_roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions to reset password")
    
    users_container = get_container("users")
    user = users_container.read_item(item=user_id, partition_key=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update password
    user["hashed_password"] = pwd_context.hash(new_password)
    user["updated_at"] = datetime.now(UTC).isoformat()
    users_container.replace_item(item=user_id, body=user)
    
    # Send email with new password
    first_name = user.get("first_name", "User")
    result = await send_reset_password_email(
        user["email"], 
        new_password, 
        first_name, 
        background_tasks, 
        COMPANY_NAME
    )
    
    return {
        "message": "Password reset successfully and email sent", 
        "email_status": "sent" if result else "failed",
        "user_email": user["email"],
        "reset_by": current_user["email"]
    }

@router.get("/check-app-password")
async def has_app_password(current_user: dict = Depends(get_current_user)):
    container = get_container("users")
    try:
        query = f"SELECT * FROM c WHERE c.email = '{current_user['email']}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        if not items:
            raise HTTPException(status_code=404, detail="User not found")
        user = items[0]
        app_password = user.get("app_password")
        return {"has_app_password": app_password is not None, "app_password": app_password}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

@router.post("/change-app-password")
async def change_app_password(app_password: str = Body(...), current_user: dict = Depends(get_current_user)):
    try:
        container = get_container("users")
        query = f"SELECT * FROM c WHERE c.email = '{current_user['email']}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        if not items:
            raise HTTPException(status_code=404, detail="User not found")
        items[0]["app_password"] = app_password
        container.replace_item(item=items[0]["id"], body=items[0])
        return {"message": "App password updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")