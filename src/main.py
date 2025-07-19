from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from database.init_db import run_before_start
from routes import auth, user, transactions
from services.smart_sync import smart_sync_service
from database.bank_repository import bank_repository
import logging
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="ExpenseTracker avec GoCardless",
    description="Application de suivi des dépenses avec synchronisation automatique des données bancaires",
    version="1.0.0"
)

# Planificateur pour les tâches automatiques
scheduler = AsyncIOScheduler()

async def auto_sync_task():
    """Tâche de synchronisation automatique"""
    try:
        requisition_id = os.getenv("REQUISITION_ID")
        if not requisition_id:
            logger.warning("⚠️ REQUISITION_ID non configuré - synchronisation automatique désactivée")
            return
        
        logger.info("🔄 Début de la synchronisation automatique...")
        
        # Vérifier si on a encore des appels API disponibles
        remaining_calls = await smart_sync_service.get_remaining_api_calls()
        if remaining_calls <= 0:
            logger.warning("⚠️ Quota API épuisé - synchronisation reportée")
            return
        
        # Lancer la synchronisation intelligente
        result = await smart_sync_service.smart_sync(requisition_id)
        
        logger.info(f"✅ Synchronisation automatique terminée:")
        logger.info(f"   - Type: {result['sync_type']}")
        logger.info(f"   - Nouvelles transactions: {result.get('total_new_transactions', 0)}")
        logger.info(f"   - Appels API utilisés: {result.get('api_calls_used', 0)}")
        logger.info(f"   - Appels API restants: {result.get('remaining_api_calls', 0)}")
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la synchronisation automatique: {e}")

async def check_and_sync_on_startup(requisition_id: str):
    """
    Vérifie au démarrage si une synchronisation est nécessaire
    Lance automatiquement une sync si la dernière date de plus de 4 jours
    """
    try:
        logger.info("🔍 Vérification de la nécessité de synchronisation au démarrage...")
        
        # Vérifier les appels API disponibles
        remaining_calls = await smart_sync_service.get_remaining_api_calls()
        logger.info(f"📊 Appels API restants: {remaining_calls}/50")
        
        if remaining_calls <= 0:
            logger.warning("⚠️ Quota API épuisé - pas de synchronisation au démarrage")
            return
        
        # Récupérer les comptes stockés
        accounts_cursor = bank_repository.db.accounts.find({"requisition_id": requisition_id})
        accounts = await accounts_cursor.to_list(length=None)
        
        if not accounts:
            logger.info("📋 Aucun compte en base - synchronisation initiale recommandée")
            logger.info("💡 Utilisez: curl -X POST 'http://127.0.0.1:8000/api/sync/initial/{}'".format(requisition_id))
            return
        
        # Vérifier chaque compte pour voir si sync nécessaire
        sync_needed = False
        oldest_sync = None
        
        for account in accounts:
            account_id = account.get("account_id")
            last_sync = await bank_repository.get_last_sync_date(account_id)
            
            if not last_sync:
                logger.info(f"📝 {account_id[:12]}... n'a jamais été synchronisé")
                sync_needed = True
                break
            
            days_since_sync = (datetime.now().date() - last_sync).days
            logger.info(f"📅 {account_id[:12]}... - dernière sync il y a {days_since_sync} jours")
            
            if days_since_sync >= 4:
                sync_needed = True
                if not oldest_sync or days_since_sync > oldest_sync:
                    oldest_sync = days_since_sync
        
        if sync_needed:
            if oldest_sync:
                logger.info(f"🚨 Synchronisation nécessaire! Plus ancienne sync: {oldest_sync} jours")
            
            logger.info("🔄 Lancement de la synchronisation au démarrage...")
            
            # Lancer la synchronisation intelligente
            result = await smart_sync_service.smart_sync(requisition_id)
            
            logger.info(f"✅ Synchronisation au démarrage terminée!")
            logger.info(f"   - Type: {result['sync_type']}")
            logger.info(f"   - Comptes synchronisés: {result.get('accounts_synced', 0)}")
            logger.info(f"   - Nouvelles transactions: {result.get('total_new_transactions', 0)}")
            logger.info(f"   - Appels API utilisés: {result.get('api_calls_used', 0)}")
            
            # Afficher un résumé des comptes
            if result.get('sync_results'):
                for account_id, account_result in result['sync_results'].items():
                    if 'error' in account_result:
                        logger.warning(f"   ❌ {account_id[:12]}...: {account_result['error']}")
                    elif 'skipped' in account_result:
                        logger.info(f"   ⏭️ {account_id[:12]}...: {account_result['reason']}")
                    else:
                        new_tx = account_result.get('new_transactions', 0)
                        if new_tx > 0:
                            logger.info(f"   ✅ {account_id[:12]}...: {new_tx} nouvelles transactions")
                        else:
                            logger.info(f"   ℹ️ {account_id[:12]}...: aucune nouvelle transaction")
        else:
            logger.info("✅ Toutes les synchronisations sont à jour (< 4 jours)")
            logger.info("⏭️ Pas de synchronisation nécessaire au démarrage")
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification au démarrage: {e}")
        logger.info("💡 La synchronisation peut être lancée manuellement via /sync/manual")

