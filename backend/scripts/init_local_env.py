"""Create a private v3-only environment; never overwrites an existing file."""
import base64
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    raise SystemExit('backend/.env already exists; left unchanged.')
content = (root / '.env.example').read_text()
content = content.replace('CHANGE_ME', secrets.token_urlsafe(36))
content = content.replace('GENERATE_RATE_KEY', secrets.token_urlsafe(48))
content = content.replace('GENERATE_CSRF_KEY', secrets.token_urlsafe(48))
content = content.replace('GENERATE_MAIL_KEY', base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
    output.write(content)
(root / 'runtime/v3/storage').mkdir(parents=True, exist_ok=True)
print('Created private v3 config with independent credentials. Configure SMTP and arXiv contact locally.')
