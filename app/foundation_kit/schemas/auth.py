from pydantic import BaseModel

class SignupRequest(BaseModel):
    email: str
    password: str
    display_name: str

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    local_id: str
    email: str
    display_name: str
    id_token: str
    refresh_token: str

class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class RefreshTokenResponse(BaseModel):
    id_token: str
    refresh_token: str
    expires_in: str

class ResetPassRequest(BaseModel):
    email: str

class AdminPasswordResetRequest(BaseModel):
    user_id: str
    new_password: str
