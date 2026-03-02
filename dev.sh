#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  ElectON — Local Development Launch Script
#  Mirrors production: Redis + Celery worker + Celery beat + Django all required.
#
#  Usage:
#    chmod +x dev.sh
#    ./dev.sh              # full launch — auto-detects Solana, always starts Redis+Celery+Django
#    ./dev.sh --no-rebuild # skip 'anchor build' if already built
#    ./dev.sh --no-chain   # explicitly skip Solana validator + Anchor deploy
#
#  Prerequisites:
#    Redis must be running (brew install redis && brew services start redis)
#    PostgreSQL accessible via DATABASE_URL in .env
#    Python venv with requirements installed
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
IFS=$'\n\t'

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}✔${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✖${NC}  $*" >&2; }
info() { echo -e "${CYAN}→${NC}  $*"; }
step() { echo -e "\n${BOLD}${BLUE}━━━  $*  ━━━${NC}"; }

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROGRAM_DIR="$SCRIPT_DIR/solana-program"
IDL_DEST="$SCRIPT_DIR/apps/blockchain/contracts/electon_voting.json"
ENV_FILE="$SCRIPT_DIR/.env"
# Prefer .venv over venv (VS Code / newer convention)
if [[ -f "$SCRIPT_DIR/.venv/bin/activate" ]]; then
  VENV="$SCRIPT_DIR/.venv/bin/activate"
else
  VENV="$SCRIPT_DIR/venv/bin/activate"
fi
LEDGER_DIR="$SCRIPT_DIR/test-ledger"
LOG_DIR="$SCRIPT_DIR/logs"
VALIDATOR_LOG="$LOG_DIR/solana-validator.log"
VALIDATOR_PID_FILE="$LOG_DIR/validator.pid"
DJANGO_PORT="${DJANGO_PORT:-8001}"
REDIS_PORT="${REDIS_PORT:-6379}"

# ── PATH — add Solana + Cargo bins (must come BEFORE any solana availability check) ──
export PATH="$HOME/.local/share/solana/install/active_release/bin:$HOME/.cargo/bin:$PATH"

# ── Flags ─────────────────────────────────────────────────────────────────────
NO_CHAIN=false
NO_REBUILD=false
for arg in "$@"; do
  case "$arg" in
    --no-chain)    NO_CHAIN=true ;;
    --no-rebuild)  NO_REBUILD=true ;;
    --help|-h)
      echo "Usage: ./dev.sh [--no-chain] [--no-rebuild]"
      echo "  --no-chain     Explicitly skip Solana validator + Anchor deploy"
      echo "  --no-rebuild   Skip 'anchor build' if program is already built"
      echo ""
      echo "  Redis + Celery worker + Celery beat + PostgreSQL are ALWAYS started."
      echo "  Solana runs when tools are installed (default). Use --no-chain to skip."
      echo "  Ensure Redis is running: brew install redis && brew services start redis"
      exit 0
      ;;
  esac
done

# ── Auto-detect Solana availability ──────────────────────────────────────────
# PATH is already extended above, so command -v solana will find the CLI if installed.
SKIP_CHAIN=false
if [[ "$NO_CHAIN" == "true" ]]; then
  SKIP_CHAIN=true
  warn "--no-chain specified — skipping Solana blockchain layer"
elif ! command -v solana &>/dev/null; then
  SKIP_CHAIN=true
  warn "solana CLI not found — skipping Solana blockchain layer (install to enable)"
fi

# ── PIDs for background services ─────────────────────────────────────────────
CELERY_WORKER_PID=""
CELERY_BEAT_PID=""

