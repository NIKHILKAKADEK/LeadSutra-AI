"""Authenticated SMTP with verified TLS; no provider responses or secrets logged."""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import EmailSettings

logger = logging.getLogger("leadsutra.smtp")


class SmtpEmailProvider:
    def __init__(self, settings: EmailSettings):
        self.settings = settings

    def send(self, message: EmailMessage) -> str:
        settings = self.settings
        context = ssl.create_default_context()
        options = {"host": settings.smtp_host, "port": settings.smtp_port,
                   "timeout": settings.smtp_timeout_seconds}
        logger.info("SMTP connecting to %s:%s (security=%s)", settings.smtp_host, settings.smtp_port, settings.smtp_security)
        if settings.smtp_security == "ssl":
            connection = smtplib.SMTP_SSL(**options, context=context)
        else:
            connection = smtplib.SMTP(**options)
        with connection as smtp:
            if settings.smtp_security == "starttls":
                smtp.starttls(context=context)
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            refused = smtp.send_message(message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
        logger.info("SMTP message accepted by %s:%s", settings.smtp_host, settings.smtp_port)
        return message["Message-ID"] or ""
