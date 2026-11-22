#!/bin/sh
# Seed the persistent volume with the models shipped in the image (first start only), apply DB
# migrations, then run the given command (API or discovery worker).
set -e
mkdir -p "$HAMI_DATA_DIR" "$HAMI_MODELS_DIR" "$HAMI_PROCESSED_DIR"
if [ ! -f "$HAMI_MODELS_DIR/registry.json" ]; then
  cp -r /app/backend/models/. "$HAMI_MODELS_DIR/"
  echo "seeded models into $HAMI_MODELS_DIR"
fi
python -m app.cli migrate
if [ -z "$HAMI_REVIEWER_TOKEN" ]; then
  echo "WARNING: HAMI_REVIEWER_TOKEN is empty; reviewer endpoints and the console are disabled (set it in .env)"
fi
exec "$@"
