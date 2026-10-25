"""Plain-text formatting of existing proposal facts; no proposal generation."""

from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.schemas.email import EmailDraft
from app.schemas.proposal import ProposalResult


def proposal_email_content(business_name: str, proposal: ProposalResult) -> tuple[str, str]:
    if not business_name.strip() or any(c in business_name for c in "\r\n"):
        raise ValueError("email_business_name_invalid")
    sections = []
    for field, label in (
        ("business_context", "Business context"), ("proposed_service", "Proposed service"),
        ("approved_product_facts", "Product facts"), ("approved_pricing", "Pricing"),
    ):
        value = getattr(proposal, field)
        if value and value.strip():
            sections.append(f"{label}\n{value}")
    if not sections:
        raise ValueError("proposal_empty")
    return f"Proposal for {business_name}", "\n\n".join(sections)


def build_message(draft: EmailDraft) -> EmailMessage:
    message = EmailMessage()
    message["From"] = draft.sender
    message["To"] = draft.recipient
    message["Subject"] = draft.subject
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = make_msgid()
    message.set_content(draft.body)
    return message
