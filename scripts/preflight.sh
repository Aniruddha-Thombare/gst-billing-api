#!/usr/bin/env bash
# Pre-flight check before `docker compose up`. Run from the project root:  bash scripts/preflight.sh
# It NEVER prints secret values: only names, lengths and OK/FAIL. Safe to paste the output to anyone.
set -u
FAILS=0; WARNS=0
ok()   { echo "[ OK ] $*"; }
fail() { echo "[FAIL] $*"; FAILS=$((FAILS+1)); }
warn() { echo "[WARN] $*"; WARNS=$((WARNS+1)); }

echo "== 1. Docker"
if docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then ok "Docker engine is running"; else fail "Docker engine not reachable (start Docker Desktop)"; fi

echo "== 2. Files"
for f in Dockerfile docker-compose.yml .dockerignore requirements.txt alembic.ini app/main.py \
         app/routers/health.py app/services/health_service.py app/repositories/health_repository.py \
         scripts/backup_loop.sh scripts/restore_db.sh .env; do
  [ -f "$f" ] && ok "$f" || fail "$f is missing"
done
[ -d migrations ] && ok "migrations/ folder" || fail "migrations/ folder is missing"
loc=$(grep -E '^script_location' alembic.ini 2>/dev/null | tr -d '\r' | sed 's/.*= *//')
case "$loc" in
  migrations|'%(here)s/migrations') ok "alembic.ini script_location = $loc (points to migrations/)";;
  *) fail "alembic.ini script_location is '${loc:-?}', expected migrations or %(here)s/migrations";;
esac
grep -q $'\r' scripts/backup_loop.sh 2>/dev/null && fail "scripts/backup_loop.sh has Windows (CRLF) line endings - the backup container will crash" || ok "backup_loop.sh line endings are LF"

echo "== 3. .env (values are never printed)"
if [ -f .env ]; then
  envval() { sed 's/\r$//' .env | grep -E "^$1=" | head -1 | cut -d= -f2-; }
  for k in ENVIRONMENT POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB REDIS_PASSWORD JWT_SECRET_KEY ACCESS_TOKEN_EXPIRE_MINUTES DATABASE_URL REDIS_URL; do
    v=$(envval $k); [ -n "$v" ] && ok "$k is set (length ${#v})" || fail "$k is missing or empty"
  done
  for k in POSTGRES_PASSWORD REDIS_PASSWORD; do
    v=$(envval $k)
    [[ "$v" =~ ^[A-Za-z0-9]+$ ]] && ok "$k uses letters/digits only" || fail "$k contains symbols or spaces - it will break the database/Redis URL"
    [ ${#v} -ge 8 ] || warn "$k is shorter than 8 characters"
  done
  jwt=$(envval JWT_SECRET_KEY); [ ${#jwt} -ge 64 ] && ok "JWT_SECRET_KEY length ${#jwt} (needs >= 64)" || fail "JWT_SECRET_KEY length ${#jwt} (needs >= 64)"
  env_=$(envval ENVIRONMENT); [[ "$env_" =~ ^(development|production|testing)$ ]] && ok "ENVIRONMENT = $env_" || fail "ENVIRONMENT must be development, production or testing"
  pw=$(envval POSTGRES_PASSWORD); rp=$(envval REDIS_PASSWORD)
  [ "$pw" = "Root@123" ] || [ "$rp" = "Root@Ani" ] && fail "an OLD password that appeared in chat is still in .env"
  case "$(envval DATABASE_URL)" in *"@localhost:5433/"*) ok "DATABASE_URL points at the Docker DB (localhost:5433)";; *) warn "DATABASE_URL does not use localhost:5433 (only matters when running uvicorn outside Docker)";; esac
  grep -q "$pw" <<<"$(envval DATABASE_URL)" && ok "DATABASE_URL contains the current POSTGRES_PASSWORD" || warn "DATABASE_URL password differs from POSTGRES_PASSWORD (matters only outside Docker)"
fi

echo "== 4. app/main.py"
if [ -f app/main.py ]; then
  grep -q "health_router" app/main.py && ok "main.py imports/uses health_router" || fail "main.py does not use health_router (see main_py_edit.txt)"
  n=$(grep -cE '@app\.get\(\s*"/health"' app/main.py); [ "$n" = "0" ] && ok "old inline /health route is removed" || fail "old inline /health route still in main.py ($n) - it conflicts with the new router"
  for r in auth_router invoice_router payment_router; do
    c=$(grep -c "include_router($r.router" app/main.py)
    [ "$c" -le 1 ] && ok "$r included $c time(s)" || fail "$r is included $c times - delete the duplicate"
  done
fi

echo "== 5. Git safety"
if git rev-parse --git-dir >/dev/null 2>&1; then
  [ -z "$(git ls-files .env)" ] && ok ".env is not tracked by git" || fail ".env IS tracked by git - stop and ask before committing"
  git check-ignore -q .env && ok ".env is git-ignored" || fail ".env is not git-ignored"
  [ -z "$(git ls-files | grep -E '\.dump$|^backups/')" ] && ok "no database dumps tracked" || fail "database dumps are tracked by git"
fi

echo "== 6. Compose file"
# Inside Docker the database listens on 5432. 5433 is only the port published to YOUR laptop.
grep -qE '@postgres:5433' docker-compose.yml 2>/dev/null && fail "docker-compose.yml uses @postgres:5433 - inside Docker it must be @postgres:5432 (5433 is only for pgAdmin on your laptop)" || ok "container-to-container DB port is not 5433"
grep -qE '@redis:(6380|6379)' docker-compose.yml 2>/dev/null && ok "Redis URL uses host 'redis'" || warn "check REDIS_URL host in docker-compose.yml"
if docker compose config -q >/dev/null 2>/tmp/preflight_compose.err; then ok "docker compose config is valid"; else fail "docker compose config failed:"; sed 's/^/        /' /tmp/preflight_compose.err | head -8; fi
rm -f /tmp/preflight_compose.err

echo "== 7. Ports"
for p in 8000 5433 6379; do
  if (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null; then warn "port $p is already in use (stop what uses it, or it may be your own running stack)"; else ok "port $p is free"; fi
done

echo
echo "Result: $FAILS failure(s), $WARNS warning(s)."
[ $FAILS -eq 0 ] && echo "Ready: docker compose up -d --build" || echo "Fix the [FAIL] lines first."
exit $FAILS