#!/usr/bin/env bash
# Respaldo lógico de Postgres + huella de la cadena de auditoría.
#
#   ./scripts/backup.sh                 # escribe en ./backups
#   ./scripts/backup.sh /ruta/destino
#
# Deja dos archivos junto al volcado: <nombre>.audit (resultado de audit_verify(), con el hash de la cabeza) y
# <nombre>.sha256. La huella es lo que permite comprobar, después de restaurar, que la cadena de auditoría
# llegó íntegra y que nadie la reescribió: ver scripts/restore-check.sh.
#
# Variables: COMPOSE (default: docker compose -f docker-compose.yml -f docker-compose.langfuse.yml)
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose -f docker-compose.yml -f docker-compose.langfuse.yml}"
OUT="${1:-backups}"
mkdir -p "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="$OUT/eightd-$STAMP.dump"

# Formato custom (-Fc): comprimido y restaurable por partes. Sin -T el exec reserva un TTY y corrompe el binario.
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$FILE"

# Huella de la cadena en el momento del respaldo.
$COMPOSE exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -c "SELECT problem, head_hash FROM audit_verify()"' > "$FILE.audit"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$OUT" && sha256sum "$(basename "$FILE")" > "$(basename "$FILE").sha256")
fi

SIZE="$(wc -c < "$FILE" | tr -d ' ')"
if [ "$SIZE" -lt 1024 ]; then
  echo "ERROR: el volcado pesa $SIZE bytes; algo falló." >&2
  exit 1
fi
echo "Respaldo: $FILE ($SIZE bytes)"
echo "Cadena de auditoría al respaldar: $(cat "$FILE.audit")"
