"""Gmail API client — downloads bank statement attachments via OAuth2.

Flow:
1. On first run, opens the browser for the user to authorize access.
   The authorization URL is printed to the console in case the browser
   doesn't open automatically.
2. After authorization, a token is saved to config/gmail_token.json.
3. Subsequent runs use the saved token (auto-refreshed when expired).
4. Emails already processed are tracked in the DB by message ID.

Discovery mode (--discover flag):
   Scans emails and prints unique senders/subjects without downloading,
   so you can inspect what patterns exist before committing to a full fetch.
"""

from __future__ import annotations

import base64
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Search query sent to Gmail API — very broad, we filter in Python
# after seeing what the user's inbox looks like.
_BASE_QUERY = "has:attachment"

_WANTED_EXTENSIONS = {".pdf", ".xlsx", ".xls"}

# Known bank sender patterns (substring match, case-insensitive)
_BANK_SENDER_HINTS = [
    "bancolombia",
    "falabella",
    "scotiabank",
    "davibank",
    "davivienda",
    "colpatria",
    "nequi",
    "bbva",
    "itau",
    "occidente",
    "bogota",
    "popular",
    "extracto",
    "mensajeria@",
    "notificaciones@",
    "tarjeta",
]

# Subject keywords that indicate a bank statement
_SUBJECT_HINTS = [
    "extracto",
    "estado de cuenta",
    "resumen de cuenta",
    "movimientos",
    "factura",
    "cobro",
]


def _looks_like_bank(sender: str, subject: str) -> bool:
    s = (sender + " " + subject).lower()
    return (
        any(h in s for h in _BANK_SENDER_HINTS)
        or any(h in s for h in _SUBJECT_HINTS)
    )


def _safe_filename(name: str) -> str:
    import unicodedata
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[^\w.\-() ]", "_", name)
    return name.strip()[:200] or "attachment"


class GmailFetchResult:
    def __init__(self, account_name: str) -> None:
        self.account_name = account_name
        self.emails_scanned = 0
        self.emails_new = 0
        self.attachments_downloaded = 0
        self.errors: list[str] = []
        # Discovery mode results
        self.discovered: list[dict] = []   # [{sender, subject, date, has_pdf}]


