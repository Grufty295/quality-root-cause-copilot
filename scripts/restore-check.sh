#!/usr/bin/env bash
# Prueba de restauración: restaura un volcado en una base temporal y comprueba la cadena de auditoría.
# No toca la base real. Un respaldo que nunca se restauró no es un respaldo.
#
#   ./scripts/restore-check.sh backups/eightd-20261018-220000.dump
#
# Comprueba: (1) pg_restore termina sin errores, (2) audit_verify() no reporta problemas y (3) el hash de la cabeza
# y el número de registros coinciden con los que se anotaron al respaldar (<volcado>.audit).
# Termina con código 1 si algo no coincide. Borra la base temporal al final.
set -euo pipefail

DUMP="${1:?uso: restore-check.sh <volcado.dump>}"
COMPOSE="${COMPOSE:-docker compose -f docker-compose.yml -f docker-compose.langfuse.yml}"
SCRATCH="eightd_restore_check"
EXPECTED_FILE="$DUMP.audit"
[ -f "$DUMP" ] || { echo "No existe $DUMP" >&2; exit 2; }
[ -f "$EXPECTED_FILE" ] || { echo "Falta $EXPECTED_FILE (lo escribe backup.sh)" >&2; exit 2; }

run_db() { $COMPOSE exec -T db sh -c "$1"; }

cleanup() { run_db "dropdb -U \"\$POSTGRES_USER\" --if-exists $SCRATCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT

run_db "dropdb -U \"\$POSTGRES_USER\" --if-exists $SCRATCH && createdb -U \"\$POSTGRES_USER\" $SCRATCH"
# --no-owner: la restauración no debe depender de que exista el mismo rol.
$COMPOSE exec -T db sh -c "pg_restore -U \"\$POSTGRES_USER\" -d $SCRATCH --no-owner --exit-on-error" < "$DUMP"

GOT="$(run_db "psql -U \"\$POSTGRES_USER\" -d $SCRATCH -At -F '|' -c \"SELECT problem, head_hash FROM audit_verify()\"")"
WANT="$(cat "$EXPECTED_FILE")"

echo "Al respaldar:    $WANT"
echo "Tras restaurar:  $GOT"
if [ "$GOT" != "$WANT" ]; then
  echo "FALLA: la cadena de auditoría restaurada no coincide con la del respaldo." >&2
  exit 1
fi
if echo "$GOT" | grep -vq '^registros verificados: '; then
  echo "FALLA: audit_verify() reporta problemas." >&2
  exit 1
fi
echo "OK: restauración verificada; la cadena de auditoría llegó íntegra."
