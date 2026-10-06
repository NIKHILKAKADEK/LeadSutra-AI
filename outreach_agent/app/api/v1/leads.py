from fastapi import APIRouter, HTTPException, status

from fastapi import Depends, Path, Query

from app.api.v1.calling_eligibility import require_reviewer
from app.core.config import get_settings
from app.models.lead_management import LeadDetailsResponse, LeadListItem, LeadListResponse
from app.models.call_history import CallHistoryItem, CallHistoryPage
from app.models.leads import LeadFileError, LeadOutcome, LeadPreviewResponse, PreparedLead
from app.services.call_dispatch import DispatchLedger
from app.services.leads import LeadJsonService

router = APIRouter(prefix='/leads', tags=['leads'])


def _load_leads() -> list[PreparedLead]:
    try:
        return LeadJsonService(get_settings().lead_json_path).load()
    except LeadFileError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={'status': 'unavailable', 'message': 'Lead source is unavailable.'},
        ) from None


def _list_item(lead: PreparedLead) -> LeadListItem:
    return LeadListItem(
        lead_id=lead.lead_id,
        business_name=lead.business_name,
        category=lead.category,
        qualification_status=lead.qualification_status,
        lead_score=lead.lead_score,
        phone_numbers=[phone.normalized_value for phone in lead.phone_numbers],
    )


@router.get(
    '', response_model=LeadListResponse,
    dependencies=[Depends(require_reviewer)],
    summary='List and filter leads',
    description='Read-only listing from the configured lead JSON source. Phone numbers are normalized; eligibility filtering is intentionally separate.',
)
def list_leads(
    limit: int = Query(default=25, ge=1, le=100, description='Maximum number of results to return.'),
    offset: int = Query(default=0, ge=0, le=1_000_000, description='Number of matching results to skip.'),
    search: str | None = Query(default=None, max_length=200, description='Case-insensitive substring of business name.'),
    qualification_status: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=100),
) -> LeadListResponse:
    leads = _load_leads()
    search_value = search.strip().casefold() if search and search.strip() else None
    qualification_value = qualification_status.strip().casefold() if qualification_status else None
    category_value = category.strip().casefold() if category else None
    matching = [lead for lead in leads if
                (search_value is None or search_value in (lead.business_name or '').casefold()) and
                (qualification_value is None or qualification_value == (lead.qualification_status or '').strip().casefold()) and
                (category_value is None or category_value == (lead.category or '').strip().casefold())]
    return LeadListResponse(total=len(matching), limit=limit, offset=offset,
                            leads=[_list_item(lead) for lead in matching[offset:offset + limit]])


@router.get('/preview', response_model=LeadPreviewResponse,
            dependencies=[Depends(require_reviewer)],
            summary='Preview imported leads',
            description='Read-only legacy preview. Use the protected calling-eligibility route for per-lead eligibility.')
def preview_leads() -> LeadPreviewResponse:
    """Preview parsed leads and eligibility. This endpoint never dispatches calls."""
    leads = _load_leads()
    counts = {outcome: sum(lead.eligibility.outcome == outcome for lead in leads) for outcome in LeadOutcome}
    return LeadPreviewResponse(
        total=len(leads),
        eligible=counts[LeadOutcome.eligible],
        rejected=counts[LeadOutcome.rejected],
        manual_review=counts[LeadOutcome.manual_review],
        dispatch_enabled=False,
        leads=leads,
    )


@router.get(
    '/{lead_id}', response_model=LeadDetailsResponse,
    dependencies=[Depends(require_reviewer)],
    summary='Get lead details',
    description='Returns a restricted lead projection. Consent evidence, email addresses, invalid raw phone values, and internal records are excluded.',
)
def get_lead(lead_id: str = Path(min_length=1, max_length=256)) -> LeadDetailsResponse:
    lead = next((item for item in _load_leads() if item.lead_id == lead_id), None)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={'status': 'not_found', 'message': 'Lead was not found.'})
    return LeadDetailsResponse(
        lead_id=lead.lead_id,
        business_name=lead.business_name,
        website=lead.website,
        category=lead.category,
        address=lead.address,
        # Contact names are not represented in the current validated source model.
        contact_names=[],
        phone_numbers=[phone.normalized_value for phone in lead.phone_numbers],
        lead_score=lead.lead_score,
        qualification_status=lead.qualification_status,
    )


@router.get(
    '/{lead_id}/calls', response_model=CallHistoryPage,
    dependencies=[Depends(require_reviewer)],
    summary='List dispatch history for a lead',
)
def get_lead_calls(
    lead_id: str = Path(min_length=1, max_length=256),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> CallHistoryPage:
    if not any(lead.lead_id == lead_id for lead in _load_leads()):
        raise HTTPException(status_code=404, detail={'status': 'not_found', 'message': 'Lead was not found.'})
    records, total = DispatchLedger(get_settings().eligibility_db_path).list_records(
        lead_id=lead_id, status=None, limit=limit, offset=offset)
    return CallHistoryPage(total=total, limit=limit, offset=offset,
                           calls=[CallHistoryItem(**record) for record in records])
