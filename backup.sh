#!/bin/sh
# ============================================================
#  Backup automático da base de dados (SQLite)
#  - Cópia CONSISTENTE (usa o ".backup" do SQLite, seguro mesmo
#    com a aplicação a escrever ao mesmo tempo)
#  - Comprime em .gz
#  - Rotação: apaga cópias com mais de RETENCAO_DIAS dias
# ============================================================
set -e

DB="/data/assistencias.db"
DEST="/data/backups/auto"
RETENCAO_DIAS="${RETENCAO_DIAS:-30}"
STAMP="$(date +%Y%m%d-%H%M%S)"

if [ ! -f "$DB" ]; then
  echo "[backup $(date '+%F %T')] BD nao encontrada em $DB — ignorado."
  exit 0
fi

mkdir -p "$DEST"
OUT="$DEST/assistencias-$STAMP.db"

# .backup faz uma cópia consistente da base de dados
sqlite3 "$DB" ".backup '$OUT'"
gzip -f "$OUT"
echo "[backup $(date '+%F %T')] criado: $OUT.gz"

# Rotação — apaga cópias automáticas com mais de RETENCAO_DIAS dias
find "$DEST" -name 'assistencias-*.db.gz' -type f -mtime +"$RETENCAO_DIAS" -delete
echo "[backup $(date '+%F %T')] cópias com mais de $RETENCAO_DIAS dias removidas."
