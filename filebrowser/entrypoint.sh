#!/bin/sh
set -e

DB=/database/filebrowser.db

if [ ! -f "$DB" ]; then
  echo "Initializing filebrowser database with proxy auth..."
  /bin/filebrowser config init \
    --auth.method=proxy \
    --auth.header=X-Auth-User \
    --database="$DB" \
    --root=/srv

  /bin/filebrowser users add admin "changeme-not-used" \
    --perm.admin \
    --database="$DB"
  echo "Database initialized."
fi

exec /bin/filebrowser \
  --database="$DB" \
  --root=/srv \
  --port=80 \
  --address=0.0.0.0 \
  --log=stdout
