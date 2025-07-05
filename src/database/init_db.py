from dotenv import load_dotenv
import motor.motor_asyncio
import asyncio
import os
import datetime
from utils.hash import Hasher


load_dotenv()
def init_connection():
    """
    Initialize the database connection.
    """
    print(os.getenv("ADMIN_MONGODB_URL"))
    client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv("ADMIN_MONGODB_URL"))
    return client





async def init_user():
    """
    Create a user database in the admin db
    """
    client = init_connection()
    db = client.admin
    await db.command("createUser", os.getenv("MONGODB_USER"), pwd=os.getenv("MONGODB_PASSWORD"), roles=[{"role": "readWrite", "db": os.getenv("MONGODB_DB")}])
    print(f"User {os.getenv('MONGODB_USER')} created with readWrite access to {os.getenv('MONGODB_DB')} database.")
    await client.close()
    
async def init_admin_user():
    """
    Create an admin user in the Users collection if it does not exist.
    """
    client = init_connection()
    db = client[os.getenv("MONGODB_DB")]
    users = db["Users"]
    # Check if the user already exists
    user = await users.find_one({"email": "admin@walletech.com" })
    hash_password = Hasher.get_password_hash(os.getenv("ADMIN_PASSWORD"))
    if user is None:
        # Create the admin user
        admin_user = {
            "username": "admin",
            "email": "admin@walletech.com",
            "password": hash_password,
            "role": "admin",
            "created_at": datetime.datetime.utcnow(),
            "updated_at": datetime.datetime.utcnow(),
            "database": os.getenv("MONGODB_DB"),
        }
        await users.insert_one(admin_user)
        print("Admin user created.")
    else:
        print("Admin user already exists.")
    client.close()
    
async def before_start():
    """
    Run this function before starting the application.
    """
    print("Initializing database connection...")
    client = init_connection()
    db = client["admin"]
    # Check if the user already exists
    user = await db.command("usersInfo", os.getenv("MONGODB_USER"))
    if not user["users"]:
        await init_user()
        print(f"User {os.getenv('MONGODB_USER')} created.")
    else:
        print(f"User {os.getenv('MONGODB_USER')} already exists.")
    
    await init_admin_user()
    client.close()

# Add a synchronous wrapper to call in non-async contexts
def run_before_start():
    """Synchronous wrapper for before_start"""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(before_start())