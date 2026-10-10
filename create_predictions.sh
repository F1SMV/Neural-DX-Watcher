#!/bin/bash
echo "🔄 Création de prédictions..."
HOUR=$(date -u +%H)
for band in 6m 10m 20m 40m 80m; do
  for mode in FT8 CW; do
    curl -s -X POST http://localhost:8000/api/adaptive/autotest/predict.json \
      -H "Content-Type: application/json" \
      -d "{\"band\":\"$band\", \"mode\":\"$mode\", \"hour_utc\":$HOUR}" > /dev/null
    echo "✓ $band / $mode"
  done
done
echo "✅ 10 prédictions créées!"
