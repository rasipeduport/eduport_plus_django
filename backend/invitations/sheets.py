import logging
import gspread
from django.conf import settings
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# The enrolment sheet as every caller reads it: one tab, one range, fetched
# whole. Rows 1-2 are headers, so the data starts at row 3.
ENROLLMENT_WORKSHEET = 'enrollment data'
ENROLLMENT_RANGE = 'A3:AB'

# Column indices inside ENROLLMENT_RANGE (A=0). Only the columns code reads by
# name are listed. The sheet is read for class quotas only (students.quota_sync):
# Learn accounts are created at enrollment, never from a sheet row.
#
# N and O are both class counts and are easy to confuse:
#   N "Actual No of classes purchased" -- what was ordered. DISPLAY ONLY; it is
#     deliberately not synced anywhere, because unpaid classes may not be spent.
#   O "No of classes paid for"         -- the usable quota (students.quota_sync).
COL_CLASSES_PURCHASED = 13
COL_CLASSES_PAID_FOR = 14
COL_STUDENT_CODE = 27


class GoogleSheetsService:
    @staticmethod
    def get_gspread_client():
        """
        Initializes and returns a gspread client using separate environment credentials.
        """
        email = getattr(settings, 'GOOGLE_SERVICE_ACCOUNT_EMAIL', '')
        private_key = getattr(settings, 'GOOGLE_PRIVATE_KEY', '')

        if not email or not private_key:
            raise ValueError(
                "GOOGLE_SERVICE_ACCOUNT_EMAIL and GOOGLE_PRIVATE_KEY must be configured in settings."
            )

        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        # Format key properly (handling escaped newlines in env variables)
        formatted_private_key = private_key.replace('\\n', '\n')

        info = {
            "type": "service_account",
            "private_key": formatted_private_key,
            "client_email": email,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        }

        try:
            credentials = Credentials.from_service_account_info(info, scopes=scopes)
            client = gspread.authorize(credentials)
            return client
        except Exception as e:
            logger.error(f"Failed to authenticate with Google Sheets: {e}")
            raise

    @classmethod
    def fetch_enrollment_rows(cls) -> list:
        """
        Every data row of the enrolment tab, as lists of raw cell strings, in
        sheet order.

        ONE API call per invocation: callers scan the result in memory rather
        than asking Google per student. Raises on any credential, transport or
        missing-tab error -- a caller that must not act on partial data (the
        quota sync) catches it and does nothing.
        """
        sheet_id = settings.GOOGLE_SHEET_ID
        if not sheet_id:
            raise ValueError("GOOGLE_SHEET_ID is not configured in settings.")

        try:
            client = cls.get_gspread_client()
            spreadsheet = client.open_by_key(sheet_id)
            worksheet = spreadsheet.worksheet(ENROLLMENT_WORKSHEET)
            return worksheet.get(ENROLLMENT_RANGE)
        except Exception as e:
            logger.error(
                f"Error accessing worksheet '{ENROLLMENT_WORKSHEET}' for sheet '{sheet_id}': {e}"
            )
            raise
