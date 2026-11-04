"""Validate uploads before writing into private storage. Never trust MIME headers."""
import hashlib
from pathlib import Path
from django.core.exceptions import ValidationError
from pypdf import PdfReader

MAX_PDF_BYTES = 10 * 1024 * 1024

def validate_pdf(upload):
    if upload.size > MAX_PDF_BYTES or upload.size == 0:
        raise ValidationError('Adjunte un PDF no vacío de hasta 10 MB.')
    original_name = Path(upload.name.replace('\\', '/')).name[:255]
    if Path(original_name).suffix.lower() != '.pdf':
        raise ValidationError('Solo se admiten documentos PDF.')
    upload.seek(0)
    if not upload.read(5).startswith(b'%PDF-'):
        upload.seek(0)
        raise ValidationError('El contenido del archivo no es PDF.')
    upload.seek(0)
    try:
        reader = PdfReader(upload, strict=True)
        if reader.is_encrypted or not 0 < len(reader.pages) <= 500:
            raise ValueError('PDF cifrado, vacío o demasiado extenso')
        root = reader.trailer['/Root']
        names = root.get('/Names', {})
        if hasattr(names, 'get_object'):
            names = names.get_object()
        if any(k in root for k in ('/OpenAction', '/AA')) or any(k in names for k in ('/JavaScript', '/EmbeddedFiles')):
            raise ValueError('Contenido activo')
        for page in reader.pages:
            if '/AA' in page:
                raise ValueError('Acciones de página')
            for annotation in page.get('/Annots', []):
                a = annotation.get_object()
                if '/A' in a or '/AA' in a or a.get('/Subtype') == '/FileAttachment':
                    raise ValueError('Acciones o adjuntos')
    except Exception as exc:
        raise ValidationError('PDF inválido, cifrado o con acciones/adjuntos no permitidos. Exporte una copia simple.') from exc
    finally:
        upload.seek(0)
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return {'size': upload.size, 'sha256': digest.hexdigest(), 'original_name': original_name}
