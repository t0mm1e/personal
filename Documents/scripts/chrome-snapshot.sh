#!/bin/bash
# ============================================================================
#  chrome-snapshot.sh  —  klonen + ontdubbelen van het Chrome-profiel, in één stap
# ----------------------------------------------------------------------------
#  Elke run maakt onder $SNAPSHOT_ROOT een complete, zelfstandige kopie van de
#  Default-map met een tijdstempel (bijv. 2026-10-26_2107). Op APFS gebeurt dat
#  met clonefile (cp -c): de kopie deelt haar blokken met het origineel én met
#  alle eerdere snapshots, en kost alleen wat sindsdien veranderde. Het
#  "ontdubbelen met de nacht ervoor" doet het bestandssysteem dus zelf —
#  honderd snapshots kosten ongeveer één kopie plus de verschillen.
#
#  Er wordt NOOIT iets verwijderd. Retentie is aan jou en aan niemand anders.
#  Naast elke snapshot komt een tabs.txt: alle URL's uit de Sessions-map,
#  leesbaar zonder parser (superset: ook back/forward-geschiedenis per tab).
#
#  Gebruik:
#     chrome-snapshot.sh                  gewoon draaien (met kleurtjes in een terminal)
#     KEEP_CACHES=1 chrome-snapshot.sh    ook de regenereerbare caches bewaren
#     SNAPSHOT_ROOT=/pad chrome-snapshot.sh   andere bestemming (zie TCC-opmerking)
#
#  Cron (elk uur, op minuut 7 — ontdubbeld is elk uur even goedkoop als 's nachts):
#     7 * * * * /Users/thomas/bin/chrome-snapshot.sh >/dev/null 2>&1
#
#  Terugzetten (Chrome helemaal afsluiten, dan):
#     mv "$HOME/Library/Application Support/Google/Chrome/Default" \
#        "$HOME/Library/Application Support/Google/Chrome/Default.kapot-$(date +%Y%m%d-%H%M)"
#     cp -a -c ~/chrome-snapshots/2026-10-26_2107/Default \
#        "$HOME/Library/Application Support/Google/Chrome/Default"
#     (versie bewaren, nooit overschrijven — vandaar de mv.)
#
#  TCC-opmerking: bestemming staat bewust in je home en NIET in Desktop,
#  Documents, Downloads of op een externe schijf; daar komt cron zonder
#  Full Disk Access niet in, en faalt dan stil. Daarom werkte het "toen" niet.
# ============================================================================

set -uo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin   # cron geeft bijna niets mee; meer hebben we niet nodig

PROFILE="${CHROME_PROFILE:-$HOME/Library/Application Support/Google/Chrome/Default}"
ROOT="${SNAPSHOT_ROOT:-$HOME/tmp/Chrome_sessions}"
LOG="$ROOT/snapshot.log"
LATEST="$ROOT/latest"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
NEW="$ROOT/$STAMP"

# Regenereerbare caches: standaard niet bewaard (churnen hard, zijn in seconden terug).
CACHES=(
  "Code Cache" "GPUCache" "DawnCache" "DawnGraphiteCache" "DawnWebGPUCache"
  "GrShaderCache" "ShaderCache" "Service Worker/CacheStorage" "Service Worker/ScriptCache"
)

# ---- kleurtjes (alleen als er een terminal aan hangt; cron krijgt kale tekst) ----
if [ -t 1 ]; then
  B=$'\e[1m'; D=$'\e[2m'; R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; C=$'\e[36m'; M=$'\e[35m'; X=$'\e[0m'
else
  B=; D=; R=; G=; Y=; C=; M=; X=
fi
say() { printf '%s\n' "$*"; }
log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }
free_kb() { df -k "$ROOT" | awk 'NR==2 {print $4}'; }

# ---- voorbereiding ----
mkdir -p "$ROOT" || { say "${R}✗ kan $ROOT niet aanmaken${X}"; exit 1; }
if [ ! -d "$PROFILE" ]; then
  say "${R}✗ profielmap niet gevonden:${X} $PROFILE"
  log "ERROR profielmap ontbreekt: $PROFILE"
  exit 1
fi
if [ -e "$NEW" ]; then
  say "${Y}⚠ $NEW bestaat al, ik raak hem niet aan${X}"
  log "SKIP bestaat al: $NEW"
  exit 0
fi

case "$(uname -s)" in
  Darwin) CPFLAGS="-a -c" ;;    # APFS clone: kopie deelt blokken met bron en eerdere snapshots
  *)      CPFLAGS="-a"    ;;    # elders: gewone kopie (geen ontdubbeling)
esac

say "${B}${M}💾 chrome-snapshot${X} ${D}$STAMP${X}"
say "   ${D}bron${X}  $PROFILE"
say "   ${D}doel${X}  $NEW"

# ---- klonen ----
before=$(free_kb)
mkdir -p "$NEW"
ERRS="$NEW/.cp-errors.txt"
# shellcheck disable=SC2086
if cp $CPFLAGS "$PROFILE" "$NEW/Default" 2>"$ERRS"; then
  status="compleet"
  rm -f "$ERRS"
else
  # Chrome roteert bestanden onder onze handen door; een enkele miss is normaal.
  status="gedeeltelijk ($(wc -l < "$ERRS" | tr -d ' ') fout(en), zie .cp-errors.txt)"
  say "${Y}⚠ kopie gedeeltelijk:${X} $(head -3 "$ERRS")"
fi

# ---- caches uit de snapshot (niet uit het profiel!) ----
if [ "${KEEP_CACHES:-0}" != "1" ]; then
  for c in "${CACHES[@]}"; do
    [ -e "$NEW/Default/$c" ] && rm -rf "$NEW/Default/$c"
  done
  say "   ${D}caches${X} weggelaten (KEEP_CACHES=1 bewaart ze)"
else
  say "   ${D}caches${X} bewaard"
fi

# ---- tabs.txt: de sessie als leesbare lijst, zonder parser ----
if [ -d "$NEW/Default/Sessions" ]; then
  LC_ALL=C grep -ahoE 'https?://[^[:space:][:cntrl:]"<>]+' "$NEW/Default/Sessions"/* 2>/dev/null \
    | sort -u > "$NEW/tabs.txt" || true
  tabs=$(wc -l < "$NEW/tabs.txt" | tr -d ' ')
else
  tabs=0
  say "${Y}⚠ geen Sessions-map in het profiel — Chrome schrijft z'n sessie nu nergens?${X}"
fi

# ---- boekhouding ----
after=$(free_kb)
cost_kb=$(( before - after )); [ "$cost_kb" -lt 0 ] && cost_kb=0
files=$(find "$NEW/Default" -type f | wc -l | tr -d ' ')
logical=$(du -sh "$NEW/Default" 2>/dev/null | awk '{print $1}')
ln -sfn "$NEW" "$LATEST"
printf 'snapshot:  %s\nstatus:    %s\nbestanden: %s\nlogisch:   %s\necht:      %s KB (wat deze snapshot werkelijk aan schijf kostte)\ntabs.txt:  %s URLs\n' \
  "$STAMP" "$status" "$files" "$logical" "$cost_kb" "$tabs" > "$NEW/MANIFEST.txt"
log "OK $STAMP status=$status bestanden=$files logisch=$logical echt=${cost_kb}KB tabs=$tabs"

say "   ${G}✓ $status${X}  ${D}$files bestanden, logisch $logical, echt ${C}${cost_kb} KB${X}${D}, tabs.txt: ${X}${C}$tabs URLs${X}"
say "   ${D}latest →${X} $NEW"
