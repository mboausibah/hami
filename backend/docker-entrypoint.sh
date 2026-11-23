#!/bin/sh
# First start: seed the volume with the models shipped in the image, create a reviewer token if none is set,
# apply DB migrations and load the seed indicators. Then run the given command (API or discovery worker).
set -e
mkdir -p "$HAMI_DATA_DIR" "$HAMI_MODELS_DIR" "$HAMI_PROCESSED_DIR"

# Models: copy every version shipped in the image that the volume doesn't have yet; the registry (which model
# is current) is copied only on first start so promotions made on this server are kept.
for d in /app/backend/models/*/; do
  v=$(basename "$d")
  [ -d "$HAMI_MODELS_DIR/$v" ] || cp -r "$d" "$HAMI_MODELS_DIR/$v"
done
if [ ! -f "$HAMI_MODELS_DIR/registry.json" ]; then
  cp /app/backend/models/registry.json "$HAMI_MODELS_DIR/registry.json"
  echo "seeded models into $HAMI_MODELS_DIR"
fi

# Reviewer token: use HAMI_REVIEWER_TOKEN from .env if set; otherwise generate one once and keep it in the volume.
if [ -z "$HAMI_REVIEWER_TOKEN" ]; then
  TOKEN_FILE="$HAMI_DATA_DIR/reviewer_token"
  if [ ! -s "$TOKEN_FILE" ]; then
    python -c "import secrets; print(secrets.token_urlsafe(24))" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "generated a reviewer token (see it with: docker compose exec api cat /data/reviewer_token)"
  fi
  HAMI_REVIEWER_TOKEN=$(cat "$TOKEN_FILE")
  export HAMI_REVIEWER_TOKEN
fi

python -m app.cli migrate
exec "$@"