# ── Trap: clean up on exit ────────────────────────────────────────────────────
cleanup() {
  echo ""
  log "Shutting down…"
  if [[ -f "$VALIDATOR_PID_FILE" ]]; then
    VPID="$(cat "$VALIDATOR_PID_FILE")"
    kill "$VPID" 2>/dev/null && log "Stopped validator (PID $VPID)" || true
    rm -f "$VALIDATOR_PID_FILE"
  fi
  if [[ -n "$CELERY_WORKER_PID" ]]; then
    kill "$CELERY_WORKER_PID" 2>/dev/null && log "Stopped Celery worker (PID $CELERY_WORKER_PID)" || true
  fi
  if [[ -n "$CELERY_BEAT_PID" ]]; then
    kill "$CELERY_BEAT_PID" 2>/dev/null && log "Stopped Celery beat (PID $CELERY_BEAT_PID)" || true
  fi
  # Kill any stray Celery children that inherited our session
  pkill -f "celery -A electon" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

mkdir -p "$LOG_DIR"

# ══════════════════════════════════════════════════════════════════════════════
#  1 — Prerequisites check
# ══════════════════════════════════════════════════════════════════════════════
step "Checking prerequisites"

check_tool() {
  local bin="$1" hint="$2"
  if ! command -v "$bin" &>/dev/null; then
    err "'$bin' not found.  $hint"
    exit 1
  fi
  log "$bin: $(command -v "$bin")  [$("$bin" --version 2>&1 | head -1)]"
}

if [[ "$SKIP_CHAIN" == "false" ]]; then
  check_tool solana  "Install: sh -c \"\$(curl -sSfL https://release.anza.xyz/stable/install)\""
  check_tool anchor  "Install: cargo install --git https://github.com/coral-xyz/anchor avm --force && avm install latest"
  check_tool rustc   "Install: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
else
  [[ "$NO_CHAIN" == "false" ]] && info "Solana layer skipped (tools not found)"
fi

check_tool redis-cli "Redis is required (mirrors production). Install: brew install redis && brew services start redis"

if [[ ! -f "$VENV" ]]; then
  err "virtualenv not found. Run: python -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
source "$VENV"
log "Python: $(python --version)"

# Check / install Solana Python packages
python -c "import solana, solders, anchorpy" 2>/dev/null || {
  warn "Installing Solana Python packages (solana solders anchorpy)…"
  pip install --quiet "solana>=0.34,<1.0" "solders>=0.21,<1.0" "anchorpy>=0.20,<1.0"
  log "Python Solana packages installed"
}
log "Python Solana packages: solana, solders, anchorpy  ✓"



# ── PostgreSQL (mandatory) ───────────────────────────────────────────────────
step "PostgreSQL"

if python - <<'PGEOF' 2>/dev/null; then
from decouple import config
import dj_database_url, psycopg2
url = config('DATABASE_URL')
cfg = dj_database_url.parse(url)
conn = psycopg2.connect(
    dbname=cfg['NAME'], user=cfg['USER'], password=cfg['PASSWORD'],
    host=cfg['HOST'], port=cfg['PORT'], sslmode='require',
    connect_timeout=10,
)
conn.close()
print('ok')
PGEOF
  log "PostgreSQL: connected  ✓"
else
  err "Cannot connect to PostgreSQL. Check DATABASE_URL in .env"
  exit 1
fi

# ── Redis (mandatory — mirrors production) ───────────────────────────────────
step "Redis"
if ! command -v redis-cli &>/dev/null; then
  err "redis-cli not found. Redis is required (mirrors production)."
  err "Install: brew install redis && brew services start redis"
  exit 1
fi
if redis-cli -p "$REDIS_PORT" ping &>/dev/null; then
  log "Redis: running on port $REDIS_PORT  ✓"
else
  info "Redis not responding — attempting to start via brew services…"
  if command -v brew &>/dev/null && brew services start redis >/dev/null 2>&1; then
    sleep 2
    if redis-cli -p "$REDIS_PORT" ping &>/dev/null; then
      log "Redis: started on port $REDIS_PORT  ✓"
    else
      err "Redis failed to start. Redis is required (mirrors production)."
      err "Start it manually: redis-server --daemonize yes"
      exit 1
    fi
  else
    err "Cannot start Redis automatically. Redis is required (mirrors production)."
    err "Run: redis-server --daemonize yes   OR   brew services start redis"
    exit 1
  fi
fi

# ══════════════════════════════════════════════════════════════════════════════
#  2 — Solana CLI keypair
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$SKIP_CHAIN" == "false" ]]; then
  step "Solana CLI keypair"

  SOLANA_KEYPAIR="$HOME/.config/solana/id.json"
  if [[ ! -f "$SOLANA_KEYPAIR" ]]; then
    warn "No keypair at $SOLANA_KEYPAIR — generating new one…"
    mkdir -p "$(dirname "$SOLANA_KEYPAIR")"
    solana-keygen new --outfile "$SOLANA_KEYPAIR" --no-bip39-passphrase --silent
    log "New keypair created"
  fi
  CLI_PUBKEY="$(solana address -k "$SOLANA_KEYPAIR")"
  log "CLI wallet:   $CLI_PUBKEY"

  # Extract Django payer pubkey from .env
  DJANGO_KEY_HEX="$(grep -E '^SOLANA_PRIVATE_KEY=' "$ENV_FILE" 2>/dev/null \
      | cut -d= -f2 | tr -d '"' || echo "")"
  DJANGO_PAYER_PUBKEY=""
  if [[ -n "$DJANGO_KEY_HEX" && "${#DJANGO_KEY_HEX}" -eq 128 ]]; then
    DJANGO_PAYER_PUBKEY="$(python - <<PYEOF 2>/dev/null || echo ""
from solders.keypair import Keypair
kp = Keypair.from_bytes(bytes.fromhex("$DJANGO_KEY_HEX"))
print(str(kp.pubkey()))
PYEOF
)"
  fi
  [[ -n "$DJANGO_PAYER_PUBKEY" ]] && log "Django payer: $DJANGO_PAYER_PUBKEY" \
    || warn "SOLANA_PRIVATE_KEY not set or invalid — Django payer won't be funded"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  3 — Start Solana test-validator
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$SKIP_CHAIN" == "false" ]]; then
  step "Solana test-validator"

  # Kill any existing validator
  if pkill -f "solana-test-validator" 2>/dev/null; then
    info "Stopped existing validator — waiting 2 s…"
    sleep 2
  fi

  info "Starting solana-test-validator (ledger: $LEDGER_DIR)…"
  solana-test-validator \
    --reset \
    --ledger "$LEDGER_DIR" \
    --log \
    >"$VALIDATOR_LOG" 2>&1 &
  VALIDATOR_PID=$!
  echo "$VALIDATOR_PID" > "$VALIDATOR_PID_FILE"
  log "Validator started (PID $VALIDATOR_PID) — log: $VALIDATOR_LOG"

  # Configure solana CLI to localnet
  solana config set \
    --url http://127.0.0.1:8899 \
    --keypair "$SOLANA_KEYPAIR" \
    --commitment confirmed \
    >/dev/null 2>&1 || true

  # Wait until RPC is ready (up to 45 s)
  info "Waiting for validator RPC…"
  RETRIES=0
  until solana cluster-version --url http://127.0.0.1:8899 &>/dev/null; do
    sleep 1
    RETRIES=$((RETRIES + 1))
    if [[ $RETRIES -ge 45 ]]; then
      err "Validator did not start in 45 s. Check: $VALIDATOR_LOG"
      exit 1
    fi
    [[ $((RETRIES % 5)) -eq 0 ]] && info "  …still waiting ($RETRIES s)"
  done
  log "Validator ready! ($(solana cluster-version --url http://127.0.0.1:8899 2>/dev/null))"

  # ── Airdrop SOL ─────────────────────────────────────────────────────────────
  step "Funding wallets"

  airdrop_to() {
    local addr="$1" label="$2"
    if solana airdrop 10 "$addr" \
        --url http://127.0.0.1:8899 \
        --commitment confirmed &>/dev/null; then
      BALANCE="$(solana balance "$addr" --url http://127.0.0.1:8899 2>/dev/null)"
      log "$label ($addr): $BALANCE"
    else
      warn "Airdrop to $label failed (may already be funded)"
    fi
  }

  airdrop_to "$CLI_PUBKEY" "CLI wallet"
  [[ -n "$DJANGO_PAYER_PUBKEY" ]] && airdrop_to "$DJANGO_PAYER_PUBKEY" "Django payer"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  4 — Build Anchor program
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$SKIP_CHAIN" == "false" ]]; then
  step "Anchor program — build"
  cd "$PROGRAM_DIR"

  KEYPAIR_FILE="$PROGRAM_DIR/target/deploy/electon_voting-keypair.json"
  ANCHOR_BUILD_LOG="$LOG_DIR/anchor-build.log"

  if [[ "$NO_REBUILD" == "false" || ! -f "$KEYPAIR_FILE" ]]; then
    info "Running 'anchor build' (this may take a few minutes on first run)…"
    # Capture output; print it; check exit code without pipefail interfering
    set +e
    anchor build >"$ANCHOR_BUILD_LOG" 2>&1
    ANCHOR_BUILD_EXIT=$?
    set -e
    # Show relevant lines
    grep -E "(Compiling|Finished|^error)" "$ANCHOR_BUILD_LOG" | tail -30 || true
    if [[ $ANCHOR_BUILD_EXIT -ne 0 ]]; then
      err "anchor build failed (exit $ANCHOR_BUILD_EXIT) — see $ANCHOR_BUILD_LOG"
      exit 1
    fi
    log "Build complete"
  else
    log "Skipping build (--no-rebuild)"
  fi

  # ── Sync program ID ──────────────────────────────────────────────────────────
  KEYPAIR_FILE="$PROGRAM_DIR/target/deploy/electon_voting-keypair.json"
  if [[ ! -f "$KEYPAIR_FILE" ]]; then
    err "Keypair not found after build: $KEYPAIR_FILE"
    exit 1
  fi

  NEW_PROGRAM_ID="$(python - <<PYEOF 2>/dev/null
