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
# name are listed; the rest are mapped inline in lookup_student_by_code.
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

    @classmethod
    def lookup_student_by_code(cls, student_code: str, rows=None) -> dict:
        """
        Queries Google Sheets ('enrollment data' tab, A3:AB range) for matching student code.
        Replicates the findStudentByCode logic with exact production index mapping.

        Pass ``rows`` to reuse an already-fetched range: the enrolment flow
        needs the profile fields AND the class quota from the same snapshot, and
        one fetch for both keeps them consistent as well as halving the API
        calls. Quota arithmetic deliberately lives in ``students.quota_sync``,
        not here -- this class stays the raw sheet reader.

        The profile fields come from the FIRST matching row, unchanged. A code
        may legitimately appear on several rows (one per payment); the later
        ones repeat the same person, so only their class counts are additive.
        """
        logger.info(f"Initiating production-matched Sheets lookup for student_code: {student_code}")
        if rows is None:
            rows = cls.fetch_enrollment_rows()

        target_code = str(student_code).strip().lower()

        # Helper to get value at index safely
        def get_val(row, idx):
            if len(row) > idx:
                return str(row[idx]).strip()
            return ""

        for row in rows:
            # AB is index 27 (0-indexed column AB where A=0, B=1, ... Z=25, AA=26, AB=27)
            row_student_code = get_val(row, COL_STUDENT_CODE)
            if row_student_code.strip().lower() == target_code:
                # Match found! Map variables exactly to production specs
                return {
                    "student_code": row_student_code,
                    "full_name": get_val(row, 1),        # B
                    "mobile_number": get_val(row, 2),    # C
                    "email": get_val(row, 3),            # D
                    "country": get_val(row, 5),          # F
                    "state": get_val(row, 6),            # G
                    "school_name": get_val(row, 7),      # H
                    "grade": get_val(row, 8),            # I
                    "syllabus": get_val(row, 9),         # J
                    "admission_date": get_val(row, 10),  # K
                    "tutor_name": get_val(row, 21),      # V
                    "remarks": get_val(row, 25),         # Z
                }

        logger.warning(
            f"Student code '{student_code}' not found in '{ENROLLMENT_WORKSHEET}' "
            f"worksheet range {ENROLLMENT_RANGE}."
        )
        return None


