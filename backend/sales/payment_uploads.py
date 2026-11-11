"""Payment proof uses the existing private media storage, never a public file URL."""
from django.conf import settings

from .payments import refusal


def validate_proof(upload):
    if not upload.size or upload.size > settings.PAYMENT_PROOF_MAX_BYTES:
        raise refusal('INVALID_PROOF', 'The receipt must be non-empty and within the configured upload limit.')
    head = upload.read(16)
    upload.seek(0)
    if head.startswith(b'%PDF-'):
        return 'application/pdf', '.pdf'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png', '.png'
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg', '.jpg'
    if head.startswith(b'RIFF') and head[8:12] == b'WEBP':
        return 'image/webp', '.webp'
    raise refusal('INVALID_PROOF', 'Upload a PDF, PNG, JPEG or WebP receipt. Active content is not accepted.')
