from datetime import datetime, timedelta, timezone, UTC
from jose import jwt, JWTError
from app.config import SECRET_KEY, ALGORITHM
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
import random
import string
from typing import List, Dict, Any
from app.foundation_kit.database.cosmos import get_container
from app.foundation_kit.schemas.user import User
from passlib.context import CryptContext
import uuid
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from app.config import MAIL_USERNAME, MAIL_PASSWORD, MAIL_PORT, MAIL_SERVER, MAIL_FROM
from fastapi import BackgroundTasks
from dotenv import load_dotenv
import os

load_dotenv()

FRONTEND_URL = os.getenv("FRONTEND_URL")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30 # 30 days

conf = ConnectionConfig(
    MAIL_USERNAME=MAIL_USERNAME,
    MAIL_PASSWORD=MAIL_PASSWORD,
    MAIL_PORT=MAIL_PORT,
    MAIL_SERVER=MAIL_SERVER,
    MAIL_FROM=MAIL_FROM,
    MAIL_STARTTLS=False,
    MAIL_SSL_TLS=True,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True,
    TEMPLATE_FOLDER = None
)

# HTML Email Template with improved structure
CREDENTIALS_EMAIL = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to {company_name}</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; margin: 0; padding: 0;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: #0A2E42; padding: 20px; border-radius: 10px; text-align: center; color: #ffffff;">
            <h1 style="margin: 0; padding: 20px 0;">Welcome to {company_name}!</h1>
            <p style="font-size: 16px;">Your account has been successfully created.</p>
        </div>
        
        <div style="background: #ffffff; padding: 20px; border-radius: 10px; margin-top: 20px;">
            <p>Hello {email},</p>
            <p>Thank you for joining {company_name}. We're excited to have you on board!</p>
            <p>Here are your login credentials:</p>
            
            <div style="background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <p style="margin: 5px 0;"><strong>Email:</strong> {email}</p>
                <p style="margin: 5px 0;"><strong>Password:</strong> {password}</p>
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href='{frontend_url}/login' 
                   style="background: #04AA6D; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                    Log in Now
                </a>
            </div>
            
            <p style="color: #666666; font-size: 14px;">For security reasons, we recommend changing your password after your first login.</p>
        </div>
        
        <div style="text-align: center; margin-top: 20px; padding: 20px; color: #666666; font-size: 12px;">
            <p>This email was sent to {email}</p>
            <p>&copy; {current_year} {company_name}. All rights reserved.</p>
            <p>
                <a href="{frontend_url}/privacy" style="color: #666666; text-decoration: none;">Privacy Policy</a> | 
                <a href="{frontend_url}/terms" style="color: #666666; text-decoration: none;">Terms of Service</a>
            </p>
        </div>
    </div>
</body>
</html>
"""

FORGOT_PASSWORD_EMAIL = """
<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8" />
    <title>Reset Your Password</title>
    <style>
      body {{
        font-family: Arial, sans-serif;
        background-color: #f9fafb;
        padding: 20px;
        color: #333;
      }}
      .container {{
        max-width: 500px;
        margin: auto;
        background: #ffffff;
        padding: 30px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
      }}
      .btn {{
        display: inline-block;
        background: #2563eb;
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        text-decoration: none;
        font-weight: bold;
        margin-top: 20px;
        margin-bottom: 10px;
      }}
      .footer {{
        margin-top: 30px;
        font-size: 12px;
        color: #777;
      }}
    </style>
  </head>
  <body>
    <div class="container">
      <h2>Password Reset Request</h2>
      <p>Hello,</p>
      <p>
        We received a request to reset your password. Click the button below to
        set a new password:
      </p>
      <a href="{reset_link}" class="btn">Reset Password</a>
      <p>
        If you did not request this change, you can safely ignore this email.
        This link will expire in <strong>1 hour</strong> for your security.
      </p>
      <div class="footer">
        <p>Thank you,<br />The {company_name} Team</p>
      </div>
    </div>
  </body>
</html>
"""

# Admin Password Reset Email Template
RESET_PASSWORD_EMAIL = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Password Reset by Administrator - {company_name}</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; margin: 0; padding: 0;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: #0A2E42; padding: 20px; border-radius: 10px; text-align: center; color: #ffffff;">
            <h1 style="margin: 0; padding: 20px 0;">Password Reset by Administrator</h1>
            <p style="font-size: 16px;">Your password has been reset by an administrator.</p>
        </div>
        
        <div style="background: #ffffff; padding: 20px; border-radius: 10px; margin-top: 20px;">
            <p>Hello {first_name},</p>
            <p>An administrator has reset your password for your {company_name} account. This action was taken for security purposes or at your request.</p>
            
            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #dc3545;">
                <p style="margin: 5px 0; color: #dc3545; font-weight: bold;">Important Security Information:</p>
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>Your previous password is no longer valid</li>
                    <li>You will need to use the new password provided below</li>
                    <li>We recommend changing this password after your first login</li>
                </ul>
            </div>
            
            <div style="background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <p style="margin: 5px 0;"><strong>Email:</strong> {email}</p>
                <p style="margin: 5px 0;"><strong>New Password:</strong> {new_password}</p>
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href='{frontend_url}/login' 
                   style="background: #04AA6D; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                    Log in with New Password
                </a>
            </div>
            
            <div style="background: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107;">
                <p style="margin: 5px 0; color: #856404; font-weight: bold;">Security Recommendations:</p>
                <ul style="margin: 10px 0; padding-left: 20px; color: #856404;">
                    <li>Change your password immediately after logging in</li>
                    <li>Use a strong, unique password</li>
                    <li>Enable two-factor authentication if available</li>
                    <li>Contact support if you did not request this password reset</li>
                </ul>
            </div>
            
            <p style="color: #666666; font-size: 14px;">If you have any questions or concerns about this password reset, please contact your system administrator immediately.</p>
        </div>
        
        <div style="text-align: center; margin-top: 20px; padding: 20px; color: #666666; font-size: 12px;">
            <p>This email was sent to {email}</p>
            <p>&copy; {current_year} {company_name}. All rights reserved.</p>
            <p>
                <a href="{frontend_url}/privacy" style="color: #666666; text-decoration: none;">Privacy Policy</a> | 
                <a href="{frontend_url}/terms" style="color: #666666; text-decoration: none;">Terms of Service</a>
            </p>
        </div>
    </div>
</body>
</html>
"""


