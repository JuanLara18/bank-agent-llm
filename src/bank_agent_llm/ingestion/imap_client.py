"""IMAP client — connects to email accounts and downloads bank statement attachments.

Design:
- One ImapClient instance per email account config.
- Searches INBOX (and configured folders) for emails matching subject keywords.
- Downloads PDF/XLSX attachments to the configured raw_data_dir.
- Tracks processed message-IDs in the DB so re-runs are idempotent.
- Graceful degradation: connection errors are logged, not raised — the
  pipeline continues with whatever was already downloaded.
"""

from __future__ import annotations

import email
import email.header
import logging
import re
import unicodedata
from email.message import Message
from pathlib import Path

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Attachment MIME types we care about
_WANTED_TYPES = {
    "application/pdf",
    "application/octet-stream",   # some banks send PDFs with wrong MIME
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}
_WANTED_EXTENSIONS = {".pdf", ".xlsx", ".xls"}

# Senders known to send bank statements (case-insensitive substring match)
_BANK_SENDERS = [
    "bancolombia",
    "mensajeria@",
    "notificaciones@",
    "extractos@",
    "falabella",
    "scotiabank",
    "davibank",
    "davivienda",
    "colpatria",
    "nequi",
]


def _decode_header(raw: str) -> str:
    """Decode RFC 2047-encoded email header value."""
    parts = email.header.decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _safe_filename(name: str) -> str:
    """Normalise an attachment filename so it's safe to write to disk."""
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[^\w.\-() ]", "_", name)
    return name.strip()[:200] or "attachment"


def _is_bank_sender(from_header: str) -> bool:
    from_lower = from_header.lower()
    return any(kw in from_lower for kw in _BANK_SENDERS)


def _matches_subject(subject: str, keywords: list[str]) -> bool:
    subject_lower = subject.lower()
    return any(kw.lower() in subject_lower for kw in keywords)


class FetchResult:
    """Summary of a single account's fetch run."""

    def __init__(self, account_name: str) -> None:
        self.account_name = account_name
        self.emails_scanned = 0
        self.emails_new = 0
        self.attachments_downloaded = 0
        self.errors: list[str] = []

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"FetchResult({self.account_name!r}: "
            f"scanned={self.emails_scanned} new={self.emails_new} "
            f"files={self.attachments_downloaded} errors={len(self.errors)})"
        )


