import logging
import hashlib
import json
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from app.agents.email.agent import build_message, generate_proposal_email
from app.agents.lead_pipeline.pipeline import EMAIL_RE, _valid_email
from app.core.config import EmailSettings, get_email_settings
from app.integrations.smtp import SmtpEmailProvider
from app.agents.lead_pipeline.schema import LeadResult
from app.agents.email.schema import EmailDraft, EmailResult
from app.services.email_results import EmailResultStore
from app.services.lead_results import LeadResultStore
from app.services.proposals import ProposalFileError, ProposalJsonService
from app.services.research_outputs import ResearchOutputService

logger = logging.getLogger("leadsutra.email")


def _documented_service_catalog() -> str:
    """Load the business's own static service descriptions for grounded personalization."""
    root = Path(__file__).resolve().parents[2] / "data" / "rag"
    catalog_files = (
        "website_services.txt", "digital_marketing.txt",
        "lead_generation_crm.txt", "social_media_delivery.txt",
    )
    parts = []
    for filename in catalog_files:
        try:
            text = (root / filename).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            parts.append(text)
    return "\n\n".join(parts)[:8000]


class EmailWorkflowError(Exception):
    def __init__(self, status_code: int, code: str):
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.email_id: UUID | None = None


class EmailService:
    def __init__(self, settings: EmailSettings, provider=None):
        self.settings = settings
        self.store = EmailResultStore(settings.email_db_path)
        self.proposals = ProposalJsonService(settings.proposal_root)
        self.provider = provider if provider is not None else SmtpEmailProvider(settings)

    def _lead(self, lead_id: str) -> LeadResult:
        try:
            lead = LeadResultStore(self.settings.lead_json_path).get_by_id(lead_id)
        except (OSError, RuntimeError, ValueError, ValidationError):
            raise EmailWorkflowError(503, "lead_source_unavailable") from None
        if lead is not None:
            return lead
        raise EmailWorkflowError(404, "lead_not_found")

    def preview(
        self, lead_id: str, *, template: str | None = None,
        regenerate: bool = False, research_if_missing: bool = False,
    ) -> EmailDraft:
        lead = self._lead(lead_id)
        try:
            proposal = self.proposals.load(lead_id)
        except ProposalFileError:
            raise EmailWorkflowError(422, "proposal_invalid") from None
        if proposal is None:
            raise EmailWorkflowError(404, "proposal_not_found")
        candidates = list(lead.enrichment.emails)
        if lead.discovery.email:
            candidates.append(lead.discovery.email)
        # Existing extractor order selects its first email; skip unusable values,
        # then use the existing listing fallback, without extracting again.
        recipient = next((value for raw in candidates if (value := _valid_email(raw))), None)
        if recipient is None:
            raise EmailWorkflowError(422, "recipient_unavailable")
        sender = (self.settings.smtp_from_address or "").strip()
        if not EMAIL_RE.fullmatch(sender):
            raise EmailWorkflowError(503, "email_configuration_unavailable")
        generation_settings = {
            "company_name": self.settings.outreach_company_name,
            "company_summary": self.settings.outreach_company_summary,
            "service_offerings": self.settings.outreach_service_offerings,
            "contact_name": self.settings.outreach_contact_name,
            "signature": self.settings.outreach_email_signature,
            "tagline": self.settings.outreach_email_tagline,
            "website_url": self.settings.outreach_website_url,
            "intro_call_minutes": self.settings.outreach_intro_call_minutes,
            "template": template if template is not None else self.settings.outreach_email_template,
            "company_service_catalog": _documented_service_catalog(),
        }
        fingerprint_data = {
            "lead": lead.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
            "sender": sender,
            "recipient": recipient,
            "settings": generation_settings,
        }
        try:
            research = ResearchOutputService(self.settings.research_root).load(lead_id)
        except (RuntimeError, OSError, ValueError):
            research = None
        if research is None and research_if_missing:
            try:
                from app.services.ai_agents import analyze_lead
                research = analyze_lead(lead)
            except Exception:
                logger.exception("Could not generate research before email preview for lead %s", lead_id)
        fingerprint_data["research"] = research
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_data, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        try:
            cached = None if regenerate else self.store.generated_draft(fingerprint)
            if cached is None:
                subject, body = generate_proposal_email(
                    lead, proposal, sender, company_name=generation_settings["company_name"],
                    company_summary=generation_settings["company_summary"],
                    service_offerings=generation_settings["service_offerings"],
                    sender_contact_name=generation_settings["contact_name"],
                    signature=generation_settings["signature"], tagline=generation_settings["tagline"],
                    intro_call_minutes=generation_settings["intro_call_minutes"],
                    template=generation_settings["template"],
                    company_website=generation_settings["website_url"], research=research,
                    company_service_catalog=generation_settings["company_service_catalog"],
                )
                subject, body = self.store.save_generated_draft(
                    fingerprint, subject, body, lead_id=lead_id,
                    template=generation_settings["template"], replace=regenerate,
                )
            else:
                subject, body = cached
        except ValueError as exc:
            code = str(exc) if str(exc) == "email_business_name_invalid" else "email_generation_failed"
            status = 422 if code == "email_business_name_invalid" else 502
            raise EmailWorkflowError(status, code) from None
        except (RuntimeError, OSError):
            raise EmailWorkflowError(502, "email_generation_failed") from None
        draft = EmailDraft(lead_id=lead_id, business_name=lead.discovery.business_name,
                           recipient=recipient, sender=sender, subject=subject, body=body,
                           proposal_file=f"{lead_id}/proposal.json", draft_key=fingerprint,
                           template=generation_settings["template"], review_id="")
        reviewed = {"draft": draft.model_dump(exclude={"review_id", "approved"}),
                    "proposal": proposal.model_dump()}
        draft.review_id = hashlib.sha256(json.dumps(reviewed, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        draft.approved = self.store.approved(draft.review_id)
        return draft

    def approve(
        self, lead_id: str, review_id: str, approved: bool, principal: str, *,
        template: str | None = None, subject: str | None = None, body: str | None = None,
    ) -> EmailDraft:
        draft = self.preview(lead_id, template=template)
        if draft.review_id != review_id:
            raise EmailWorkflowError(409, "email_review_changed")
        if subject is not None or body is not None:
            if (subject is None or body is None or
                    any(ord(char) < 32 or ord(char) == 127 for char in subject) or
                    not 5 <= len(subject.strip()) <= 180 or not 80 <= len(body.strip()) <= 12000):
                raise EmailWorkflowError(422, "email_draft_invalid")
            self.store.save_generated_draft(
                draft.draft_key, subject.strip(), body.strip(), lead_id=lead_id,
                template=template if template is not None else self.settings.outreach_email_template,
                replace=True,
            )
            draft = self.preview(lead_id, template=template)
        self.store.set_approval(draft.review_id, approved, principal)
        draft.approved = approved
        return draft

    def _validate_configuration(self) -> None:
        if not self.settings.email_sending_enabled:
            raise EmailWorkflowError(503, "email_sending_disabled")
        if not all((self.settings.smtp_host and self.settings.smtp_host.strip(),
                    self.settings.smtp_username and self.settings.smtp_username.strip(),
                    self.settings.smtp_password and self.settings.smtp_password.get_secret_value())):
            raise EmailWorkflowError(503, "email_configuration_unavailable")

    def queue(self, lead_id: str, draft_key: str | None = None) -> tuple[EmailResult, bool]:
        try:
            template = self.store.generated_template(draft_key) if draft_key else None
            draft = self.preview(lead_id, template=template)
            if draft_key and draft.draft_key != draft_key:
                raise EmailWorkflowError(409, "email_review_changed")
            if not draft.approved:
                raise EmailWorkflowError(403, "proposal_not_approved")
            self._validate_configuration()
        except EmailWorkflowError as exc:
            failure = self.store.record_failure(lead_id, exc.code)
            exc.email_id = failure.email_id
            raise
        return self.store.enqueue(draft)

    def send(self, email_id: UUID) -> None:
        record = self.store.claim(email_id)
        if record is None:
            return
        try:
            template = self.store.generated_template(record.draft_key) if record.draft_key else None
            draft = self.preview(record.lead_id, template=template)
            if draft.review_id != record.review_id or not draft.approved:
                raise EmailWorkflowError(409, "email_approval_changed")
            self._validate_configuration()
            message = build_message(draft)
        except EmailWorkflowError as exc:
            self.store.finish(email_id, "failed", exc.code)
            return
        try:
            message_id = self.provider.send(message)
        except smtplib.SMTPServerDisconnected as exc:
            logger.error("SMTP server disconnected during send for email_id=%s: %s: %s",
                         email_id, type(exc).__name__, exc)
            self.store.finish(email_id, "uncertain", "email_provider_outcome_uncertain")
        except smtplib.SMTPException as exc:
            logger.error("SMTP provider rejected send for email_id=%s: %s: %s",
                         email_id, type(exc).__name__, exc)
            self.store.finish(email_id, "failed", "email_provider_rejected")
        except OSError as exc:
            logger.error("OS/network error during send for email_id=%s: %s: %s",
                         email_id, type(exc).__name__, exc)
            self.store.finish(email_id, "uncertain", "email_provider_outcome_uncertain")
        except Exception as exc:
            logger.error("Unexpected error during send for email_id=%s: %s: %s",
                         email_id, type(exc).__name__, exc)
            self.store.finish(email_id, "uncertain", "email_provider_outcome_uncertain")
        else:
            logger.info("Email sent successfully for email_id=%s message_id=%s", email_id, message_id)
            self.store.finish(email_id, "sent", message_id=message_id)

    def result(self, email_id: UUID) -> EmailResult:
        result = self.store.get(email_id)
        if result is None:
            raise EmailWorkflowError(404, "email_not_found")
        return result


def get_email_service() -> EmailService:
    return EmailService(get_email_settings())