import json
from solders.keypair import Keypair
with open("$KEYPAIR_FILE") as f:
    kp = Keypair.from_bytes(bytes(json.load(f)))
print(str(kp.pubkey()))
PYEOF
)"
  if [[ -z "$NEW_PROGRAM_ID" ]]; then
    err "Could not extract program ID from $KEYPAIR_FILE"
    exit 1
  fi
  log "Program keypair ID: $NEW_PROGRAM_ID"

  LIB_RS="$PROGRAM_DIR/programs/electon_voting/src/lib.rs"
  ANCHOR_TOML="$PROGRAM_DIR/Anchor.toml"

  CURRENT_ID="$(grep -oE 'declare_id!\("([^"]+)"\)' "$LIB_RS" | grep -oE '"[^"]+"' | tr -d '"' || echo "")"

  if [[ "$CURRENT_ID" != "$NEW_PROGRAM_ID" ]]; then
    info "Updating program ID in lib.rs + Anchor.toml: $NEW_PROGRAM_ID"
    # macOS-compatible in-place sed
    sed -i '' "s|declare_id!(\"[^\"]*\")|declare_id!(\"$NEW_PROGRAM_ID\")|g" "$LIB_RS"
    sed -i '' "s|electon_voting = \"[^\"]*\"|electon_voting = \"$NEW_PROGRAM_ID\"|g" "$ANCHOR_TOML"
    info "Rebuilding with updated program ID…"
    set +e
    anchor build >"$ANCHOR_BUILD_LOG" 2>&1
    ANCHOR_BUILD_EXIT=$?
    set -e
    grep -E "(Compiling|Finished|^error)" "$ANCHOR_BUILD_LOG" | tail -20 || true
    if [[ $ANCHOR_BUILD_EXIT -ne 0 ]]; then
      err "anchor rebuild failed — see $ANCHOR_BUILD_LOG"
      exit 1
    fi
    log "Rebuild complete"
  else
    log "Program ID unchanged: $NEW_PROGRAM_ID"
  fi
