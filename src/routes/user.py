from fastapi import APIRouter, HTTPException, Depends, Header
from services.auth import get_user_from_token
from typing import Optional

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/me")
async def get_current_user(authorization: Optional[str] = Header(None)):
    """
    Récupère les informations de l'utilisateur connecté à partir de son token JWT.
    
    Args:
        authorization: Header Authorization contenant le token Bearer
        
    Returns:
        dict: Informations de l'utilisateur (id, username, email, role, created_at, updated_at)
        
    Raises:
        HTTPException: Si le token est manquant, invalide ou expiré
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    # Extraire le token du header Authorization (format: "Bearer <token>")
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    # Récupérer les informations de l'utilisateur
    user_info = await get_user_from_token(token)
    return user_info


