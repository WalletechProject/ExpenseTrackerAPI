from pydantic import BaseModel, Field, validator
from datetime import date, datetime
from typing import List, Optional, Literal
from decimal import Decimal
from enum import Enum


class TransactionType(str, Enum):
    """Énumération pour le type de transaction"""
    INCOME = "income"
    EXPENSE = "expense"


class TransactionAmount(BaseModel):
    """Modèle pour le montant de la transaction"""
    amount: str = Field(..., description="Montant de la transaction (négatif pour les débits)")
    currency: str = Field(..., description="Code de devise (ex: EUR, USD)")


class Transaction(BaseModel):
    """Modèle pour une transaction bancaire"""
    entryReference: str = Field(..., description="Référence unique de l'écriture")
    bookingDate: date = Field(..., description="Date de comptabilisation")
    valueDate: date = Field(..., description="Date de valeur")
    transactionAmount: TransactionAmount = Field(..., description="Montant et devise de la transaction")
    remittanceInformationUnstructuredArray: List[str] = Field(
        ..., 
        description="Informations de remise non structurées"
    )
    internalTransactionId: str = Field(..., description="Identifiant interne de la transaction")
    transaction_type: Optional[TransactionType] = Field(
        None, 
        description="Type de transaction (automatiquement défini: income si positif, expense si négatif)"
    )
    
    @validator('transaction_type', always=True)
    def set_transaction_type(cls, v, values):
        """Détermine automatiquement le type de transaction basé sur le montant"""
        if 'transactionAmount' in values:
            amount_str = values['transactionAmount'].amount
            try:
                amount_value = float(amount_str)
                return TransactionType.INCOME if amount_value >= 0 else TransactionType.EXPENSE
            except (ValueError, AttributeError):
                return TransactionType.EXPENSE  # Par défaut si conversion échoue
        return v
    
    class Config:
        """Configuration du modèle"""
        json_encoders = {
            date: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "entryReference": "8537030481969",
                "bookingDate": "2025-06-30",
                "valueDate": "2025-06-30",
                "transactionAmount": {
                    "amount": "-5.49",
                    "currency": "EUR"
                },
                "remittanceInformationUnstructuredArray": [
                    "PAIEMENT PAR CARTE X2592 SoundCloud Monthly G 27/06"
                ],
                "internalTransactionId": "85dbe91859a05d1e5c5ba3438c3bb7d4",
                "transaction_type": "expense"
            }
        }


class TransactionCreate(Transaction):
    """Modèle pour la création d'une transaction"""
    pass


class TransactionUpdate(BaseModel):
    """Modèle pour la mise à jour d'une transaction"""
    entryReference: Optional[str] = None
    bookingDate: Optional[date] = None
    valueDate: Optional[date] = None
    transactionAmount: Optional[TransactionAmount] = None
    remittanceInformationUnstructuredArray: Optional[List[str]] = None
    internalTransactionId: Optional[str] = None
    transaction_type: Optional[TransactionType] = Field(
        None, 
        description="Type de transaction (automatiquement mis à jour si transactionAmount change)"
    )
    
    @validator('transaction_type', always=True)
    def set_transaction_type(cls, v, values):
        """Détermine automatiquement le type de transaction basé sur le montant"""
        if 'transactionAmount' in values and values['transactionAmount']:
            amount_str = values['transactionAmount'].amount
            try:
                amount_value = float(amount_str)
                return TransactionType.INCOME if amount_value >= 0 else TransactionType.EXPENSE
            except (ValueError, AttributeError):
                return v  # Garde la valeur existante si conversion échoue
        return v


class TransactionResponse(Transaction):
    """Modèle de réponse pour une transaction avec métadonnées"""
    id: Optional[str] = Field(None, description="ID MongoDB de la transaction")
    created_at: Optional[date] = Field(None, description="Date de création")
    updated_at: Optional[date] = Field(None, description="Date de dernière mise à jour")
    
    class Config:
        """Configuration du modèle de réponse"""
        from_attributes = True


class AccountBalance(BaseModel):
    """Modèle pour suivre l'évolution de la balance du compte"""
    balance: str = Field(..., description="Solde du compte")
    currency: str = Field(..., description="Code de devise (ex: EUR, USD)")
    balance_date: date = Field(..., description="Date à laquelle le solde a été calculé")
    transaction_id: Optional[str] = Field(None, description="ID de la transaction qui a causé ce changement de solde")
    
    @validator('balance')
    def validate_balance(cls, v):
        """Valide que le solde est un nombre valide"""
        try:
            float(v)
            return v
        except ValueError:
            raise ValueError("Le solde doit être un nombre valide")
    
    class Config:
        """Configuration du modèle"""
        json_encoders = {
            date: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "balance": "1250.75",
                "currency": "EUR",
                "balance_date": "2025-06-30",
                "transaction_id": "85dbe91859a05d1e5c5ba3438c3bb7d4"
            }
        }


class AccountBalanceCreate(BaseModel):
    """Modèle pour la création d'un enregistrement de balance"""
    balance: str = Field(..., description="Solde du compte")
    currency: str = Field(..., description="Code de devise (ex: EUR, USD)")
    balance_date: Optional[date] = Field(None, description="Date du solde (par défaut: aujourd'hui)")
    transaction_id: Optional[str] = Field(None, description="ID de la transaction associée")
    
    @validator('balance_date', always=True)
    def set_default_date(cls, v):
        """Définit la date du jour par défaut si non fournie"""
        return v or date.today()
    
    @validator('balance')
    def validate_balance(cls, v):
        """Valide que le solde est un nombre valide"""
        try:
            float(v)
            return v
        except ValueError:
            raise ValueError("Le solde doit être un nombre valide")


class AccountBalanceResponse(AccountBalance):
    """Modèle de réponse pour un enregistrement de balance avec métadonnées"""
    id: Optional[str] = Field(None, description="ID MongoDB de l'enregistrement")
    created_at: Optional[datetime] = Field(None, description="Date de création de l'enregistrement")
    
    class Config:
        """Configuration du modèle de réponse"""
        from_attributes = True
        json_encoders = {
            date: lambda v: v.isoformat(),
            datetime: lambda v: v.isoformat()
        }
