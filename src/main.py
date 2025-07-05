from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from database.init_db import run_before_start
from routes import auth


app = FastAPI()

# Optional: allow CORS (Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change this in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include your routes here
app.include_router(auth.router, prefix="/api", tags=["auth"])

# Example route
@app.get("/")
async def root():
    return {"message": "Hello, FastAPI!"}


if __name__ == "__main__":
    run_before_start()  
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info", reload=True)
   