#!/usr/bin/env bash
# Pre-reboot validation for Ragnar on Raspberry Pi. Abort reboot on failure.
# Logging: /var/log/ragnar_health.log (requires root for write; falls back to stderr-only if not writable)

set -uo pipefail

readonly RAGNAR_DIR="/home/ragnar/Ragnar"
readonly RAGNAR_SCRIPTS="${RAGNAR_DIR}/scripts"
readonly LOG_FILE="/var/log/ragnar_health.log"
readonly MIN_DISK_KB_AVAILABLE="${RAGNAR_MIN_DISK_KB:-51200}"

log_line() {
  local msg="$1"
  local ts
  ts="$(date -Is 2>/dev/null || date)"
  if touch "$LOG_FILE" 2>/dev/null && [[ -w "$LOG_FILE" ]]; then
    printf '%s %s\n' "$ts" "$msg" >>"$LOG_FILE"
  fi
  printf '%s %s\n' "$ts" "$msg"
}

fail() {
  local reason="$1"
  log_line "PRE_REBOOT_CHECK FAIL: $reason"
  echo "ABORT: $reason" >&2
  exit 1
}

pass() {
  log_line "PRE_REBOOT_CHECK PASS: $1"
}

log_line "PRE_REBOOT_CHECK starting"

# --- System ---
if ! df -Pk / >/dev/null 2>&1; then
  fail "df / failed (filesystem not accessible)"
fi
avail_kb="$(df -Pk / | awk 'NR==2 {print $4}')"
if [[ -z "${avail_kb:-}" ]] || ! [[ "$avail_kb" =~ ^[0-9]+$ ]]; then
  fail "Could not parse available disk space on / (df output unexpected)"
fi
if (( avail_kb < MIN_DISK_KB_AVAILABLE )); then
  fail "Insufficient disk space on /: ${avail_kb} KiB available (minimum ${MIN_DISK_KB_AVAILABLE} KiB)"
fi
pass "disk space on / OK (${avail_kb} KiB available)"

if ! touch /tmp/.ragnar_pre_reboot_rw_test 2>/dev/null; then
  fail "/tmp not writable (root filesystem read-only or permission)"
fi
rm -f /tmp/.ragnar_pre_reboot_rw_test
pass "/tmp writable"

# --- Directories ---
for d in "$RAGNAR_DIR" "${RAGNAR_DIR}/config" "${RAGNAR_DIR}/data"; do
  if [[ ! -d "$d" ]]; then
    fail "Required directory missing: $d"
  fi
done
pass "Ragnar directories exist"

# --- Python ---
if [[ ! -x /usr/bin/python3 ]]; then
  fail "/usr/bin/python3 missing or not executable"
fi
pass "python3 present"

# --- Self-test (imports, config, syntax) ---
SELFTEST="${RAGNAR_SCRIPTS}/ragnar_startup_selftest.py"
if [[ ! -f "$SELFTEST" ]]; then
  fail "Missing script: $SELFTEST"
fi
# Do not prefix RAGNAR_DIR=... here: RAGNAR_DIR is readonly above and bash errors on reassignment.
# ragnar_startup_selftest.py defaults RAGNAR_DIR to /home/ragnar/Ragnar.
if ! /usr/bin/python3 "$SELFTEST"; then
  fail "ragnar_startup_selftest.py reported errors (see stderr above)"
fi
pass "ragnar_startup_selftest.py OK"

# --- Entry point file ---
if [[ ! -f "${RAGNAR_DIR}/Ragnar.py" ]] && [[ ! -f "${RAGNAR_DIR}/headlessRagnar.py" ]]; then
  fail "Neither Ragnar.py nor headlessRagnar.py found under ${RAGNAR_DIR}"
fi
pass "Ragnar entrypoint file present"

# --- Config files ---
for f in "${RAGNAR_DIR}/config/shared_config.json" "${RAGNAR_DIR}/config/actions.json"; do
  if [[ ! -f "$f" ]]; then
    fail "Required config missing: $f"
  fi
done
pass "shared_config.json and actions.json present"

# --- systemd unit ---
UNIT="/etc/systemd/system/ragnar.service"
if [[ ! -f "$UNIT" ]]; then
  fail "systemd unit missing: $UNIT"
fi
if ! grep -q "ExecStart=.*${RAGNAR_DIR}" "$UNIT" 2>/dev/null; then
  fail "ragnar.service ExecStart does not reference ${RAGNAR_DIR} (drift or wrong install)"
fi
if ! grep -q "WorkingDirectory=${RAGNAR_DIR}" "$UNIT" 2>/dev/null; then
  fail "ragnar.service WorkingDirectory is not ${RAGNAR_DIR}"
fi
pass "ragnar.service paths match ${RAGNAR_DIR}"

if command -v systemd-analyze >/dev/null 2>&1; then
  if ! out="$(systemd-analyze verify "$UNIT" 2>&1)"; then
    fail "systemd-analyze verify $UNIT failed: $out"
  fi
  pass "systemd-analyze verify ragnar.service OK"
else
  pass "systemd-analyze not available (skipped)"
fi

# --- Service state ---
if systemctl is-enabled ragnar >/dev/null 2>&1; then
  pass "ragnar.service is enabled"
else
  fail "ragnar.service is not enabled (systemctl is-enabled ragnar)"
fi

if systemctl is-failed ragnar >/dev/null 2>&1; then
  st="$(systemctl is-failed ragnar 2>/dev/null || true)"
  fail "ragnar.service is in failed state: $st (fix before reboot: journalctl -u ragnar -b --no-pager)"
fi
pass "ragnar.service not in failed state"

# --- Network (interface or default route; Pi OS may rename wlan0) ---
if ip route show default 2>/dev/null | grep -q .; then
  pass "default IPv4 route present"
elif ip link show wlan0 >/dev/null 2>&1 || ip link show eth0 >/dev/null 2>&1; then
  pass "wlan0 or eth0 present (no default route yet — OK for pre-reboot)"
elif ip -o link show 2>/dev/null | grep -qE ': (wl|en|eth)[^:]*:'; then
  pass "network interface (wl*/en*/eth*) present"
else
  fail "No default route and no common network interface (wlan0/eth0/wl*)"
fi

# Optional: quick default-route reachability (5s max)
if gw="$(ip route show default 2>/dev/null | awk '{print $3; exit}')" && [[ -n "$gw" ]]; then
  if ping -c 1 -W 2 "$gw" >/dev/null 2>&1; then
    pass "default gateway $gw responded to ping"
  else
    log_line "PRE_REBOOT_CHECK WARN: default gateway $gw did not respond to ping (continuing)"
  fi
fi

# --- Display / SPI (when config says displayhatmini) ---
if [[ -f "${RAGNAR_DIR}/config/shared_config.json" ]] && grep -q '"displayhatmini"' "${RAGNAR_DIR}/config/shared_config.json" 2>/dev/null; then
  if [[ ! -e /dev/spidev0.0 ]] && [[ ! -e /dev/spidev0.1 ]]; then
    fail "displayhatmini in config but no /dev/spidev0.0 or /dev/spidev0.1"
  fi
  pass "SPI device node present for displayhatmini"
fi

log_line "PRE_REBOOT_CHECK completed successfully — reboot allowed"
echo "All pre-reboot checks passed. See $LOG_FILE"
exit 0
