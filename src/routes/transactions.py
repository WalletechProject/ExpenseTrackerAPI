from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Dict, Any, Optional
from datetime import date, datetime, timedelta
import sys
import os

# Ajouter le répertoire parent au chemin pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.transactions import transaction_service
from services.smart_sync import smart_sync_service
from database.bank_repository import bank_repository
from models.transaction import Transaction
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================================
# ENDPOINTS OPTIMISÉS POUR LA VERSION GRATUITE (50 APPELS/MOIS)
# ============================================================================

@router.get("/api-usage")
async def get_api_usage():
    """
    Affiche l'utilisation de l'API GoCardless ce mois-ci
    """
    try:
        used_calls = await bank_repository.get_api_calls_this_month()
        remaining = 50 - used_calls
        
        return {
            "status": "success",
            "data": {
                "used_calls": used_calls,
                "remaining_calls": max(0, remaining),
                "monthly_limit": 50,
                "usage_percentage": (used_calls / 50) * 100
            },
            "message": f"API utilisation: {used_calls}/50 appels ce mois"
        }
    except Exception as e:
        logger.error(f"Error getting API usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync/recommendations/{requisition_id}")
async def get_sync_recommendations(requisition_id: str):
    """
    Recommandations intelligentes pour la synchronisation
    """
    try:
        recommendations = await smart_sync_service.get_sync_recommendations(requisition_id)
        return {
            "status": "success",
            "data": recommendations,
            "message": "Recommandations générées"
        }
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/smart/{requisition_id}")
async def smart_sync(requisition_id: str):
    """
    Synchronisation intelligente - choisit automatiquement le meilleur type de sync
    Optimisé pour minimiser les appels API
    """
    try:
        result = await smart_sync_service.smart_sync(requisition_id)
        return {
            "status": "success",
            "data": result,
            "message": f"Synchronisation {result['sync_type']} terminée avec succès"
        }
    except Exception as e:
        logger.error(f"Error in smart sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/initial/{requisition_id}")
async def initial_full_sync(requisition_id: str):
    """
    Synchronisation initiale complète - récupère 90 jours d'historique
    À utiliser UNIQUEMENT pour la première synchronisation
    """
    try:
        # Vérifier qu'il n'y a pas déjà eu de sync
        requisition = await bank_repository.db.requisitions.find_one({"requisition_id": requisition_id})
        if requisition and requisition.get("last_sync"):
            return {
                "status": "warning",
                "message": "Une synchronisation a déjà été effectuée. Utilisez /sync/incremental ou /sync/smart"
            }
        
        result = await smart_sync_service.initial_full_sync(requisition_id)
        return {
            "status": "success",
            "data": result,
            "message": "Synchronisation initiale complète terminée"
        }
    except Exception as e:
        logger.error(f"Error in initial sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/incremental/{requisition_id}")