def generate_password():
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(random.choice(characters) for _ in range(8))

def create_access_token(data: dict, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES):
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict, expires_minutes: int = REFRESH_TOKEN_EXPIRE_MINUTES):
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        if not all(key in payload for key in ["sub", "roles"]):
            raise HTTPException(status_code=401, detail="Invalid token")
            
        return {
            "id": payload.get("id"),
            "first_name": payload.get("first_name"),
            "last_name": payload.get("last_name"),
            "email": payload["sub"],
            "roles": payload.get("roles", ["User"]),
            "institutions": payload.get("institutions", []),
            "hashed_password": payload.get("hashed_password", None)
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
def check_user_exists(email: str) -> List[Dict[str, Any]]:
    """Check if a user with the given email exists in the database."""
    container = get_container("users")
    query = f"SELECT * FROM c WHERE c.email = '{email}'"
    return list(container.query_items(query=query, enable_cross_partition_query=True))

def prepare_user_data(user: User) -> Dict[str, Any]:
    """Prepare user data for database insertion."""
    now = datetime.now(timezone.utc)
    hashed_password = pwd_context.hash(user.hashed_password)
    
    user_data = user.model_dump()
    user_data.update({
        "id": str(uuid.uuid4()),
        "hashed_password": hashed_password,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    })
    
    return user_data

def require_role(required_role: str):
    def role_checker(user: dict = Depends(get_current_user)):
        if required_role not in user["roles"]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return role_checker

def get_user_roles(user: dict):
    user_groups_container = get_container("user_groups")
    user_roles = []
    for role in user.get("roles", []):
        user_group = user_groups_container.read_item(item=role, partition_key=role)
        user_roles.append(user_group["tag"])
    return user_roles

async def send_welcome_email(email: str, password: str, background_tasks: BackgroundTasks, company_name: str) -> bool:
    """
    Send welcome email to the newly registered user.
    
    Args:
        email: Recipient email address
        password: User's original password (before hashing)
        background_tasks: FastAPI background tasks
        
    Returns:
        bool: True if email was queued successfully, False otherwise
    """
    try:
        # Get current year for copyright
        current_year = datetime.now().year
        
        message = MessageSchema(
            subject=f'Welcome to {company_name} - Your Account Details',
            recipients=[email],
            body=CREDENTIALS_EMAIL.format(
                email=email,
                password=password,
                frontend_url=FRONTEND_URL,
                current_year=current_year,
                company_name=company_name
            ),
            subtype=MessageType.html
        )
        
        # Create FastMail instance
        fm = FastMail(conf)
        
        # Add the actual send task with error handling
        async def send_email_with_logging():
            try:
                await fm.send_message(message)
            except Exception:
                raise

        background_tasks.add_task(send_email_with_logging)
        return True
    except Exception:
        return False

async def send_forgot_password_email(email: str,token: str, background_tasks: BackgroundTasks, company_name: str) -> bool:
    """
    Send forgot password email to the user.
    
    Args:
        email: Recipient email address
        token: Token for the reset password link
        background_tasks: FastAPI background tasks
        
    Returns:
        bool: True if email was queued successfully, False otherwise
    """
    try:
        reset_link = f"{FRONTEND_URL}/reset-password/{token}"

        message = MessageSchema(
            subject=f'Forgot Password - {company_name}',
            recipients=[email],
            body=FORGOT_PASSWORD_EMAIL.format(
                reset_link=reset_link,
                company_name=company_name
            ),
            subtype=MessageType.html
        )
        
        # Create FastMail instance
        fm = FastMail(conf)
        
        # Add the actual send task with error handling
        async def send_email_with_logging():
            try:
                await fm.send_message(message)
            except Exception as e:
                raise

        background_tasks.add_task(send_email_with_logging)
        return True
    except Exception as e:
        return False

async def send_reset_password_email(email: str, new_password: str, first_name: str, background_tasks: BackgroundTasks, company_name: str) -> bool:
    """
    Send reset password email to the user by admin.
    
    Args:
        email: Recipient email address
        new_password: The new password set by admin
        first_name: User's first name for personalization
        background_tasks: FastAPI background tasks
        company_name: Company name for branding
        
    Returns:
        bool: True if email was queued successfully, False otherwise
    """
    try:
        # Get current year for copyright
        current_year = datetime.now().year
        
        message = MessageSchema(
            subject=f'Password Reset by Administrator - {company_name}',
            recipients=[email],
            body=RESET_PASSWORD_EMAIL.format(
                email=email,
                new_password=new_password,
                first_name=first_name,
                frontend_url=FRONTEND_URL,
                current_year=current_year,
                company_name=company_name
            ),
            subtype=MessageType.html
        )
        
        # Create FastMail instance
        fm = FastMail(conf)
        
        # Add the actual send task with error handling
        async def send_email_with_logging():
            try:
                await fm.send_message(message)
            except Exception as e:
                raise

        background_tasks.add_task(send_email_with_logging)
        return True
    except Exception as e:
        return False