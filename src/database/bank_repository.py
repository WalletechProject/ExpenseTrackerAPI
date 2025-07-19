"""
Modèles MongoDB pour le stockage des données bancaires
"""

from pymongo import MongoClient, ASCENDING, DESCENDING
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Optional
import os
import sys

# Ajouter le répertoire parent au chemin pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.transaction import Transaction
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class BankDataRepository:
    """Repository pour gérer les données bancaires dans MongoDB"""
    
    def __init__(self):
        mongodb_url = os.getenv("ADMIN_MONGODB_URL", "mongodb://localhost:27017")
        self.mongo_url = mongodb_url
        self.db_name = "tafaro_db"
        self.client = None
        self.db = None
        self._ensure_connection()
    
    def _ensure_connection(self):
        """Assure une connexion à MongoDB"""
        if not self.client:
            try:
                self.client = AsyncIOMotorClient(
                    self.mongo_url,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=5000
                )
                self.db = self.client[self.db_name]
            except Exception as e:
                logger.error(f"❌ Erreur de connexion MongoDB: {e}")
                raise
    
    async def create_indexes(self):
        """Crée les index pour optimiser les performances"""
        try:
            # Index pour les transactions
            await self.db.transactions.create_index([
                ("entryReference", ASCENDING)
            ], unique=True)  # Éviter les doublons
            
            await self.db.transactions.create_index([
                ("bookingDate", DESCENDING),
                ("account_id", ASCENDING)
            ])
            
            await self.db.transactions.create_index([
                ("account_id", ASCENDING),
                ("bookingDate", DESCENDING)
            ])
            
            # Index pour les comptes
            await self.db.accounts.create_index([
                ("account_id", ASCENDING)
            ], unique=True)
            
            await self.db.accounts.create_index([
                ("user_id", ASCENDING)
            ])
            
            await self.db.accounts.create_index([
                ("requisition_id", ASCENDING)
            ])
            
            # Index pour les réquisitions
            await self.db.requisitions.create_index([
                ("requisition_id", ASCENDING)
            ], unique=True)
            
            # Index pour les appels API (monitoring)
            await self.db.api_calls.create_index([
                ("timestamp", DESCENDING)
            ])
            
            logger.info("✅ Index MongoDB créés avec succès")
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la création des index: {e}")
    
    async def save_requisition(self, requisition_data: Dict[str, Any]) -> bool:
        """Sauvegarde les informations de réquisition"""
        try:
            requisition_doc = {
                "requisition_id": requisition_data.get("requisition_id"),
                "institution_id": requisition_data.get("institution_id"),
                "status": requisition_data.get("status", "created"),
                "authorization_link": requisition_data.get("authorization_link"),
                "created_at": datetime.utcnow(),
                "last_sync": None,
                "total_accounts": 0,
                "total_transactions": 0
            }
            
            await self.db.requisitions.update_one(
                {"requisition_id": requisition_doc["requisition_id"]},
                {"$set": requisition_doc},
                upsert=True
            )
            
            logger.info(f"✅ Réquisition {requisition_doc['requisition_id']} sauvegardée")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde réquisition: {e}")
            return False
    
    async def save_accounts(self, requisition_id: str, accounts_data: List[Dict[str, Any]], user_id: Optional[str] = None) -> bool:
        """Sauvegarde les comptes bancaires avec support optionnel de user_id"""
        try:
            for account in accounts_data:
                account_doc = {
                    "account_id": account.get("account_id"),
                    "requisition_id": requisition_id,
                    "details": account.get("details", {}),
                    "balances": account.get("balances", {}),
                    "last_balance_update": datetime.utcnow(),
                    "last_transaction_sync": None,
                    "transaction_count": 0
                }
                
                # Ajouter user_id si fourni
                if user_id:
                    account_doc["user_id"] = user_id
                    account_doc["assigned_at"] = datetime.utcnow()
                
                await self.db.accounts.update_one(
                    {"account_id": account_doc["account_id"]},
                    {"$set": account_doc},
                    upsert=True
                )
            
            # Mettre à jour le nombre de comptes dans la réquisition
            await self.db.requisitions.update_one(
                {"requisition_id": requisition_id},
                {"$set": {"total_accounts": len(accounts_data)}}
            )
            
            user_info = f" pour l'utilisateur {user_id}" if user_id else ""
            logger.info(f"✅ {len(accounts_data)} comptes sauvegardés pour {requisition_id}{user_info}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde comptes: {e}")
            return False
    
    async def save_transactions(self, account_id: str, transactions: List[Transaction]) -> Dict[str, int]:
        """Sauvegarde les transactions en évitant les doublons"""
        try:
            new_count = 0
            updated_count = 0
            
            for transaction in transactions:
                # Convert date objects to datetime objects for MongoDB compatibility
                booking_date = transaction.bookingDate
                if isinstance(booking_date, date) and not isinstance(booking_date, datetime):
                    booking_date = datetime.combine(booking_date, datetime.min.time())
                
                value_date = transaction.valueDate
                if isinstance(value_date, date) and not isinstance(value_date, datetime):
                    value_date = datetime.combine(value_date, datetime.min.time())
                
                transaction_doc = {
                    "entryReference": transaction.entryReference,
                    "account_id": account_id,
                    "bookingDate": booking_date,
                    "valueDate": value_date,
                    "transactionAmount": {
                        "amount": transaction.transactionAmount.amount,
                        "currency": transaction.transactionAmount.currency
                    },
                    "remittanceInformationUnstructuredArray": transaction.remittanceInformationUnstructuredArray,
                    "internalTransactionId": transaction.internalTransactionId,
                    "transaction_type": transaction.transaction_type.value if transaction.transaction_type else None,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
                
                # Utiliser upsert pour éviter les doublons
                result = await self.db.transactions.update_one(
                    {"entryReference": transaction.entryReference},
                    {"$set": transaction_doc},
                    upsert=True
                )
                
                if result.upserted_id:
                    new_count += 1
                elif result.modified_count > 0:
                    updated_count += 1
            
            # Mettre à jour les stats du compte
            await self.db.accounts.update_one(
                {"account_id": account_id},
                {
                    "$set": {"last_transaction_sync": datetime.utcnow()},
                    "$inc": {"transaction_count": new_count}
                }
            )
            
            logger.info(f"✅ Transactions sauvegardées pour {account_id}: {new_count} nouvelles, {updated_count} mises à jour")
            
            return {
                "new_transactions": new_count,
                "updated_transactions": updated_count,
                "total_processed": len(transactions)
            }
            
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde transactions: {e}")
            return {"new_transactions": 0, "updated_transactions": 0, "total_processed": 0}
    
    async def log_api_call(self, endpoint: str, account_id: str = None, success: bool = True, error_message: str = None):
        """Log les appels API pour monitoring"""
        try:
            api_call_doc = {
                "endpoint": endpoint,
                "account_id": account_id,
                "success": success,
                "error_message": error_message,
                "timestamp": datetime.utcnow()
            }
            
            await self.db.api_calls.insert_one(api_call_doc)
            
        except Exception as e:
            logger.error(f"❌ Erreur log API call: {e}")
    
    async def get_api_calls_this_month(self) -> int:
        """Retourne le nombre d'appels API ce mois-ci"""
        try:
            # Premier jour du mois actuel
            first_day_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            count = await self.db.api_calls.count_documents({
                "timestamp": {"$gte": first_day_month}
            })
            
            return count
            
        except Exception as e:
            logger.error(f"❌ Erreur comptage API calls: {e}")
            return 0
    
    async def get_last_sync_date(self, account_id: str) -> Optional[date]:
        """Retourne la date de dernière synchronisation d'un compte"""
        try:
            account = await self.db.accounts.find_one({"account_id": account_id})
            if account and account.get("last_transaction_sync"):
                return account["last_transaction_sync"].date()
            return None
            
        except Exception as e:
            logger.error(f"❌ Erreur récupération dernière sync: {e}")
            return None
    
    async def get_transactions_count(self, account_id: str) -> int:
        """Retourne le nombre de transactions stockées pour un compte"""
        try:
            count = await self.db.transactions.count_documents({"account_id": account_id})
            return count
            
        except Exception as e:
            logger.error(f"❌ Erreur comptage transactions: {e}")
            return 0
    
    async def get_stored_transactions(self, account_id: str, date_from: date = None, date_to: date = None, limit: int = None) -> List[Dict[str, Any]]:
        """Récupère les transactions stockées pour un compte"""
        try:
            query = {"account_id": account_id}
            
            if date_from or date_to:
                date_filter = {}
                if date_from:
                    date_filter["$gte"] = date_from
                if date_to:
                    date_filter["$lte"] = date_to
                query["bookingDate"] = date_filter
            
            cursor = self.db.transactions.find(query).sort("bookingDate", DESCENDING)
            
            if limit:
                cursor = cursor.limit(limit)
            
            transactions = await cursor.to_list(length=None)
            return transactions
            
        except Exception as e:
            logger.error(f"❌ Erreur récupération transactions stockées: {e}")
            return []
    
    async def get_account_summary(self, account_id: str) -> Dict[str, Any]:
        """Retourne un résumé d'un compte"""
        try:
            account = await self.db.accounts.find_one({"account_id": account_id})
            if not account:
                return {}
            
            # Statistiques des transactions
            pipeline = [
                {"$match": {"account_id": account_id}},
                {"$group": {
                    "_id": None,
                    "total_transactions": {"$sum": 1},
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
                    },
                    "oldest_transaction": {"$min": "$bookingDate"},
                    "newest_transaction": {"$max": "$bookingDate"}
                }}
            ]
            
            result = await self.db.transactions.aggregate(pipeline).to_list(length=1)
            stats = result[0] if result else {}
            
            return {
                "account_id": account_id,
                "account_details": account.get("details", {}),
                "last_sync": account.get("last_transaction_sync"),
                "transaction_stats": stats
            }
            
        except Exception as e:
            logger.error(f"❌ Erreur résumé compte: {e}")
            return {}
    
    async def cleanup_old_api_calls(self, days_to_keep: int = 90):
        """Nettoie les anciens logs d'appels API"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
            result = await self.db.api_calls.delete_many({
                "timestamp": {"$lt": cutoff_date}
            })
            
            logger.info(f"✅ {result.deleted_count} anciens logs API supprimés")
            
        except Exception as e:
            logger.error(f"❌ Erreur nettoyage logs API: {e}")
    
    async def get_stored_transactions_by_user(self, user_id: str, date_from: Optional[date] = None, date_to: Optional[date] = None, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
        """Récupère les transactions stockées pour un utilisateur"""
        try:
            # D'abord, récupérer tous les comptes de l'utilisateur
            accounts_cursor = self.db.accounts.find({"user_id": user_id})
            accounts = await accounts_cursor.to_list(length=None)
            
            if not accounts:
                return []
            
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
            transactions_cursor = self.db.transactions.find(query).sort("bookingDate", -1)
            if limit:
                transactions_cursor = transactions_cursor.limit(limit)
            
            transactions = await transactions_cursor.to_list(length=None)
            
            # Convertir les ObjectId en strings
            for transaction in transactions:
                if "_id" in transaction:
                    transaction["_id"] = str(transaction["_id"])
            
            return transactions
            
        except Exception as e:
            logger.error(f"❌ Erreur récupération transactions utilisateur: {e}")
            return []
    async def validate_user_id(self, user_id: str) -> bool:
        """Valide qu'un user_id existe dans la base de données"""
        try:
            # Vérifier que l'user_id n'est pas vide ou None
            if not user_id or not user_id.strip():
                return False
            
            # Essayer d'abord avec ObjectId si le format est valide
            user_exists = False
            if ObjectId.is_valid(user_id):
                user_exists = await self.db.Users.find_one({"_id": ObjectId(user_id)}) is not None
            
            if not user_exists:
                # Si pas trouvé par ObjectId, essayer par un autre champ (username, email, etc.)
                user_exists = await self.db.Users.find_one({
                    "$or": [
                        {"username": user_id},
                        {"email": user_id},
                        {"user_id": user_id}
                    ]
                }) is not None
            
            return user_exists
            
        except Exception as e:
            logger.error(f"❌ Erreur validation user_id: {e}")
            return False
            return False


# Instance globale du repository
bank_repository = BankDataRepository()