async def incremental_sync(requisition_id: str):
    """
    Synchronisation incrémentale - récupère seulement les nouvelles transactions
    Recommandé tous les 3-4 jours
    """
    try:
        result = await smart_sync_service.incremental_sync(requisition_id)
        return {
            "status": "success",
            "data": result,
            "message": "Synchronisation incrémentale terminée"
        }
    except Exception as e:
        logger.error(f"Error in incremental sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ENDPOINTS DE CONSULTATION (PAS D'APPELS API)
# ============================================================================

@router.get("/stored/accounts/{user_id}")
async def get_stored_accounts_by_user(user_id: str):
    """
    Récupère les comptes stockés en base pour un utilisateur spécifique (pas d'appel API)
    """
    try:
        # Validation de l'user_id
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=400, detail="L'user_id ne peut pas être vide")
        
        # Vérifier que l'utilisateur existe
        user_exists = await bank_repository.validate_user_id(user_id)
        if not user_exists:
            raise HTTPException(
                status_code=404, 
                detail=f"L'utilisateur avec l'ID '{user_id}' n'existe pas dans la base de données"
            )
        
        accounts_cursor = bank_repository.db.accounts.find({"user_id": user_id})
        accounts = await accounts_cursor.to_list(length=None)
        
        # Convertir les ObjectId en strings pour la sérialisation JSON
        serializable_accounts = []
        for account in accounts:
            # Convertir l'ObjectId en string
            if "_id" in account:
                account["_id"] = str(account["_id"])
            
            # Enrichir avec les statistiques
            account_id = account["account_id"]
            account["summary"] = await bank_repository.get_account_summary(account_id)
            
            serializable_accounts.append(account)
        
        return {
            "status": "success",
            "data": serializable_accounts,
            "count": len(serializable_accounts),
            "user_id": user_id,
            "message": "Comptes récupérés depuis la base de données pour l'utilisateur"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stored accounts for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stored/transactions/user/{user_id}")
async def get_stored_transactions_by_user(
    user_id: str,
    date_from: Optional[date] = Query(None, description="Date de début"),
    date_to: Optional[date] = Query(None, description="Date de fin"),
    limit: Optional[int] = Query(100, description="Nombre max de transactions")
):
    """
    Récupère toutes les transactions stockées en base pour un utilisateur (pas d'appel API)
    """
    try:
        # Validation de l'user_id
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=400, detail="L'user_id ne peut pas être vide")
        
        # Vérifier que l'utilisateur existe
        user_exists = await bank_repository.validate_user_id(user_id)
        if not user_exists:
            raise HTTPException(
                status_code=404, 
                detail=f"L'utilisateur avec l'ID '{user_id}' n'existe pas dans la base de données"
            )
        
        # D'abord, récupérer tous les comptes de l'utilisateur
        accounts_cursor = bank_repository.db.accounts.find({"user_id": user_id})
        accounts = await accounts_cursor.to_list(length=None)
        
        if not accounts:
            return {
                "status": "success",
                "data": [],
                "count": 0,
                "user_id": user_id,
                "message": "Aucun compte trouvé pour cet utilisateur"
            }
        
        # Récupérer les IDs des comptes
        account_ids = [account["account_id"] for account in accounts]
        
        # Construire la requête pour les transactions
        query = {"account_id": {"$in": account_ids}}
        if date_from:
            query["bookingDate"] = {"$gte": date_from}
        if date_to:
            if "bookingDate" in query:
                query["bookingDate"]["$lte"] = date_to
            else:
                query["bookingDate"] = {"$lte": date_to}
        
        # Récupérer les transactions
        transactions_cursor = bank_repository.db.transactions.find(query).sort("bookingDate", -1).limit(limit)
        transactions = await transactions_cursor.to_list(length=None)
        
        # Convertir les ObjectId en strings
        serializable_transactions = []
        for transaction in transactions:
            if "_id" in transaction:
                transaction["_id"] = str(transaction["_id"])
            serializable_transactions.append(transaction)
        
        return {
            "status": "success",
            "data": serializable_transactions,
            "count": len(serializable_transactions),
            "user_id": user_id,
            "accounts_count": len(accounts),
            "message": f"Transactions récupérées depuis la base de données pour l'utilisateur"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stored transactions for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stored/transactions/{account_id}")
async def get_stored_transactions(
    account_id: str,
    date_from: Optional[date] = Query(None, description="Date de début"),
    date_to: Optional[date] = Query(None, description="Date de fin"),
    limit: Optional[int] = Query(100, description="Nombre max de transactions")
):
    """
    Récupère les transactions stockées en base pour un compte spécifique (pas d'appel API)
    """
    try:
        transactions = await bank_repository.get_stored_transactions(account_id, date_from, date_to, limit)
        
        return {
            "status": "success",
            "data": transactions,
            "count": len(transactions),
            "account_id": account_id,
            "message": f"Transactions récupérées depuis la base de données"
        }
    except Exception as e:
        logger.error(f"Error getting stored transactions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stored/summary/user/{user_id}")
async def get_stored_summary_by_user(
    user_id: str,
    days_back: int = Query(30, description="Nombre de jours en arrière pour le résumé")
):
    """
    Génère un résumé financier pour un utilisateur depuis les données stockées (pas d'appel API)
    """
    try:
        # Validation de l'user_id
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=400, detail="L'user_id ne peut pas être vide")
        
        # Vérifier que l'utilisateur existe
        user_exists = await bank_repository.validate_user_id(user_id)
        if not user_exists:
            raise HTTPException(
                status_code=404, 
                detail=f"L'utilisateur avec l'ID '{user_id}' n'existe pas dans la base de données"
            )
        
        # Récupérer tous les comptes de l'utilisateur
        accounts_cursor = bank_repository.db.accounts.find({"user_id": user_id})
        accounts = await accounts_cursor.to_list(length=None)
        
        if not accounts:
            raise HTTPException(status_code=404, detail="Aucun compte trouvé pour cet utilisateur")
        
        # Date limite pour le résumé
        date_from = date.today() - timedelta(days=days_back)
        
        total_income = 0.0
        total_expenses = 0.0
        total_transactions = 0
        accounts_summary = []
        
        for account in accounts:
            account_id = account["account_id"]
            
            # Pipeline d'agrégation pour les statistiques
            pipeline = [
                {
                    "$match": {
                        "account_id": account_id,
                        "bookingDate": {"$gte": date_from}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "transaction_count": {"$sum": 1},
                        "total_income": {
                            "$sum": {
                                "$cond": [
                                    {"$gte": [{"$toDouble": "$transactionAmount.amount"}, 0]},
                                    {"$toDouble": "$transactionAmount.amount"},
                                    0
                                ]
                            }
                        },
                        "total_expenses": {
                            "$sum": {
                                "$cond": [
                                    {"$lt": [{"$toDouble": "$transactionAmount.amount"}, 0]},
                                    {"$abs": {"$toDouble": "$transactionAmount.amount"}},
                                    0
                                ]
                            }
                        }
                    }
                }
            ]
            
            result = await bank_repository.db.transactions.aggregate(pipeline).to_list(length=1)
            account_stats = result[0] if result else {
                "transaction_count": 0,
                "total_income": 0,
                "total_expenses": 0
            }
            
            total_income += account_stats["total_income"]
            total_expenses += account_stats["total_expenses"]
            total_transactions += account_stats["transaction_count"]
            
            accounts_summary.append({
                "account_id": account_id,
                "account_name": account.get("details", {}).get("name", "Compte inconnu"),
                "requisition_id": account.get("requisition_id"),
                "stats": account_stats
            })
        
        return {
            "status": "success",
            "data": {
                "user_id": user_id,
                "period": {
                    "from": date_from.isoformat(),
                    "to": date.today().isoformat(),
                    "days": days_back
                },
                "global_summary": {
                    "total_transactions": total_transactions,
                    "total_income": round(total_income, 2),
                    "total_expenses": round(total_expenses, 2),
                    "net_balance": round(total_income - total_expenses, 2)
                },
                "accounts_summary": accounts_summary,
                "accounts_count": len(accounts)
            },
            "message": f"Résumé généré depuis les données stockées pour l'utilisateur ({days_back} derniers jours)"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating stored summary for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stored/summary/{requisition_id}")
async def get_stored_summary(
    requisition_id: str,
    days_back: int = Query(30, description="Nombre de jours en arrière pour le résumé")
):
    """
    Génère un résumé financier depuis les données stockées par requisition_id (pas d'appel API)
    DEPRECATED: Utilisez /stored/summary/user/{user_id} à la place
    """
    try:
        # Récupérer tous les comptes de la réquisition
        accounts_cursor = bank_repository.db.accounts.find({"requisition_id": requisition_id})
        accounts = await accounts_cursor.to_list(length=None)
        
        if not accounts:
            raise HTTPException(status_code=404, detail="Aucun compte trouvé pour cette réquisition")
        
        # Date limite pour le résumé
        date_from = date.today() - timedelta(days=days_back)
        
        total_income = 0.0
        total_expenses = 0.0
        total_transactions = 0
        accounts_summary = []
        
        for account in accounts:
            account_id = account["account_id"]
            
            # Pipeline d'agrégation pour les statistiques
            pipeline = [
                {
                    "$match": {
                        "account_id": account_id,
                        "bookingDate": {"$gte": date_from}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "transaction_count": {"$sum": 1},
                        "total_income": {
                            "$sum": {
                                "$cond": [
                                    {"$gte": [{"$toDouble": "$transactionAmount.amount"}, 0]},
                                    {"$toDouble": "$transactionAmount.amount"},
                                    0
                                ]
                            }
                        },
                        "total_expenses": {
                            "$sum": {
                                "$cond": [
                                    {"$lt": [{"$toDouble": "$transactionAmount.amount"}, 0]},
                                    {"$abs": {"$toDouble": "$transactionAmount.amount"}},
                                    0
                                ]
                            }
                        }
                    }
                }
            ]
            
            result = await bank_repository.db.transactions.aggregate(pipeline).to_list(length=1)
            account_stats = result[0] if result else {
                "transaction_count": 0,
                "total_income": 0,
                "total_expenses": 0
            }
            
            total_income += account_stats["total_income"]
            total_expenses += account_stats["total_expenses"]
            total_transactions += account_stats["transaction_count"]
            
            accounts_summary.append({
                "account_id": account_id,
                "account_name": account.get("details", {}).get("name", "Compte inconnu"),
                "stats": account_stats
            })
        
        return {
            "status": "success",
            "data": {
                "period": {
                    "from": date_from.isoformat(),
                    "to": date.today().isoformat(),
                    "days": days_back
                },
                "global_summary": {
                    "total_transactions": total_transactions,
                    "total_income": round(total_income, 2),
                    "total_expenses": round(total_expenses, 2),
                    "net_balance": round(total_income - total_expenses, 2)
                },
                "accounts_summary": accounts_summary,
                "requisition_id": requisition_id
            },
            "message": f"Résumé généré depuis les données stockées ({days_back} derniers jours) - DEPRECATED: utilisez /stored/summary/user/{{user_id}}"
        }
    except Exception as e:
        logger.error(f"Error generating stored summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ENDPOINTS ORIGINAUX (AVEC APPELS API - À UTILISER AVEC PRÉCAUTION)
# ============================================================================


@router.get("/banks/institutions")
async def get_bank_institutions(country_code: str = Query("FR", description="Code pays (FR, DE, GB, etc.)")):
    """
    Récupère la liste des institutions bancaires disponibles dans un pays
    """
    try:
        institutions = await transaction_service.get_bank_institutions(country_code)
        return {
            "status": "success",
            "data": institutions,
            "message": f"Institutions bancaires disponibles pour {country_code}"
        }
    except Exception as e:
        logger.error(f"Error getting institutions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/banks/connect")
async def connect_to_bank(
    institution_id: str,
    redirect_url: str = "https://your-app.com/callback"
):
    """
    Initie une connexion à une banque spécifique
    Retourne un lien d'autorisation que l'utilisateur doit visiter
    """
    try:
        requisition = await transaction_service.initiate_bank_connection(institution_id, redirect_url)
        return {
            "status": "success",
            "data": {
                "requisition_id": requisition.get("id"),
                "authorization_link": requisition.get("link"),
                "status": requisition.get("status")
            },
            "message": "Connexion initiée. Visitez le lien d'autorisation pour connecter votre banque."
        }
    except Exception as e:
        logger.error(f"Error connecting to bank: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/banks/accounts/{requisition_id}")
async def get_user_accounts(requisition_id: str):
    """
    Récupère les comptes bancaires de l'utilisateur après autorisation
    """
    try:
        accounts = await transaction_service.get_user_accounts(requisition_id)
        return {
            "status": "success",
            "data": accounts,
            "message": f"Comptes récupérés avec succès"
        }
    except Exception as e:
        logger.error(f"Error getting accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/banks/transactions/{account_id}")
async def get_account_transactions(
    account_id: str,
    date_from: Optional[date] = Query(None, description="Date de début (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Date de fin (YYYY-MM-DD)")
):
    """
    Récupère les transactions d'un compte bancaire spécifique
    """
    try:
        transactions = await transaction_service.get_transactions_from_bank(account_id, date_from, date_to)
        return {
            "status": "success",
            "data": [transaction.dict() for transaction in transactions],
            "count": len(transactions),
            "message": f"Transactions récupérées pour le compte {account_id}"
        }
    except Exception as e:
        logger.error(f"Error getting transactions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/banks/sync/{requisition_id}")
async def sync_all_transactions(
    requisition_id: str,
    days_back: int = Query(30, description="Nombre de jours en arrière pour synchroniser")
):
    """
    Synchronise toutes les transactions de tous les comptes liés à une réquisition
    """
    try:
        all_transactions = await transaction_service.sync_all_accounts_transactions(requisition_id, days_back)
        
        # Compter le total des transactions
        total_transactions = sum(len(transactions) for transactions in all_transactions.values())
        
        # Convertir en format sérialisable
        serialized_data = {}
        for account_id, transactions in all_transactions.items():
            serialized_data[account_id] = [transaction.dict() for transaction in transactions]
        
        return {
            "status": "success",
            "data": serialized_data,
            "total_transactions": total_transactions,
            "accounts_synced": len(all_transactions),
            "message": f"Synchronisation terminée: {total_transactions} transactions trouvées"
        }
    except Exception as e:
        logger.error(f"Error syncing transactions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/banks/transactions/summary/{requisition_id}")
async def get_transactions_summary(
    requisition_id: str,
    days_back: int = Query(30, description="Nombre de jours en arrière")
):
    """
    Récupère un résumé des transactions (totaux, par type, etc.)
    """
    try:
        all_transactions = await transaction_service.sync_all_accounts_transactions(requisition_id, days_back)
        
        total_income = 0.0
        total_expenses = 0.0
        transaction_count = 0
        
        for account_id, transactions in all_transactions.items():
            for transaction in transactions:
                transaction_count += 1
                amount = float(transaction.transactionAmount.amount)
                if amount >= 0:
                    total_income += amount
                else:
                    total_expenses += abs(amount)
        
        return {
            "status": "success",
            "data": {
                "total_transactions": transaction_count,
                "total_income": total_income,
                "total_expenses": total_expenses,
                "net_balance": total_income - total_expenses,
                "accounts_analyzed": len(all_transactions),
                "period_days": days_back
            },
            "message": "Résumé des transactions généré avec succès"
        }
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE GESTION DES UTILISATEURS
# ============================================================================

@router.post("/accounts/assign-user")
async def assign_account_to_user(
    account_id: str = Query(..., description="ID du compte à assigner"),
    user_id: str = Query(..., description="ID de l'utilisateur")
):
    """
    Associe un compte bancaire à un utilisateur spécifique
    """
    try:
        # Validation de l'user_id
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=400, detail="L'user_id ne peut pas être vide")
        
        # Vérifier que l'utilisateur existe
        user_exists = await bank_repository.validate_user_id(user_id)
        if not user_exists:
            raise HTTPException(
                status_code=404, 
                detail=f"L'utilisateur avec l'ID '{user_id}' n'existe pas dans la base de données"
            )
        
        # Vérifier que le compte existe
        account = await bank_repository.db.accounts.find_one({"account_id": account_id})
        if not account:
            raise HTTPException(status_code=404, detail="Compte non trouvé")
        
        # Mettre à jour le compte avec l'user_id
        result = await bank_repository.db.accounts.update_one(
            {"account_id": account_id},
            {"$set": {"user_id": user_id, "assigned_at": datetime.utcnow()}}
        )
        
        if result.modified_count > 0:
            return {
                "status": "success",
                "data": {
                    "account_id": account_id,
                    "user_id": user_id,
                    "assigned_at": datetime.utcnow().isoformat()
                },
                "message": f"Compte {account_id} assigné à l'utilisateur {user_id}"
            }
        else:
            return {
                "status": "warning",
                "message": "Aucune modification effectuée (compte déjà assigné à cet utilisateur)"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning account to user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accounts/bulk-assign-user")
async def bulk_assign_accounts_to_user(
    requisition_id: str = Query(..., description="ID de la réquisition"),
    user_id: str = Query(..., description="ID de l'utilisateur")
):
    """
    Associe tous les comptes d'une réquisition à un utilisateur spécifique
    """
    try:
        # Validation de l'user_id
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=400, detail="L'user_id ne peut pas être vide")
        
        # Vérifier que l'utilisateur existe
        user_exists = await bank_repository.validate_user_id(user_id)
        if not user_exists:
            raise HTTPException(
                status_code=404, 
                detail=f"L'utilisateur avec l'ID '{user_id}' n'existe pas dans la base de données"
            )
        
        # Récupérer tous les comptes de la réquisition
        accounts_cursor = bank_repository.db.accounts.find({"requisition_id": requisition_id})
        accounts = await accounts_cursor.to_list(length=None)
        
        if not accounts:
            raise HTTPException(status_code=404, detail="Aucun compte trouvé pour cette réquisition")
        
        # Mettre à jour tous les comptes avec l'user_id
        result = await bank_repository.db.accounts.update_many(
            {"requisition_id": requisition_id},
            {"$set": {"user_id": user_id, "assigned_at": datetime.utcnow()}}
        )
        
        return {
            "status": "success",
            "data": {
                "requisition_id": requisition_id,
                "user_id": user_id,
                "accounts_updated": result.modified_count,
                "total_accounts": len(accounts),
                "assigned_at": datetime.utcnow().isoformat()
            },
            "message": f"{result.modified_count} comptes assignés à l'utilisateur {user_id}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk assigning accounts to user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/accounts/status")
async def get_user_accounts_status(user_id: str):
    """
    Récupère le statut des comptes d'un utilisateur
    """
    try:
        # Validation de l'user_id
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=400, detail="L'user_id ne peut pas être vide")
        
        # Vérifier que l'utilisateur existe
        user_exists = await bank_repository.validate_user_id(user_id)
        if not user_exists:
            raise HTTPException(
                status_code=404, 
                detail=f"L'utilisateur avec l'ID '{user_id}' n'existe pas dans la base de données"
            )
        
        # Compter les comptes avec et sans user_id
        total_accounts = await bank_repository.db.accounts.count_documents({"user_id": user_id})
        
        # Récupérer les détails des comptes
        accounts_cursor = bank_repository.db.accounts.find(
            {"user_id": user_id},
            {"account_id": 1, "requisition_id": 1, "details.name": 1, "assigned_at": 1, "last_transaction_sync": 1}
        )
        accounts = await accounts_cursor.to_list(length=None)
        
        # Convertir les ObjectId en strings
        for account in accounts:
            if "_id" in account:
                account["_id"] = str(account["_id"])
        
        return {
            "status": "success",
            "data": {
                "user_id": user_id,
                "total_accounts": total_accounts,
                "accounts": accounts
            },
            "message": f"Statut des comptes pour l'utilisateur {user_id}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user accounts status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/validate")
async def validate_user_id_endpoint(user_id: str):
    """
    Valide qu'un user_id existe dans la base de données
    """
    try:
        # Validation de l'user_id
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=400, detail="L'user_id ne peut pas être vide")
        
        # Vérifier que l'utilisateur existe
        user_exists = await bank_repository.validate_user_id(user_id)
        
        if user_exists:
            return {
                "status": "success",
                "data": {
                    "user_id": user_id,
                    "exists": True,
                    "validated_at": datetime.utcnow().isoformat()
                },
                "message": f"L'utilisateur avec l'ID '{user_id}' existe dans la base de données"
            }
        else:
            raise HTTPException(
                status_code=404, 
                detail=f"L'utilisateur avec l'ID '{user_id}' n'existe pas dans la base de données"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating user_id {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