@app.on_event("startup")
async def startup_event():
    """Événements au démarrage de l'application"""
    try:
        logger.info("🚀 Démarrage d'ExpenseTracker...")
        
        # Initialiser la base de données
        await bank_repository.create_indexes()
        logger.info("✅ Base de données initialisée")
        
        # Vérifier la configuration GoCardless
        secret_id = os.getenv("GOCARDLESS_SECRET_ID")
        secret_key = os.getenv("GOCARDLESS_SECRET_KEY")
        requisition_id = os.getenv("REQUISITION_ID")
        
        if not secret_id or not secret_key:
            logger.warning("⚠️ Clés GoCardless non configurées - certaines fonctionnalités seront désactivées")
        else:
            logger.info("✅ Configuration GoCardless détectée")
        
        if not requisition_id:
            logger.warning("⚠️ REQUISITION_ID non configuré - synchronisation automatique désactivée")
            logger.info("💡 Pour activer la sync auto: connectez votre banque et ajoutez REQUISITION_ID dans .env")
        else:
            logger.info(f"✅ Configuration trouvée pour {requisition_id[:12]}...")
            
            # NOUVEAU: Vérification au démarrage si sync nécessaire
            await check_and_sync_on_startup(requisition_id)
            
            # Programmer la synchronisation automatique tous les 3 jours à 6h du matin
            scheduler.add_job(
                auto_sync_task,
                CronTrigger(hour=6, minute=0, day="*/3"),  # Tous les 3 jours à 6h
                id="auto_sync",
                replace_existing=True,
                max_instances=1
            )
            
            # Optionnel: synchronisation quotidienne de vérification (plus légère)
            scheduler.add_job(
                auto_sync_task,
                CronTrigger(hour=8, minute=30),  # Tous les jours à 8h30
                id="daily_check",
                replace_existing=True,
                max_instances=1
            )
            
            scheduler.start()
            logger.info("✅ Planificateur de synchronisation démarré")
            logger.info("📅 Synchronisation programmée: tous les 3 jours à 6h + vérification quotidienne à 8h30")
        
        # Afficher l'utilisation API actuelle
        try:
            used_calls = await bank_repository.get_api_calls_this_month()
            logger.info(f"📊 Utilisation API ce mois: {used_calls}/50 appels")
        except:
            logger.info("📊 Utilisation API: non disponible (première utilisation)")
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du démarrage: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Événements à l'arrêt de l'application"""
    logger.info("🛑 Arrêt d'ExpenseTracker...")
    if scheduler.running:
        scheduler.shutdown()
        logger.info("✅ Planificateur arrêté")

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
app.include_router(user.router, prefix="/api", tags=["user"])
app.include_router(transactions.router, prefix="/api", tags=["transactions"])

# Example route
@app.get("/")
async def root():
    """Page d'accueil avec informations sur l'application"""
    try:
        # Informations sur la synchronisation
        requisition_id = os.getenv("REQUISITION_ID")
        sync_status = "configurée" if requisition_id else "non configurée"
        
        # Utilisation API
        used_calls = await bank_repository.get_api_calls_this_month()
        
        return {
            "message": "ExpenseTracker avec GoCardless - API Ready!",
            "version": "1.0.0",
            "synchronisation_automatique": sync_status,
            "api_usage": f"{used_calls}/50 appels ce mois",
            "endpoints": {
                "documentation": "/docs",
                "api_usage": "/api/api-usage",
                "sync_recommendations": "/api/sync/recommendations/{requisition_id}",
                "smart_sync": "/api/sync/smart/{requisition_id}",
                "stored_summary": "/api/stored/summary/{requisition_id}"
            },
            "status": "running"
        }
    except Exception as e:
        return {
            "message": "ExpenseTracker - API Ready!",
            "status": "running",
            "note": "Base de données non encore initialisée"
        }

@app.get("/sync/status")
async def sync_status():
    """Statut de la synchronisation automatique"""
    try:
        requisition_id = os.getenv("REQUISITION_ID")
        if not requisition_id:
            return {
                "sync_enabled": False,
                "message": "Synchronisation automatique désactivée - REQUISITION_ID non configuré"
            }
        
        # Récupérer les informations de synchronisation
        recommendations = await smart_sync_service.get_sync_recommendations(requisition_id)
        used_calls = await bank_repository.get_api_calls_this_month()
        
        # Informations sur les tâches programmées
        jobs_info = []
        if scheduler.running:
            for job in scheduler.get_jobs():
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "Non programmé"
                jobs_info.append({
                    "id": job.id,
                    "next_run": next_run
                })
        
        return {
            "sync_enabled": True,
            "requisition_id": requisition_id[:12] + "..." if len(requisition_id) > 12 else requisition_id,
            "api_usage": {
                "used": used_calls,
                "remaining": 50 - used_calls,
                "limit": 50
            },
            "recommendations": recommendations.get("recommended_action", "Non disponible"),
            "scheduled_jobs": jobs_info,
            "scheduler_running": scheduler.running
        }
    except Exception as e:
        return {
            "sync_enabled": False,
            "error": str(e)
        }

@app.post("/sync/manual")
async def manual_sync():
    """Déclencher manuellement une synchronisation"""
    try:
        requisition_id = os.getenv("REQUISITION_ID")
        if not requisition_id:
            raise HTTPException(status_code=400, detail="REQUISITION_ID non configuré")
        
        logger.info("🔄 Synchronisation manuelle déclenchée...")
        await auto_sync_task()
        
        return {
            "status": "success",
            "message": "Synchronisation manuelle terminée",
            "requisition_id": requisition_id[:12] + "..."
        }
    except Exception as e:
        logger.error(f"❌ Erreur synchronisation manuelle: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sync/check-startup")
async def check_startup_sync():
    """Vérifier si une synchronisation au démarrage serait nécessaire (sans l'exécuter)"""
    try:
        requisition_id = os.getenv("REQUISITION_ID")
        if not requisition_id:
            return {
                "sync_needed": False,
                "reason": "REQUISITION_ID non configuré"
            }
        
        # Vérifier les appels API disponibles
        remaining_calls = await smart_sync_service.get_remaining_api_calls()
        
        if remaining_calls <= 0:
            return {
                "sync_needed": False,
                "reason": "Quota API épuisé",
                "api_calls_remaining": 0
            }
        
        # Récupérer les comptes
        accounts_cursor = bank_repository.db.accounts.find({"requisition_id": requisition_id})
        accounts = await accounts_cursor.to_list(length=None)
        
        if not accounts:
            return {
                "sync_needed": True,
                "reason": "Aucun compte en base - synchronisation initiale nécessaire",
                "api_calls_remaining": remaining_calls
            }
        
        # Analyser chaque compte
        accounts_analysis = []
        sync_needed = False
        
        for account in accounts:
            account_id = account.get("account_id")
            last_sync = await bank_repository.get_last_sync_date(account_id)
            
            if not last_sync:
                accounts_analysis.append({
                    "account_id": account_id[:12] + "...",
                    "last_sync": None,
                    "days_since_sync": None,
                    "needs_sync": True,
                    "reason": "Jamais synchronisé"
                })
                sync_needed = True
            else:
                days_since_sync = (datetime.now().date() - last_sync).days
                needs_sync = days_since_sync >= 4
                
                accounts_analysis.append({
                    "account_id": account_id[:12] + "...",
                    "last_sync": last_sync.isoformat(),
                    "days_since_sync": days_since_sync,
                    "needs_sync": needs_sync,
                    "reason": f"Dernière sync il y a {days_since_sync} jours" + (" (>= 4 jours)" if needs_sync else " (< 4 jours)")
                })
                
                if needs_sync:
                    sync_needed = True
        
        return {
            "sync_needed": sync_needed,
            "reason": "Au moins un compte nécessite une synchronisation" if sync_needed else "Toutes les synchronisations sont récentes",
            "api_calls_remaining": remaining_calls,
            "accounts_analysis": accounts_analysis,
            "total_accounts": len(accounts)
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur vérification startup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    run_before_start()  
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info", reload=True)
