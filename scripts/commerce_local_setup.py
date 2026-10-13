"""Create private local operator credentials once; never print or overwrite secrets."""
from pathlib import Path
import os
import secrets

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'.env'
if path.exists():
    print('Existing .env preserved. Operator setup already exists.')
else:
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as output:
        output.write('COMMERCE_STAFF_USERNAME=operator\nCOMMERCE_STAFF_PASSWORD='+secrets.token_urlsafe(32)+'\n')
    print('Private .env created (mode 600), username operator. Read the password locally to sign in.')
