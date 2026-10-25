"""Backend representations and validation for the verified lead JSON format."""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceBusiness(BaseModel):
    model_config = ConfigDict(extra='ignore')
    business_name: str | None = None
    website: str | None = None
    category: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None


class SourceContacts(BaseModel):
    model_config = ConfigDict(extra='ignore')
    emails: list[str] | None = Field(default_factory=list)
    phone_numbers: list[str] | None = Field(default_factory=list)


class SourceScoring(BaseModel):
    model_config = ConfigDict(extra='ignore')
    lead_score: float | None = None
    qualification_status: str | None = None


class SourceLead(BaseModel):
    model_config = ConfigDict(extra='ignore')
    lead_id: str
    business: SourceBusiness | None = None
    contacts: SourceContacts | None = None
    lead_scoring: SourceScoring | None = None


class NormalizedPhone(BaseModel):
    original_value: str
    normalized_value: str


class InvalidPhone(BaseModel):
    original_value: str
    reason: str


class LeadOutcome(StrEnum):
    eligible = 'eligible'
    rejected = 'rejected'
    manual_review = 'manual_review'


class ConsentGate(BaseModel):
    approved: bool = False
    consent_or_lawful_basis_verified: bool = False
    dispatch_enabled: bool = False


class LeadEligibility(BaseModel):
    outcome: LeadOutcome
    call_eligible: bool
    reasons: list[str] = Field(default_factory=list)
    consent: ConsentGate = Field(default_factory=ConsentGate)


class PreparedLead(BaseModel):
    lead_id: str
    business_name: str | None
    website: str | None
    category: str | None
    address: str | None
    email_addresses: list[str]
    phone_numbers: list[NormalizedPhone]
    invalid_phone_numbers: list[InvalidPhone]
    lead_score: float | None
    qualification_status: str | None
    eligibility: LeadEligibility


class LeadPreviewResponse(BaseModel):
    total: int
    eligible: int
    rejected: int
    manual_review: int
    dispatch_enabled: bool = False
    leads: list[PreparedLead]


class LeadFileError(Exception):
    """Lead data could not be loaded or parsed."""


def normalize_indian_mobile(value: str) -> str:
    """Normalize only supported Indian mobile formats, rejecting other values."""
    raw = value.strip()
    if not raw or not re.fullmatch(r'\+?[0-9](?:[0-9\s().-]*[0-9])?', raw):
        raise ValueError('Phone value is empty or contains unsupported formatting.')
    digits = re.sub(r'\D', '', raw)
    if digits.startswith('91') and len(digits) == 12:
        national = digits[2:]
    elif len(digits) == 10:
        national = digits
    else:
        raise ValueError('Expected a 10-digit Indian mobile or 91 plus 10 digits.')
    if not re.fullmatch(r'[6-9]\d{9}', national):
        raise ValueError('Number does not match the supported Indian mobile format.')
    return f'+91{national}'


def prepare_lead(source: SourceLead) -> PreparedLead:
    business = source.business or SourceBusiness()
    contacts = source.contacts or SourceContacts()
    scoring = source.lead_scoring or SourceScoring()
    business_name = (business.business_name or '').strip() or None
    raw_phones = [business.phone] if business.phone else []
    raw_phones.extend(contacts.phone_numbers or [])
    normalized: list[NormalizedPhone] = []
    invalid: list[InvalidPhone] = []
    seen: set[str] = set()
    for original in raw_phones:
        try:
            value = normalize_indian_mobile(original)
        except ValueError as exc:
            invalid.append(InvalidPhone(original_value=original, reason=str(exc)))
            continue
        if value not in seen:
            seen.add(value)
            normalized.append(NormalizedPhone(original_value=original, normalized_value=value))

    reasons: list[str] = []
    if not business_name:
        reasons.append('Business name is missing.')
    if not raw_phones:
        reasons.append('No phone number was supplied.')
    elif not normalized:
        reasons.append('No valid phone number is available.')
    if invalid:
        reasons.append('At least one supplied phone number requires manual review.')
    qualification = (scoring.qualification_status or '').strip()
    if qualification.casefold() == 'needs review':
        reasons.append('Lead qualification status is Needs Review.')

    if not business_name or not raw_phones or (raw_phones and not normalized):
        outcome = LeadOutcome.rejected
    elif invalid or qualification.casefold() == 'needs review':
        outcome = LeadOutcome.manual_review
    else:
        outcome = LeadOutcome.eligible

    raw_emails = ([business.email] if business.email else []) + (contacts.emails or [])
    return PreparedLead(
        lead_id=source.lead_id,
        business_name=business_name,
        website=business.website,
        category=business.category,
        address=business.address,
        email_addresses=list(dict.fromkeys(
            email.strip().casefold() for email in raw_emails if email and email.strip()
        )),
        phone_numbers=normalized,
        invalid_phone_numbers=invalid,
        lead_score=scoring.lead_score,
        qualification_status=scoring.qualification_status,
        eligibility=LeadEligibility(
            outcome=outcome,
            call_eligible=outcome == LeadOutcome.eligible,
            reasons=reasons,
            consent=ConsentGate(),
        ),
    )