class GmailClient:
    """Downloads bank statement PDFs from a Gmail account using the Gmail API."""

    def __init__(
        self,
        credentials_path: Path,
        token_path: Path,
        *,
        account_name: str = "gmail",
        since_year: int = 2022,
    ) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._account_name = account_name
        self._since_year = since_year

    # ── Auth ─────────────────────────────────────────────────────────────────

    def _get_service(self):
        """Return an authorized Gmail API service, triggering OAuth2 if needed."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None

        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._token_path), _SCOPES
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing Gmail token...")
                creds.refresh(Request())
            else:
                if not self._credentials_path.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials not found: {self._credentials_path}\n"
                        "Download OAuth2 credentials from Google Cloud Console and "
                        "save them as config/gmail_credentials.json"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_path), _SCOPES
                )
                logger.info(
                    "\n"
                    "=== Autorizacion Gmail requerida ===\n"
                    "Se va a abrir el navegador. Si no abre automaticamente,\n"
                    "copia la URL que aparece abajo y pegala en tu navegador.\n"
                    "Selecciona tu cuenta %s y haz clic en 'Permitir'.\n",
                    self._account_name,
                )
                creds = flow.run_local_server(port=0, open_browser=True)

            self._token_path.write_text(creds.to_json(), encoding="utf-8")
            logger.info("Token guardado en %s", self._token_path)

        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    # ── Public API ────────────────────────────────────────────────────────────

    def discover(self) -> GmailFetchResult:
        """Scan emails and return metadata without downloading anything.

        Use this first to understand what bank emails exist in the inbox.
        """
        result = GmailFetchResult(self._account_name)
        service = self._get_service()

        query = f"{_BASE_QUERY} after:{self._since_year}/01/01"
        logger.info("[%s] Discovery scan — query: %r", self._account_name, query)

        messages = self._list_all_messages(service, query)
        logger.info("[%s] Found %d messages with attachments", self._account_name, len(messages))

        seen_patterns: set[str] = set()
        for msg_id in messages:
            try:
                meta = service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()

                headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
                sender = headers.get("From", "")
                subject = headers.get("Subject", "")
                date = headers.get("Date", "")

                result.emails_scanned += 1

                if _looks_like_bank(sender, subject):
                    key = f"{sender}|||{subject[:60]}"
                    if key not in seen_patterns:
                        seen_patterns.add(key)
                        result.discovered.append({
                            "sender": sender,
                            "subject": subject,
                            "date": date,
                        })

            except Exception as exc:
                result.errors.append(f"msg {msg_id}: {exc}")

        return result

    def fetch(
        self,
        dest_dir: Path,
        processed_repo,
        *,
        sender_filter: list[str] | None = None,
        subject_filter: list[str] | None = None,
    ) -> GmailFetchResult:
        """Download PDF attachments from bank-related emails.

        Args:
            dest_dir:       Where to save downloaded files.
            processed_repo: DB repo to track processed message IDs.
            sender_filter:  If set, only emails whose From contains one of these.
            subject_filter: If set, only emails whose Subject contains one of these.
        """
        result = GmailFetchResult(self._account_name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        service = self._get_service()

        # Build a targeted Gmail search query
        query_parts = [f"after:{self._since_year}/01/01", "has:attachment"]
        if subject_filter:
            subject_clause = " OR ".join(f'subject:"{kw}"' for kw in subject_filter)
            query_parts.append(f"({subject_clause})")
        query = " ".join(query_parts)

        logger.info("[%s] Fetching — query: %r", self._account_name, query)
        messages = self._list_all_messages(service, query)
        logger.info("[%s] %d candidate messages", self._account_name, len(messages))

        for msg_id in messages:
            self._process_message(
                service, msg_id, dest_dir, processed_repo, result,
                sender_filter=sender_filter,
            )

        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    def _list_all_messages(self, service, query: str) -> list[str]:
        """Return all message IDs matching the query (handles pagination)."""
        ids = []
        page_token = None
        while True:
            kwargs = {"userId": "me", "q": query, "maxResults": 500}
            if page_token:
                kwargs["pageToken"] = page_token
            resp = service.users().messages().list(**kwargs).execute()
            for m in resp.get("messages", []):
                ids.append(m["id"])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    def _process_message(
        self,
        service,
        msg_id: str,
        dest_dir: Path,
        processed_repo,
        result: GmailFetchResult,
        sender_filter: list[str] | None,
    ) -> None:
        try:
            # Check if already processed
            if processed_repo.is_processed(msg_id):
                return

            result.emails_scanned += 1

            # Fetch metadata first (cheap)
            meta = service.users().messages().get(
                userId="me", id=msg_id, format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()

            headers = {
                h["name"]: h["value"]
                for h in meta.get("payload", {}).get("headers", [])
            }
            sender = headers.get("From", "")
            subject = headers.get("Subject", "")

            # Apply sender filter if specified
            if sender_filter:
                if not any(f.lower() in sender.lower() for f in sender_filter):
                    if not _looks_like_bank(sender, subject):
                        processed_repo.mark_processed(self._account_name, msg_id, subject)
                        return

            if not _looks_like_bank(sender, subject):
                processed_repo.mark_processed(self._account_name, msg_id, subject)
                return

            # Fetch full message
            full_msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            saved = self._download_attachments(service, full_msg, dest_dir)
            result.attachments_downloaded += len(saved)
            result.emails_new += 1
            processed_repo.mark_processed(self._account_name, msg_id, subject)

            if saved:
                logger.info(
                    "[%s] %d PDF(s) de: %s | %s",
                    self._account_name, len(saved), sender[:40], subject[:50],
                )

        except Exception as exc:
            err = f"[{self._account_name}] msg {msg_id}: {exc}"
            logger.warning(err)
            result.errors.append(err)

    def _download_attachments(
        self, service, message: dict, dest_dir: Path
    ) -> list[Path]:
        saved: list[Path] = []

        def _walk_parts(parts: list) -> None:
            for part in parts:
                # Recurse into multipart
                sub = part.get("parts")
                if sub:
                    _walk_parts(sub)
                    continue

                filename = part.get("filename", "")
                if not filename:
                    continue

                ext = Path(filename).suffix.lower()
                mime = part.get("mimeType", "").lower()

                is_pdf = ext == ".pdf" or "pdf" in mime
                is_sheet = ext in {".xlsx", ".xls"} or "spreadsheet" in mime or "excel" in mime
                if not (is_pdf or is_sheet):
                    continue

                body = part.get("body", {})
                attachment_id = body.get("attachmentId")
                data = body.get("data")

                if attachment_id:
                    att = service.users().messages().attachments().get(
                        userId="me",
                        messageId=message["id"],
                        id=attachment_id,
                    ).execute()
                    data = att.get("data", "")

                if not data:
                    continue

                file_bytes = base64.urlsafe_b64decode(data + "==")
                safe_name = _safe_filename(filename)
                dest = dest_dir / safe_name

                counter = 1
                stem = Path(safe_name).stem
                while dest.exists():
                    dest = dest_dir / f"{stem}_{counter}{ext}"
                    counter += 1

                dest.write_bytes(file_bytes)
                saved.append(dest)

        payload = message.get("payload", {})
        parts = payload.get("parts") or [payload]
        _walk_parts(parts)
        return saved
