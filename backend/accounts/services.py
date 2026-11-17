"""Date parsing retained for authorized enrollment-sheet imports."""
import logging
from datetime import datetime
from django.utils.dateparse import parse_date
logger = logging.getLogger(__name__)

def parse_admission_date(date_str):
    """
    Tries parsing a date string from Google Sheets with various formats.
    """
    if not date_str:
        return None
    
    # Clean string
    date_str = str(date_str).strip()
    
    # Try standard YYYY-MM-DD
    parsed = parse_date(date_str)
    if parsed:
        return parsed
        
    # Try other formats
    for fmt in ("%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
            
    logger.warning(f"Could not parse admission date string: '{date_str}'")
    return None