class ImapClient:
    """Downloads bank statement attachments from a single IMAP account."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        use_ssl: bool = True,
        folders: list[str] | None = None,
        subject_keywords: list[str] | None = None,
        lookback_days: int = 365,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self._folders = folders or ["INBOX"]
        self._subject_keywords = subject_keywords or [
            "extracto", "estado de cuenta", "resumen de cuenta", "bank statement"
        ]
        self._lookback_days = lookback_days

    # ── Connection ────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _connect(self):  # type: ignore[return]
        """Return an authenticated imapclient.IMAPClient."""
        import imapclient  # noqa: PLC0415

        client = imapclient.IMAPClient(
            self._host,
            port=self._port,
            ssl=self._use_ssl,
        )
        client.login(self._username, self._password)
        logger.debug("Connected to %s as %s", self._host, self._username)
        return client

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch(
        self,
        dest_dir: Path,
        processed_repo,  # ProcessedEmailRepository
        account_name: str,
    ) -> FetchResult:
        """Scan all configured folders and download new attachments.

        Args:
            dest_dir:        Directory to write downloaded files into.
            processed_repo:  Repository to check / record processed message IDs.
            account_name:    Human-readable label for logging.

        Returns:
            FetchResult with counts per outcome.
        """
        result = FetchResult(account_name)
        dest_dir.mkdir(parents=True, exist_ok=True)

        try:
            client = self._connect()
        except Exception as exc:
            msg = f"[{account_name}] Cannot connect to {self._host}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        try:
            for folder in self._folders:
                self._process_folder(client, folder, dest_dir, processed_repo, result, account_name)
        finally:
            try:
                client.logout()
            except Exception:
                pass

        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    def _process_folder(
        self,
        client,
        folder: str,
        dest_dir: Path,
        processed_repo,
        result: FetchResult,
        account_name: str,
    ) -> None:
        from datetime import date, timedelta

        try:
            client.select_folder(folder, readonly=True)
        except Exception as exc:
            logger.warning("[%s] Cannot open folder %r: %s", account_name, folder, exc)
            result.errors.append(f"Folder {folder!r}: {exc}")
            return

        # Build search criteria: SINCE date + HASATTACHMENT (if server supports it)
        since = date.today() - timedelta(days=self._lookback_days)
        since_str = since.strftime("%d-%b-%Y")  # IMAP date format: 01-Jan-2025

        try:
            # First try with keyword filter
            uids = client.search(["SINCE", since_str, "HASATTACHMENT"])
        except Exception:
            # HASATTACHMENT not supported by all servers — fall back
            try:
                uids = client.search(["SINCE", since_str])
            except Exception as exc:
                logger.error("[%s] Search failed in %r: %s", account_name, folder, exc)
                result.errors.append(f"Search in {folder!r}: {exc}")
                return

        logger.info(
            "[%s] Folder %r: %d message(s) since %s",
            account_name, folder, len(uids), since_str,
        )

        for uid in uids:
            self._process_message(
                client, uid, dest_dir, processed_repo, result, account_name
            )

    def _process_message(
        self,
        client,
        uid: int,
        dest_dir: Path,
        processed_repo,
        result: FetchResult,
        account_name: str,
    ) -> None:
        try:
            # Fetch envelope first (cheap) to check sender/subject
            envelope_data = client.fetch([uid], ["ENVELOPE"])
            if uid not in envelope_data:
                return

            envelope = envelope_data[uid][b"ENVELOPE"]
            message_id = self._extract_message_id(envelope)

            result.emails_scanned += 1

            if processed_repo.is_processed(message_id):
                logger.debug("Already processed: %s", message_id)
                return

            # Check subject and sender before fetching full body
            subject = self._get_subject(envelope)
            sender = self._get_sender(envelope)

            is_relevant = (
                _matches_subject(subject, self._subject_keywords)
                or _is_bank_sender(sender)
            )

            if not is_relevant:
                logger.debug("Skipping non-bank email: %r from %r", subject, sender)
                processed_repo.mark_processed(account_name, message_id, subject)
                return

            # Fetch full message body
            msg_data = client.fetch([uid], ["RFC822"])
            if uid not in msg_data:
                return

            raw_bytes = msg_data[uid][b"RFC822"]
            msg = email.message_from_bytes(raw_bytes)

            saved = self._save_attachments(msg, dest_dir, subject)
            result.attachments_downloaded += len(saved)
            result.emails_new += 1

            processed_repo.mark_processed(account_name, message_id, subject)

            if saved:
                logger.info(
                    "[%s] Downloaded %d file(s) from %r (%s)",
                    account_name, len(saved), subject, sender,
                )
            else:
                logger.debug(
                    "[%s] No useful attachments in %r (%s)",
                    account_name, subject, sender,
                )

        except Exception as exc:
            msg = f"[{account_name}] Error processing uid {uid}: {exc}"
            logger.warning(msg)
            result.errors.append(msg)

    def _extract_message_id(self, envelope) -> str:
        mid = envelope.message_id
        if isinstance(mid, bytes):
            mid = mid.decode("utf-8", errors="replace")
        return (mid or "").strip("<>")

    def _get_subject(self, envelope) -> str:
        raw = envelope.subject
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return _decode_header(raw or "")

    def _get_sender(self, envelope) -> str:
        addrs = envelope.sender or envelope.from_ or []
        if not addrs:
            return ""
        addr = addrs[0]
        parts = []
        if addr.mailbox:
            parts.append(addr.mailbox.decode("utf-8", errors="replace") if isinstance(addr.mailbox, bytes) else addr.mailbox)
        if addr.host:
            parts.append(addr.host.decode("utf-8", errors="replace") if isinstance(addr.host, bytes) else addr.host)
        return "@".join(parts)

    def _save_attachments(
        self, msg: Message, dest_dir: Path, subject: str
    ) -> list[Path]:
        saved: list[Path] = []

        for part in msg.walk():
            content_disposition = part.get_content_disposition() or ""
            content_type = part.get_content_type().lower()

            # Only process attachments with useful types
            is_attachment = "attachment" in content_disposition or "inline" in content_disposition
            is_wanted_type = content_type in _WANTED_TYPES

            filename_raw = part.get_filename()
            if not filename_raw and not is_attachment:
                continue

            filename = _decode_header(filename_raw or "attachment.bin")
            ext = Path(filename).suffix.lower()

            if ext not in _WANTED_EXTENSIONS and not is_wanted_type:
                continue

            # Force .pdf extension for octet-stream with no extension
            if not ext and content_type == "application/octet-stream":
                ext = ".pdf"
                filename = filename + ext

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            safe_name = _safe_filename(filename)
            dest = dest_dir / safe_name

            # Avoid overwriting with a counter suffix
            counter = 1
            stem = Path(safe_name).stem
            while dest.exists():
                dest = dest_dir / f"{stem}_{counter}{ext}"
                counter += 1

            dest.write_bytes(payload)
            saved.append(dest)
            logger.debug("Saved attachment: %s", dest.name)

        return saved