fi

# ══════════════════════════════════════════════════════════════════════════════
#  5 — Deploy program to localnet
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$SKIP_CHAIN" == "false" ]]; then
  step "Deploying program to localnet"
  cd "$PROGRAM_DIR"

  anchor deploy \
    --provider.cluster localnet \
    --provider.wallet "$HOME/.config/solana/id.json" \
    2>&1 | tail -20 || {
      err "anchor deploy failed"
      exit 1
    }

  log "Program deployed: $NEW_PROGRAM_ID"

  # ── Convert IDL v1 → v0 and copy to Django ───────────────────────────────────
  # Anchor 0.30+ emits IDL v1 format (writable/signer/relations/discriminator).
  # anchorpy 0.21.0 / solders 0.26.0 only understand IDL v0 (isMut/isSigner).
  # This inline converter translates v1 → v0 so Django can load the IDL.
  step "Converting IDL v1→v0 and copying to Django"
  IDL_SOURCE="$PROGRAM_DIR/target/idl/electon_voting.json"

  if [[ -f "$IDL_SOURCE" ]]; then
    python - <<PYEOF
import json, sys

src = "$IDL_SOURCE"
dst = "$IDL_DEST"
program_id = "$NEW_PROGRAM_ID"

with open(src) as f:
    v1 = json.load(f)

