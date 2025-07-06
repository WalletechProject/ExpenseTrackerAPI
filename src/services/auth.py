from models.user import UserBase, UserRegister, UserLogin, users_collection
from fastapi import HTTPException
from utils.hash import Hasher
import jwt
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv


load_dotenv()

ALGORITHM = "HS256"



async def login_user(user: UserLogin):
    """
    Authenticate a user and return a JWT token.
    """
    # Check if the user exists
    db_user = await users_collection.find_one({"email": user.email})
    if not db_user:
        raise HTTPException(status_code=400, detail="Invalid username or password")

    # Verify the password
    if not Hasher.verify_password(user.password, db_user["password"]):
        raise HTTPException(status_code=400, detail="Invalid username or password")

    # Create a JWT token
    token = create_access_token(data={"sub": db_user["email"]})
    
    return {"access_token": token}

async def register_user(user: UserRegister):
    """
    Register a new user and return a JWT token.
    """
    # Check if the user already exists
    db_user = await users_collection.find_one({"email": user.email})
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    password_hash = Hasher.get_password_hash(user.password)
    
    new_user_data = {
        "username": user.username,
        "email": user.email,
        "password": password_hash,
        "role": user.role,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "database": os.getenv("MONGODB_DB"),
    }
    new_user = users_collection.insert_one(new_user_data)
    # Create a JWT token
    token = create_access_token(data={"sub": user.email})
    return {"access_token": token}

    
def create_access_token(data: dict, expires_delta: timedelta = None):
    """
    Create a JWT token with the given data and expiration time.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, os.getenv("JWT_SECRET"), algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    """
    Verify and decode a JWT token.
    Returns the user email if valid, raises HTTPException if invalid.
    """
    try:
        payload = jwt.decode(token, os.getenv("JWT_SECRET"), algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return email
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_user_from_token(token: str):
    """
    Get user information from JWT token.
    """
    email = verify_token(token)
    
    # Find user in database
    db_user = await users_collection.find_one({"email": email})
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Remove sensitive information
    user_info = {
        "id": str(db_user["_id"]),
        "username": db_user.get("username"),
        "email": db_user["email"],
        "role": db_user.get("role", "user"),
        "created_at": db_user.get("created_at"),
        "updated_at": db_user.get("updated_at")
    }
    
    return user_info