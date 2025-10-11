#!/bin/bash
set -e

INPUT_PATH="networks/filtered/ohare-filtered.osm.xml"
OUTPUT_DIR="data"

BASENAME=$(basename "$INPUT_PATH" .osm.xml)

# Garante que o diretório de saída existe
mkdir -p "$OUTPUT_DIR"

echo "🚀 Rodando osm2po e gerando GraphML..."
docker run --rm \
  -v "$(pwd)":/data \
  osm2po:5.5.16 \
    prefix="$BASENAME" \
    file="/data/networks/filtered/ohare-filtered.osm.xml" \
    cmd=tjsg \
    t.nw=4 \
    t.mode=car \
    t.osm2po.restrict=true \
    workDir="/data/$OUTPUT_DIR"

echo "✅ Finalizado! GraphML salvo em: $OUTPUT_DIR/${BASENAME}_2po.gph"