def convert_type(t):
    """Recursively convert v1 type refs to v0 (defined:{name:X} -> defined:X, pubkey -> publicKey)."""
    if t == "pubkey":
        return "publicKey"
    if isinstance(t, dict):
        if "defined" in t and isinstance(t["defined"], dict):
            # v1: {"defined": {"name": "Foo"}} -> v0: {"defined": "Foo"}
            return {"defined": t["defined"]["name"]}
        return {k: convert_type(v) for k, v in t.items()}
    return t

def convert_field(f):
    out = {"name": f["name"]}
    if "type" in f:
        out["type"] = convert_type(f["type"])
    return out

def convert_account_item(a):
    """Convert a v1 instruction account to v0 isMut/isSigner format."""
    out = {"name": a["name"]}
    out["isMut"] = bool(a.get("writable", False))
    out["isSigner"] = bool(a.get("signer", False))
    # Skip v1-only fields: relations, address, pda, docs, optional
    return out

def convert_instruction(ix):
    out = {"name": ix["name"]}
    out["accounts"] = [convert_account_item(a) for a in ix.get("accounts", [])]
    args = []
    for arg in ix.get("args", []):
        args.append({"name": arg["name"], "type": convert_type(arg["type"])})
    out["args"] = args
    return out

def convert_account_def(a):
    """Convert a v1 account type definition to v0."""
    out = {"name": a["name"]}
    if "type" in a:
        kind = a["type"].get("kind", "struct")
        fields = [convert_field(f) for f in a["type"].get("fields", [])]
        out["type"] = {"kind": kind, "fields": fields}
    return out

def convert_type_def(t):
    kind = t["type"].get("kind", "struct")
    fields = [convert_field(f) for f in t["type"].get("fields", [])]
    return {"name": t["name"], "type": {"kind": kind, "fields": fields}}

meta = v1.get("metadata", {})
v0 = {
    "version": meta.get("version", "0.1.0"),
    "name": meta.get("name", v1.get("name", "electon_voting")),
    "instructions": [convert_instruction(ix) for ix in v1.get("instructions", [])],
    "accounts": [convert_account_def(a) for a in v1.get("accounts", [])
                 if "type" in a],
    "types": [convert_type_def(t) for t in v1.get("types", [])],
    "errors": v1.get("errors", []),
    "metadata": {"address": program_id},
}

with open(dst, "w") as f:
    json.dump(v0, f, indent=2)
print("  IDL v0 written to", dst, "(program:", program_id + ")")
PYEOF
    log "IDL: $IDL_DEST"
  else
    warn "IDL source not found ($IDL_SOURCE) — keeping existing IDL in Django"
  fi

  # ── Update .env ──────────────────────────────────────────────────────────────
  step "Updating .env"

  update_env_var() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
      sed -i '' "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
      echo "${key}=${val}" >> "$ENV_FILE"
    fi
  }

  update_env_var "SOLANA_PROGRAM_ID"  "$NEW_PROGRAM_ID"
  update_env_var "SOLANA_RPC_URL"     "http://127.0.0.1:8899"
  update_env_var "SOLANA_NETWORK"     "localnet"

  log ".env updated  (SOLANA_PROGRAM_ID=$NEW_PROGRAM_ID)"
else
  # Chain is skipped — clear SOLANA_PROGRAM_ID so Django won't attempt deploy
  _clear_env_var() {
    local key="$1"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
      sed -i '' "s|^${key}=.*|${key}=|" "$ENV_FILE"
    fi
  }
  _clear_env_var "SOLANA_PROGRAM_ID"
  info "Cleared SOLANA_PROGRAM_ID in .env (chain skipped)"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  6 — Django setup
# ══════════════════════════════════════════════════════════════════════════════
cd "$SCRIPT_DIR"
step "Django — migrate + setup"

SETTINGS="electon.settings.development"

info "Running migrations…"
python manage.py migrate --settings="$SETTINGS" 2>&1 | tail -20
log "Migrations done"

# Auto-create superuser (admin/admin) if none exists
python - <<PYEOF
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "$SETTINGS")
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser("admin", "admin@electon.local", "admin")
    print("  ✅ Superuser created:  admin / admin")
