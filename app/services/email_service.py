"""Review and approval-gated background email using existing saved outputs."""

import hashlib
import json
import logging
import smtplib
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from app.agents.email.agent import build_message, proposal_email_content
from app.agents.lead_pipeline.pipeline import EMAIL_RE, _valid_email
from app.core.config import EmailSettings, get_email_settings
from app.integrations.smtp import SmtpEmailProvider
from app.agents.lead_pipeline.schemas import LeadResult
from app.schemas.email import EmailDraft, EmailResult
from app.services.email_results import EmailResultStore
from app.services.lead_results import LeadResultStore
from app.services.proposals import ProposalFileError, ProposalJsonService

logger = logging.getLogger("leadsutra.email")


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
        path = Path(self.settings.lead_json_path)
        try:
            if path.is_dir():
                paths = sorted((p for p in path.glob("*/leads.json") if not p.parent.name.startswith(".")),
                               key=lambda p: (p.stat().st_mtime_ns, str(p)), reverse=True)
            elif path.is_file():
                paths = [path]
            else:
                raise EmailWorkflowError(503, "lead_source_unavailable")
            for artifact in paths:
                # Reuse canonical validation, credential checks and run-ID path validation.
                leads = LeadResultStore(artifact.parent.parent).load(artifact.parent.name)
                lead = next((item for item in leads if item.lead_id == lead_id), None)
                if lead is not None:
                    return lead
        except (OSError, ValueError, ValidationError):
            raise EmailWorkflowError(503, "lead_source_unavailable") from None
        raise EmailWorkflowError(404, "lead_not_found")

    def preview(self, lead_id: str) -> EmailDraft:
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
        try:
            subject, body = proposal_email_content(lead.discovery.business_name, proposal)
        except ValueError as exc:
            raise EmailWorkflowError(422, str(exc)) from None
        draft = EmailDraft(lead_id=lead_id, business_name=lead.discovery.business_name,
                           recipient=recipient, sender=sender, subject=subject, body=body,
                           proposal_file=f"{lead_id}/proposal.json", review_id="")
        reviewed = {"draft": draft.model_dump(exclude={"review_id", "approved"}),
                    "proposal": proposal.model_dump()}
        draft.review_id = hashlib.sha256(json.dumps(reviewed, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        draft.approved = self.store.approved(draft.review_id)
        return draft

    def approve(self, lead_id: str, review_id: str, approved: bool, principal: str) -> EmailDraft:
        draft = self.preview(lead_id)
        if draft.review_id != review_id:
            raise EmailWorkflowError(409, "email_review_changed")
        self.store.set_approval(review_id, approved, principal)
        draft.approved = approved
        return draft

    def _validate_configuration(self) -> None:
        if not self.settings.email_sending_enabled:
            raise EmailWorkflowError(503, "email_sending_disabled")
        if not all((self.settings.smtp_host and self.settings.smtp_host.strip(),
                    self.settings.smtp_username and self.settings.smtp_username.strip(),
                    self.settings.smtp_password and self.settings.smtp_password.get_secret_value())):
            raise EmailWorkflowError(503, "email_configuration_unavailable")

    def queue(self, lead_id: str) -> tuple[EmailResult, bool]:
        try:
            draft = self.preview(lead_id)
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
            draft = self.preview(record.lead_id)
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
