from typing import Optional, List
from uuid import uuid4
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime

class User(BaseModel):
    id: str = str(uuid4())
    first_name: str
    last_name: str
    email: str
    hashed_password: str = Field(..., alias="password")  # Accept 'password' on input
    auto_generated_password: bool = False
    roles: Optional[List[str]] = None  # e.g., 'System Admin', 'Institution Admin'
    institutions: Optional[List[str]] = None
    is_active: bool = True
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    password_update: Optional[PasswordUpdate] = None
    roles: Optional[List[str]] = None
    institutions: Optional[List[str]] = None
    is_active: Optional[bool] = None

class Institution(BaseModel):
    id: str = str(uuid4())
    name: str
    description: Optional[str] = None
    user_groups: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class UserGroup(BaseModel):
    id: str = str(uuid4())
    name: str
    tag: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# Input schema for creating user group
class UserGroupCreate(BaseModel):
    id: str
    name: str
    tag: str
    description: Optional[str] = None
    menu_items: List[str]  # list of menu/submenu IDs to grant access to

class UserBase(BaseModel):
    email: EmailStr
    display_name: str

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    id: str
    hashed_password: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

class UserResponse(UserBase):
    id: str
    is_active: bool
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str

class TokenData(BaseModel):
    email: Optional[str] = None
    user_id: Optional[str] = None 