else:
    print("  ℹ️  Superuser already exists")
PYEOF

info "Collecting static files…"
python manage.py collectstatic \
  --noinput \
  --settings="$SETTINGS" \
  --verbosity 0 || warn "collectstatic had warnings/errors — static may be served directly by Django (DEBUG=True)"
log "Static files step done"

# ══════════════════════════════════════════════════════════════════════════════
#  6b — Start Celery worker + beat (mandatory — mirrors production)
# ══════════════════════════════════════════════════════════════════════════════
step "Celery — worker + beat"

CELERY_WORKER_LOG="$LOG_DIR/celery-worker.log"
CELERY_BEAT_LOG="$LOG_DIR/celery-beat.log"
CELERY_BEAT_SCHEDULE="$LOG_DIR/celerybeat-schedule"

# Kill any stale Celery processes from a previous run
pkill -f "celery -A electon worker" 2>/dev/null || true
pkill -f "celery -A electon beat"   2>/dev/null || true
sleep 0.5

DJANGO_SETTINGS_MODULE="$SETTINGS" \
  python -m celery -A electon worker \
    --loglevel=info \
    --concurrency=2 \
    --without-gossip \
    --without-mingle \
    --without-heartbeat \
    -Q celery \
    >"$CELERY_WORKER_LOG" 2>&1 &
CELERY_WORKER_PID=$!
log "Celery worker started (PID $CELERY_WORKER_PID) — log: $CELERY_WORKER_LOG"

DJANGO_SETTINGS_MODULE="$SETTINGS" \
  python -m celery -A electon beat \
    --loglevel=info \
    --schedule="$CELERY_BEAT_SCHEDULE" \
    >"$CELERY_BEAT_LOG" 2>&1 &
CELERY_BEAT_PID=$!
log "Celery beat  started (PID $CELERY_BEAT_PID)   — log: $CELERY_BEAT_LOG"

# Verify worker actually connected before continuing
sleep 2
if ! kill -0 "$CELERY_WORKER_PID" 2>/dev/null; then
  err "Celery worker exited immediately — check $CELERY_WORKER_LOG:"
  tail -20 "$CELERY_WORKER_LOG" || true
  exit 1
fi
log "Celery worker connected to Redis  ✓"

# ══════════════════════════════════════════════════════════════════════════════
#  7 — Start ElectON
# ══════════════════════════════════════════════════════════════════════════════
step "ElectON is ready"
echo ""
echo -e "  ${BOLD}App:${NC}        http://127.0.0.1:${DJANGO_PORT}/"
echo -e "  ${BOLD}Admin:${NC}      http://127.0.0.1:${DJANGO_PORT}/admin/   (admin / admin)"
echo -e "  ${BOLD}Database:${NC}   PostgreSQL (Neon / DATABASE_URL)"
echo -e "  ${BOLD}Redis:${NC}      redis://127.0.0.1:${REDIS_PORT}"
echo -e "  ${BOLD}Worker log:${NC} $LOG_DIR/celery-worker.log"
echo -e "  ${BOLD}Beat log:${NC}   $LOG_DIR/celery-beat.log"
if [[ "$SKIP_CHAIN" == "false" ]]; then
  echo -e "  ${BOLD}Solana:${NC}     http://127.0.0.1:8899   (localnet)"
  echo -e "  ${BOLD}Program:${NC}    ${NEW_PROGRAM_ID}"
  echo -e "  ${BOLD}Val log:${NC}    $VALIDATOR_LOG"
else
  echo -e "  ${BOLD}Solana:${NC}     skipped (install solana CLI to enable)"
fi
echo -e "  ${BOLD}App log:${NC}    $LOG_DIR/electon.log"
echo ""
echo -e "  Press ${BOLD}Ctrl+C${NC} to stop all services."
echo ""

# Free the port if something is already listening (e.g. a stale dev server)
if lsof -ti:"$DJANGO_PORT" &>/dev/null; then
  warn "Port $DJANGO_PORT is in use — killing existing process…"
  lsof -ti:"$DJANGO_PORT" | xargs kill -9 2>/dev/null || true
  sleep 1
fi


DJANGO_SETTINGS_MODULE="$SETTINGS" \
  python manage.py runserver "127.0.0.1:${DJANGO_PORT}"
