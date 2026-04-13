from pydantic import BaseModel


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str


class AdminUserRead(BaseModel):
    username: str
