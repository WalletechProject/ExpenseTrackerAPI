import httpx
import os
import asyncio
import sys
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from fastapi import HTTPException

# Ajouter le répertoire parent au chemin pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.transaction import Transaction, TransactionAmount
import logging
from dotenv import load_dotenv

load_dotenv()

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GoCardlessService:
    """Service pour intégrer l'API GoCardless et récupérer les données bancaires"""
    
    def __init__(self):
        self.base_url = "https://bankaccountdata.gocardless.com/api/v2"
        self.secret_id = os.getenv("SECRET_ID")
        self.secret_key = os.getenv("SECRET_KEY")
        
        if not self.secret_id or not self.secret_key:
            logger.warning("GoCardless credentials not found in environment variables")
            raise ValueError("GoCardless credentials (GOCARDLESS_SECRET_ID, GOCARDLESS_SECRET_KEY) must be set in environment variables")
    
    async def get_access_token(self) -> str:
        """Obtient un token d'accès à partir des credentials GoCardless"""
        url = f"{self.base_url}/token/new/"
        
        data = {
            "secret_id": self.secret_id,
            "secret_key": self.secret_key,
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=data)
                response.raise_for_status()
                token_data = response.json()
                return token_data.get("access")
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get access token: {e}")
                raise HTTPException(status_code=400, detail="Failed to authenticate with GoCardless")
            except Exception as e:
                logger.error(f"Unexpected error getting access token: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
    
    async def get_institutions(self, country_code: str = "FR") -> List[Dict[str, Any]]:
        """Récupère la liste des institutions bancaires disponibles"""
        token = await self.get_access_token()
        url = f"{self.base_url}/institutions/"
        
        headers = {"Authorization": f"Bearer {token}"}
        params = {"country": country_code}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get institutions: {e}")
                raise HTTPException(status_code=400, detail="Failed to retrieve institutions")
    
    async def create_end_user_agreement(self, institution_id: str, max_historical_days: int = 90) -> Dict[str, Any]:
        """Crée un accord utilisateur final pour accéder aux données bancaires"""
        token = await self.get_access_token()
        url = f"{self.base_url}/agreements/enduser/"
        
        headers = {"Authorization": f"Bearer {token}"}
        data = {
            "institution_id": institution_id
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to create end user agreement: {e}")
                raise HTTPException(status_code=400, detail="Failed to create user agreement")
    
    async def create_requisition(self, institution_id: str, redirect_url: str = "https://localhost:5173") -> Dict[str, Any]:
        """Crée une réquisition pour l'autorisation d'accès aux comptes"""
        token = await self.get_access_token()
        
        # D'abord créer l'accord utilisateur
        agreement = await self.create_end_user_agreement(institution_id)
        agreement_id = agreement.get("id")
        
        url = f"{self.base_url}/requisitions/"
        headers = {"Authorization": f"Bearer {token}"}
        data = {
            "redirect": redirect_url,
            "institution_id": institution_id,
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to create requisition: {e}")
                raise HTTPException(status_code=400, detail="Failed to create requisition")
    
    async def get_accounts(self, requisition_id: str) -> List[str]:
        """Récupère la liste des comptes associés à une réquisition"""
        token = await self.get_access_token()
        url = f"{self.base_url}/requisitions/{requisition_id}/"
        
        headers = {"Authorization": f"Bearer {token}"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                requisition_data = response.json()
                return requisition_data.get("accounts", [])
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get accounts: {e}")
                raise HTTPException(status_code=400, detail="Failed to retrieve accounts")
    
    async def get_account_details(self, account_id: str) -> Dict[str, Any]:
        """Récupère les détails d'un compte"""
        token = await self.get_access_token()
        url = f"{self.base_url}/accounts/{account_id}/details/"
        
        headers = {"Authorization": f"Bearer {token}"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get account details: {e}")
                raise HTTPException(status_code=400, detail="Failed to retrieve account details")
    
    async def get_account_balances(self, account_id: str) -> Dict[str, Any]:
        """Récupère les soldes d'un compte"""
        token = await self.get_access_token()
        url = f"{self.base_url}/accounts/{account_id}/balances/"
        
        headers = {"Authorization": f"Bearer {token}"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get account balances: {e}")
                raise HTTPException(status_code=400, detail="Failed to retrieve account balances")
    
    async def get_account_transactions(self, account_id: str, date_from: Optional[date] = None, date_to: Optional[date] = None) -> List[Transaction]:
        """Récupère les transactions d'un compte et les convertit en objets Transaction"""
        token = await self.get_access_token()
        url = f"{self.base_url}/accounts/{account_id}/transactions/"
        
        headers = {"Authorization": f"Bearer {token}"}
        
        # Si aucune date n'est spécifiée, récupère les transactions des 30 derniers jours
        if not date_from:
            date_from = date.today() - timedelta(days=30)
        if not date_to:
            date_to = date.today()
        
        params = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat()
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                transactions_data = response.json()
                
                # Convertir les données GoCardless en objets Transaction
                transactions = []
                for tx_data in transactions_data.get("transactions", {}).get("booked", []):
                    try:
                        transaction = self._convert_gocardless_to_transaction(tx_data)
                        transactions.append(transaction)
                    except Exception as e:
                        logger.warning(f"Failed to convert transaction: {e}")
                        continue
                
                return transactions
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get account transactions: {e}")
                raise HTTPException(status_code=400, detail="Failed to retrieve account transactions")
    
    def _convert_gocardless_to_transaction(self, gocardless_data: Dict[str, Any]) -> Transaction:
        """Convertit une transaction GoCardless en objet Transaction"""
        
        # Créer l'objet TransactionAmount
        transaction_amount = TransactionAmount(
            amount=gocardless_data.get("transactionAmount", {}).get("amount", "0"),
            currency=gocardless_data.get("transactionAmount", {}).get("currency", "EUR")
        )
        
        # Convertir les dates
        booking_date = datetime.fromisoformat(gocardless_data.get("bookingDate", "")).date()
        value_date = datetime.fromisoformat(gocardless_data.get("valueDate", "")).date()
        
        # Récupérer les informations de remise
        remittance_info = gocardless_data.get("remittanceInformationUnstructuredArray", [])
        if not remittance_info:
            remittance_info = [gocardless_data.get("remittanceInformationUnstructured", "")]
        
        return Transaction(
            entryReference=gocardless_data.get("entryReference", ""),
            bookingDate=booking_date,
            valueDate=value_date,
            transactionAmount=transaction_amount,
            remittanceInformationUnstructuredArray=remittance_info,
            internalTransactionId=gocardless_data.get("internalTransactionId", gocardless_data.get("transactionId", ""))
        )


class TransactionService:
    """Service principal pour gérer les transactions"""
    
    def __init__(self):
        self.gocardless_service = GoCardlessService()
    
    async def get_bank_institutions(self, country_code: str = "FR") -> List[Dict[str, Any]]:
        """Récupère la liste des banques disponibles"""
        return await self.gocardless_service.get_institutions(country_code)
    
    async def initiate_bank_connection(self, institution_id: str, redirect_url: str = "https://your-app.com/callback") -> Dict[str, Any]:
        """Initie une connexion à une banque"""
        return await self.gocardless_service.create_requisition(institution_id, redirect_url)
    
    async def get_user_accounts(self, requisition_id: str) -> List[Dict[str, Any]]:
        """Récupère les comptes d'un utilisateur"""
        account_ids = await self.gocardless_service.get_accounts(requisition_id)
        accounts = []
        
        for account_id in account_ids:
            try:
                details = await self.gocardless_service.get_account_details(account_id)
                balances = await self.gocardless_service.get_account_balances(account_id)
                
                account_info = {
                    "account_id": account_id,
                    "details": details,
                    "balances": balances
                }
                accounts.append(account_info)
            except Exception as e:
                logger.warning(f"Failed to get details for account {account_id}: {e}")
        
        return accounts
    
    async def get_transactions_from_bank(self, account_id: str, date_from: Optional[date] = None, date_to: Optional[date] = None) -> List[Transaction]:
        """Récupère les transactions bancaires depuis GoCardless"""
        return await self.gocardless_service.get_account_transactions(account_id, date_from, date_to)
    
    async def sync_all_accounts_transactions(self, requisition_id: str, days_back: int = 30) -> Dict[str, List[Transaction]]:
        """Synchronise les transactions de tous les comptes"""
        account_ids = await self.gocardless_service.get_accounts(requisition_id)
        all_transactions = {}
        
        date_from = date.today() - timedelta(days=days_back)
        date_to = date.today()
        
        for account_id in account_ids:
            try:
                transactions = await self.get_transactions_from_bank(account_id, date_from, date_to)
                all_transactions[account_id] = transactions
                logger.info(f"Retrieved {len(transactions)} transactions for account {account_id}")
            except Exception as e:
                logger.error(f"Failed to sync transactions for account {account_id}: {e}")
                all_transactions[account_id] = []
        
        return all_transactions


# Instance globale du service
transaction_service = TransactionService()