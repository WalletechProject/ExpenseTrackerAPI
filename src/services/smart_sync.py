"""
Service de synchronisation intelligent pour optimiser les appels API GoCardless
Stratégie : 50 appels max/mois = ~1.6 appel/jour en moyenne
"""

import asyncio
import sys
import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple

# Ajouter le répertoire parent au chemin pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.transactions import TransactionService
from database.bank_repository import bank_repository
from models.transaction import Transaction
import logging

logger = logging.getLogger(__name__)


class SmartSyncService:
    """Service de synchronisation intelligent pour minimiser les appels API"""
    
    def __init__(self):
        self.transaction_service = TransactionService()
        self.max_api_calls_per_month = 50
        self.recommended_sync_interval_days = 3  # Tous les 3 jours pour capturer toutes les transactions
        
    async def get_remaining_api_calls(self) -> int:
        """Retourne le nombre d'appels API restants ce mois-ci"""
        used_calls = await bank_repository.get_api_calls_this_month()
        remaining = self.max_api_calls_per_month - used_calls
        return max(0, remaining)
    
    async def should_sync_account(self, account_id: str) -> Tuple[bool, str]:
        """Détermine si un compte doit être synchronisé et pourquoi"""
        
        # Vérifier les appels API restants
        remaining_calls = await self.get_remaining_api_calls()
        if remaining_calls <= 0:
            return False, "Quota API épuisé pour ce mois"
        
        # Récupérer la dernière date de sync
        last_sync = await bank_repository.get_last_sync_date(account_id)
        
        if not last_sync:
            return True, "Première synchronisation - récupération de l'historique complet"
        
        # Calculer les jours depuis la dernière sync
        days_since_sync = (date.today() - last_sync).days
        
        if days_since_sync >= self.recommended_sync_interval_days:
            return True, f"Dernière sync il y a {days_since_sync} jours (recommandé: {self.recommended_sync_interval_days} jours)"
        
        # Si weekend ou jour férié, on peut être plus flexible
        today = date.today()
        if today.weekday() >= 5:  # Weekend
            if days_since_sync >= 2:
                return True, f"Sync weekend - {days_since_sync} jours depuis dernière sync"
        
        return False, f"Sync récente ({days_since_sync} jours) - pas nécessaire"
    
    async def initial_full_sync(self, requisition_id: str) -> Dict[str, Any]:
        """
        Synchronisation initiale complète - récupère 90 jours d'historique
        Stratégie: Utilise 1 appel par compte pour récupérer le maximum de données
        """
        
        logger.info(f"🚀 Début de la synchronisation initiale complète pour {requisition_id}")
        
        try:
            # Vérifier les appels API disponibles
            remaining_calls = await self.get_remaining_api_calls()
            logger.info(f"📊 Appels API restants ce mois: {remaining_calls}")
            
            if remaining_calls < 2:  # Au minimum 1 pour les comptes + 1 pour les transactions
                raise Exception("Pas assez d'appels API restants pour une synchronisation complète")
            
            # 1. Récupérer les comptes (1 appel API)
            await bank_repository.log_api_call("get_accounts", requisition_id, True)
            accounts = await self.transaction_service.get_user_accounts(requisition_id)
            
            if not accounts:
                raise Exception("Aucun compte trouvé pour cette réquisition")
            
            # Sauvegarder les comptes
            await bank_repository.save_accounts(requisition_id, accounts)
            
            # 2. Pour chaque compte, récupérer 90 jours de transactions (max GoCardless)
            date_from = date.today() - timedelta(days=90)
            date_to = date.today()
            
            sync_results = {}
            total_new_transactions = 0
            
            for account in accounts:
                account_id = account.get("account_id")
                
                if remaining_calls <= 0:
                    logger.warning(f"⚠️ Quota API épuisé - arrêt de la sync pour {account_id}")
                    break
                
                try:
                    logger.info(f"📥 Récupération des transactions pour {account_id} (90 jours)")
                    
                    # Récupérer les transactions (1 appel API par compte)
                    transactions = await self.transaction_service.get_transactions_from_bank(
                        account_id, date_from, date_to
                    )
                    
                    await bank_repository.log_api_call("get_transactions", account_id, True)
                    remaining_calls -= 1
                    
                    # Sauvegarder en base
                    save_result = await bank_repository.save_transactions(account_id, transactions)
                    
                    sync_results[account_id] = {
                        "total_transactions": len(transactions),
                        "new_transactions": save_result["new_transactions"],
                        "updated_transactions": save_result["updated_transactions"],
                        "date_range": f"{date_from} to {date_to}"
                    }
                    
                    total_new_transactions += save_result["new_transactions"]
                    
                    logger.info(f"✅ {account_id}: {len(transactions)} transactions récupérées, {save_result['new_transactions']} nouvelles")
                    
                except Exception as e:
                    logger.error(f"❌ Erreur sync {account_id}: {e}")
                    await bank_repository.log_api_call("get_transactions", account_id, False, str(e))
                    sync_results[account_id] = {"error": str(e)}
            
            # Mettre à jour les stats de la réquisition
            await bank_repository.db.requisitions.update_one(
                {"requisition_id": requisition_id},
                {
                    "$set": {
                        "last_sync": datetime.utcnow(),
                        "total_transactions": total_new_transactions,
                        "status": "synced"
                    }
                }
            )
            
            result = {
                "sync_type": "initial_full",
                "requisition_id": requisition_id,
                "accounts_synced": len([r for r in sync_results.values() if "error" not in r]),
                "total_accounts": len(accounts),
                "total_new_transactions": total_new_transactions,
                "api_calls_used": len(accounts) + 1,  # +1 pour get_accounts
                "remaining_api_calls": remaining_calls,
                "sync_results": sync_results,
                "date_range": f"{date_from} to {date_to}"
            }
            
            logger.info(f"🎉 Synchronisation initiale terminée: {total_new_transactions} nouvelles transactions")
            return result
            
        except Exception as e:
            logger.error(f"❌ Erreur synchronisation initiale: {e}")
            await bank_repository.log_api_call("initial_sync", requisition_id, False, str(e))
            raise
    
    async def incremental_sync(self, requisition_id: str) -> Dict[str, Any]:
        """
        Synchronisation incrémentale - récupère seulement les nouvelles transactions
        Stratégie: Optimise en récupérant seulement depuis la dernière sync
        """
        
        logger.info(f"🔄 Début de la synchronisation incrémentale pour {requisition_id}")
        
        try:
            remaining_calls = await self.get_remaining_api_calls()
            logger.info(f"📊 Appels API restants: {remaining_calls}")
            
            # Récupérer les comptes de la base (pas d'appel API)
            accounts_cursor = bank_repository.db.accounts.find({"requisition_id": requisition_id})
            accounts = await accounts_cursor.to_list(length=None)
            
            if not accounts:
                logger.info("ℹ️ Aucun compte en base - lancement d'une sync complète")
                return await self.initial_full_sync(requisition_id)
            
            sync_results = {}
            total_new_transactions = 0
            api_calls_used = 0
            
            for account in accounts:
                account_id = account.get("account_id")
                
                # Vérifier si la sync est nécessaire
                should_sync, reason = await self.should_sync_account(account_id)
                
                if not should_sync:
                    logger.info(f"⏭️ Skip {account_id}: {reason}")
                    sync_results[account_id] = {"skipped": True, "reason": reason}
                    continue
                
                if remaining_calls <= 0:
                    logger.warning(f"⚠️ Quota API épuisé - arrêt de la sync")
                    break
                
                try:
                    # Déterminer la plage de dates pour la sync incrémentale
                    last_sync = await bank_repository.get_last_sync_date(account_id)
                    
                    if last_sync:
                        # Récupérer depuis la dernière sync avec 1 jour de chevauchement
                        date_from = last_sync - timedelta(days=1)
                    else:
                        # Si pas de sync précédente, récupérer 30 jours
                        date_from = date.today() - timedelta(days=30)
                    
                    date_to = date.today()
                    
                    logger.info(f"📥 Sync incrémentale {account_id}: {date_from} à {date_to} ({reason})")
                    
                    # Récupérer les transactions
                    transactions = await self.transaction_service.get_transactions_from_bank(
                        account_id, date_from, date_to
                    )
                    
                    await bank_repository.log_api_call("get_transactions_incremental", account_id, True)
                    remaining_calls -= 1
                    api_calls_used += 1
                    
                    # Sauvegarder en base
                    save_result = await bank_repository.save_transactions(account_id, transactions)
                    
                    sync_results[account_id] = {
                        "total_transactions": len(transactions),
                        "new_transactions": save_result["new_transactions"],
                        "updated_transactions": save_result["updated_transactions"],
                        "date_range": f"{date_from} to {date_to}",
                        "reason": reason
                    }
                    
                    total_new_transactions += save_result["new_transactions"]
                    
                    logger.info(f"✅ {account_id}: {save_result['new_transactions']} nouvelles transactions")
                    
                except Exception as e:
                    logger.error(f"❌ Erreur sync incrémentale {account_id}: {e}")
                    await bank_repository.log_api_call("get_transactions_incremental", account_id, False, str(e))
                    sync_results[account_id] = {"error": str(e)}
            
            # Mettre à jour la réquisition
            await bank_repository.db.requisitions.update_one(
                {"requisition_id": requisition_id},
                {
                    "$set": {"last_sync": datetime.utcnow()},
                    "$inc": {"total_transactions": total_new_transactions}
                }
            )
            
            result = {
                "sync_type": "incremental",
                "requisition_id": requisition_id,
                "accounts_processed": len(sync_results),
                "accounts_synced": len([r for r in sync_results.values() if "error" not in r and "skipped" not in r]),
                "accounts_skipped": len([r for r in sync_results.values() if "skipped" in r]),
                "total_new_transactions": total_new_transactions,
                "api_calls_used": api_calls_used,
                "remaining_api_calls": remaining_calls,
                "sync_results": sync_results
            }
            
            logger.info(f"🎉 Synchronisation incrémentale terminée: {total_new_transactions} nouvelles transactions, {api_calls_used} appels API")
            return result
            
        except Exception as e:
            logger.error(f"❌ Erreur synchronisation incrémentale: {e}")
            raise
    
    async def smart_sync(self, requisition_id: str) -> Dict[str, Any]:
        """
        Synchronisation intelligente - choisit automatiquement le type de sync
        """
        
        # Vérifier si c'est la première sync
        requisition = await bank_repository.db.requisitions.find_one({"requisition_id": requisition_id})
        
        if not requisition or not requisition.get("last_sync"):
            logger.info("🚀 Première synchronisation détectée - lancement sync complète")
            return await self.initial_full_sync(requisition_id)
        else:
            logger.info("🔄 Synchronisation suivante - lancement sync incrémentale")
            return await self.incremental_sync(requisition_id)
    
    async def get_sync_recommendations(self, requisition_id: str) -> Dict[str, Any]:
        """Fournit des recommandations pour la synchronisation"""
        
        try:
            remaining_calls = await self.get_remaining_api_calls()
            
            # Récupérer les comptes
            accounts_cursor = bank_repository.db.accounts.find({"requisition_id": requisition_id})
            accounts = await accounts_cursor.to_list(length=None)
            
            recommendations = {
                "remaining_api_calls": remaining_calls,
                "total_accounts": len(accounts),
                "can_full_sync": remaining_calls >= len(accounts) + 1,
                "recommended_action": "",
                "accounts_analysis": []
            }
            
            for account in accounts:
                account_id = account.get("account_id")
                should_sync, reason = await self.should_sync_account(account_id)
                last_sync = await bank_repository.get_last_sync_date(account_id)
                transaction_count = await bank_repository.get_transactions_count(account_id)
                
                recommendations["accounts_analysis"].append({
                    "account_id": account_id,
                    "should_sync": should_sync,
                    "reason": reason,
                    "last_sync": last_sync.isoformat() if last_sync else None,
                    "stored_transactions": transaction_count
                })
            
            # Recommandation globale
            if remaining_calls <= 0:
                recommendations["recommended_action"] = "Attendre le prochain mois - quota épuisé"
            elif not accounts:
                recommendations["recommended_action"] = "Lancer une synchronisation complète initiale"
            elif any(acc["should_sync"] for acc in recommendations["accounts_analysis"]):
                recommendations["recommended_action"] = "Lancer une synchronisation incrémentale"
            else:
                recommendations["recommended_action"] = "Pas de synchronisation nécessaire pour le moment"
            
            return recommendations
            
        except Exception as e:
            logger.error(f"❌ Erreur recommandations sync: {e}")
            return {"error": str(e)}


# Instance globale du service
smart_sync_service = SmartSyncService()
