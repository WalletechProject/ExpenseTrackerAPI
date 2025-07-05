from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from database.init_db import init_connection
import os

db = init_connection()
db = db[os.getenv("MONGODB_DB")]
users_collection = db["Users"]



class UserBase(BaseModel):
    email: EmailStr = Field(..., min_length=5, max_length=50)
    role: Optional[str] = "user"
    
class UserLogin(UserBase):
    password: str =Field(..., min_length=8, max_length=50)

class UserRegister(UserBase):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=50)