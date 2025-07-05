# Auth routes

from fastapi import APIRouter, Depends, HTTPException, status
from services.auth import login_user, register_user
from models.user import UserLogin, UserRegister
router = APIRouter()

@router.post("/auth/login")
async def login(user: UserLogin):
    """
    Authenticate a user and return a JWT token.
    """
    return await login_user(user)

@router.post("/auth/register")
async def register(user: UserRegister):
    """
    Register a new user and return a JWT token.
    """
    return await register_user(user)

