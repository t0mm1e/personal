#!/usr/bin/env bash
# sdmove — alle aangesloten microSD's in één keer leeghalen naar
#          <BASE>/<datum>_<tijd>_<label>/      (datum+tijd = nieuwste bestand op het kaartje)
#
#   sdmove               alle kaartjes die aan de voorwaarden hieronder voldoen, één voor één
#   sdmove -j            alle kaartjes tegelijk        -j3 = hooguit drie tegelijk
#   sdmove -n            dry-run: alleen laten zien wat er zou gebeuren   (DRY=1 sdmove mag ook)
#   sdmove -s            status: wat staat er nog op de kaartjes, wat is onderbroken, wat is er net gedaan
#   sdmove [opties] MOUNT…   alleen deze mountpoints
#
# Een mount doet alleen mee als: exFAT/FAT · het apparaat er nog is · via USB · label past op
# LABEL_RE · niet groter dan MAX · (optioneel) in een lezer die op READER past.
# Zo blijft een per ongeluk aangesloten schijf met rust. Wat overgeslagen wordt, wordt gemeld.
# Alles gaat mee, ook verborgen bestanden; daarna gaan de lege mappen weg: kaartje leeg.
# Veilig: rsync kopieert eerst en haalt een bestand pas van het kaartje als de kopie klaar is.
# Na elk kaartje: sync (alles staat op schijf, exFAT schoon) en eject (umount + stop unit, lampje uit)
# als sudo dat toestaat — zie de sudoers-regel in de uitleg; anders alleen umount, en anders alleen sync.
# Een onderbroken run maakt de volgende keer dezelfde doelmap af. Log: <BASE>/sdmove.log
#
# Instellingen: hieronder, of in ~/.config/sdmove.conf (zelfde namen), of als SDMOVE_<NAAM>=… ervoor.

# https://claude.ai/chat/54a516dd-d4b1-4676-aa85-8b0e51743932

BASE=~/MicroSDs
LABEL_RE='^[A-Z_]+$'        # zo heten de kaartjes; een ander label wordt overgeslagen
MAX=1100000000000           # bytes — groter dan dit wordt overgeslagen met waarschuwing; 0 = geen limiet
READER=''                   # bv. 'Kingston' — alleen kaartjes in zo'n lezer; leeg = elke USB-lezer
                            # (de lezer staat achter elke regel in de uitvoer, daar kies je het uit)
JOBS=1                      # hoeveel kaartjes tegelijk; 0 = allemaal   (-j op de commandoregel wint)
EJECT=1                     # na afloop eject/umount proberen (lukt alleen met rechten; sync gebeurt altijd)

[[ -f ~/.config/sdmove.conf ]] && . ~/.config/sdmove.conf
BASE=${SDMOVE_BASE:-$BASE}; LABEL_RE=${SDMOVE_LABEL_RE:-$LABEL_RE}; MAX=${SDMOVE_MAX:-$MAX}
READER=${SDMOVE_READER:-$READER}; JOBS=${SDMOVE_JOBS:-$JOBS}; EJECT=${SDMOVE_EJECT:-$EJECT}
SYSFS=${SDMOVE_SYSFS:-/sys}

# sysfs-map van het USB-apparaat waar een blockdevice (sdo1) aan hangt; niets = geen USB
usbdev() { local p; p=$(readlink -f "$SYSFS/class/block/$1" 2>/dev/null) || return 0
           while [[ $p == */devices/* ]]; do [[ -f $p/idVendor ]] && { echo "$p"; return 0; }; p=${p%/*}; done; return 0; }
# leesbare naam van zo'n apparaat: "Kingston MobileLite Plus (0951:1666)"
usbname() { local m p; m=$(cat "$1/manufacturer" 2>/dev/null || true); p=$(cat "$1/product" 2>/dev/null || true)
            echo "${m:+$m }${p:-usb} ($(cat "$1/idVendor" 2>/dev/null)$(printf :)$(cat "$1/idProduct" 2>/dev/null))"; }
toobig()  { [[ -n ${1:-} ]] && (( MAX > 0 && $1 > MAX )); }
hum()     { numfmt --to=si --suffix=B "$1" 2>/dev/null || echo "$1 bytes"; }
dur()     { printf '%dm%02ds' $(( $1 / 60 )) $(( $1 % 60 )); }
bytesof() { local b; b=$(du -sb "$1" 2>/dev/null | cut -f1 || true); echo "${b:-0}"; }
running() { local p n=0; for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null && n=$((n+1)); done; echo "$n"; }

[[ ${BASH_SOURCE[0]} != "$0" ]] && return 0        # bij 'source' alleen de functies laden (tests)
set -Eeuo pipefail
trap 'echo "sdmove: gestopt door een fout op regel $LINENO" >&2' ERR
trap sync EXIT

LOG="$BASE/sdmove.log"
INFLIGHT="$BASE/.inflight"          # onthoudt de doelmap van een onderbroken run
DRY="${DRY:-0}"
TTY=0; [[ -t 1 ]] && TTY=1
CLR=''; (( TTY )) && CLR=$'\r\e[K'  # wist de voortgangsregel voordat er iets anders geprint wordt
BWLIMIT=${SDMOVE_BWLIMIT:-}          # bv. 50M: rsync afremmen (per kaartje)
STATUS=0
while [[ ${1:-} == -* ]]; do case $1 in
  -n) DRY=1 ;;
  -s) STATUS=1 ;;
  -j) JOBS=0; [[ ${2:-} =~ ^[0-9]+$ ]] && { JOBS=$2; shift; } ;;
  -j*) JOBS=${1#-j} ;;
  *) echo "onbekende optie: $1" >&2; exit 2 ;;
esac; shift; done
[[ ${1:-} == status ]] && { STATUS=1; shift; }

command -v rsync >/dev/null || { echo "rsync ontbreekt" >&2; exit 1; }
mkdir -p "$BASE" "$INFLIGHT"

status() {      # alleen kijken, niets doen: wat de kernel ziet, wat onderbroken is, wat er net klaar is
  local t dev label uuid opts rw n b key dst nd bd any=0 seen=()
  echo "Zo werkt het: elk bestand gaat van het kaartje zodra het op de NAS staat (dus niet pas aan het eind);"
  echo "eject komt na het laatste bestand van dat kaartje. Een onderbroken kaartje gaat de volgende run verder in dezelfde doelmap."
  echo; echo "— kaartjes die de kernel nu ziet —"
  while read -r t; do
    dev=$(findmnt -nM "$t" -o SOURCE 2>/dev/null || true); [[ -n $dev ]] || continue
    if [[ ! -b $dev ]]; then any=1; echo "  $t: hangende mount, kaartje is al weg (sdmove ruimt dit op)"; continue; fi
    [[ -n ${SDMOVE_ANYDIR:-} || -n $(usbdev "${dev##*/}") ]] || continue     # /boot enzo overslaan
    any=1
    label=$(findmnt -nM "$t" -o LABEL 2>/dev/null || true); uuid=$(findmnt -nM "$t" -o UUID 2>/dev/null || true)
    opts=$(findmnt -nM "$t" -o OPTIONS 2>/dev/null || true); rw=''
    [[ ,$opts, == *,ro,* ]] && rw='   LET OP: alleen-lezen geworden (I/O-fouten?) — eruit en opnieuw insteken, anders kan er niets vanaf'
    n=$(find "$t" -type f 2>/dev/null | wc -l); b=$(bytesof "$t")
    key="$INFLIGHT/${uuid:-$label}"; seen+=("${uuid:-$label}")
    if [[ -f $key ]]; then
      dst=$(<"$key"); nd=$(find "$dst" -type f 2>/dev/null | wc -l); bd=$(bytesof "$dst")
      printf '  %-12s %-16s ONDERBROKEN: nog %s bestanden (%s) op het kaartje, %s (%s) al in %s%s\n' \
             "${label:-?}" "$t" "$n" "$(hum "$b")" "$nd" "$(hum "$bd")" "${dst#"$BASE"/}" "$rw"
    elif (( n == 0 )); then printf '  %-12s %-16s leeg%s\n' "${label:-?}" "$t" "$rw"
    else printf '  %-12s %-16s %s bestanden (%s), nog niet overgezet%s\n' "${label:-?}" "$t" "$n" "$(hum "$b")" "$rw"; fi
  done < <(findmnt -n -t exfat,vfat -o TARGET 2>/dev/null || true)
  (( any )) || echo "  geen — uitgeworpen kaartjes zijn onzichtbaar tot je ze opnieuw insteekt"
  echo; echo "— onderbroken, maar het kaartje zit er nu niet in —"
  any=0
  for key in "$INFLIGHT"/*; do
    [[ -f $key ]] || continue
    [[ " ${seen[*]} " == *" ${key##*/} "* ]] && continue
    any=1; dst=$(<"$key"); nd=$(find "$dst" -type f 2>/dev/null | wc -l); bd=$(bytesof "$dst")
    echo "  ${dst#"$BASE"/}: $nd bestanden ($(hum "$bd")) staan al op de NAS; steek het kaartje er weer in en draai sdmove, dan gaat hij hier verder"
  done
  (( any )) || echo "  niets"
  echo; echo "— laatste afgeronde kaartjes (uit $LOG) —"
  { grep -E '^[0-9]{4}-' "$LOG" 2>/dev/null || true; } | tail -n 8 | sed 's/^/  /'
  [[ -s $LOG ]] || echo "  nog niets"
}
(( STATUS )) && { status; exit 0; }

if (( $# )); then
  targets=("$@")
else
  mapfile -t targets < <(findmnt -n -t exfat,vfat -o TARGET || true)
fi
(( ${#targets[@]} )) || { echo "geen kaartjes gevonden"; exit 0; }

# ---------- 1. plan: checks, en per kaartje wat er gaat gebeuren ----------
T=(); LABEL=(); DST=(); KEY=(); N=(); BYTES=(); START=(); WHERE=()
for t in "${targets[@]}"; do
  [[ -d $t && $t != / ]] || { echo "overgeslagen (geen map): $t"; continue; }

  if [[ -n ${SDMOVE_ANYDIR:-} ]]; then              # testmodus: gewone map, geen hardwarechecks
    label=$(basename "$t"); uuid=''; bytes=''; where='test'
  else
    dev=$(findmnt -nM "$t" -o SOURCE 2>/dev/null || true)
    [[ -n $dev ]] || { echo "overgeslagen (geen mountpoint): $t" >&2; continue; }
    if [[ ! -b $dev ]]; then                         # kaartje eruit getrokken, mount hangt nog: opruimen als dat mag
      if sudo -n umount "$t" 2>/dev/null || sudo -n umount -l "$t" 2>/dev/null; then echo "$t: kaartje was al weg, hangende mount opgeruimd"
      else echo "$t: kaartje is weg maar de mount hangt er nog (UGOS ruimt dat niet op)"; fi
      continue
    fi
    usb=$(usbdev "${dev##*/}")
    [[ -n $usb ]] || continue                        # geen USB (bv. /boot): stil overslaan
    where=$(usbname "$usb")
    label=$(findmnt -nM "$t" -o LABEL 2>/dev/null || true)
    uuid=$(findmnt -nM "$t" -o UUID 2>/dev/null || true)
    bytes=$(findmnt -nbM "$t" -o SIZE 2>/dev/null || true)
  fi
  if [[ ! $label =~ $LABEL_RE ]]; then
    echo "overgeslagen: label '${label:-geen}' past niet op $LABEL_RE   ($t, $where)"; continue; fi
  if toobig "$bytes"; then
    echo "overgeslagen: $(hum "$bytes") is groter dan $(hum "$MAX") — geen microSD?   ($label, $t, $where)"; continue; fi
  if [[ -n $READER && ! $where =~ $READER ]]; then
    echo "overgeslagen: niet in lezer '$READER' maar in $where   ($label, $t)"; continue; fi
  label=${label//[^[:alnum:]_-]/_}

  n=$(find "$t" -type f 2>/dev/null | wc -l || true)
  if (( n == 0 )); then
    (( DRY )) || find "$t" -mindepth 1 -type d -empty -delete 2>/dev/null || true
    echo "$label ($t): leeg"; continue
  fi
  # naam op basis van het nieuwste zichtbare bestand; alleen verborgen rommel? dan daarvan
  newest=$(find "$t" -type f -not -path '*/.*' -printf '%TY-%Tm-%Td_%TH%TM\n' 2>/dev/null | sort | tail -n1 || true)
  [[ -n $newest ]] || newest=$(find "$t" -type f -printf '%TY-%Tm-%Td_%TH%TM\n' 2>/dev/null | sort | tail -n1 || true)

  key="$INFLIGHT/${uuid:-$label}"
  if [[ -f $key ]]; then dst=$(<"$key")       # onderbroken run: zelfde doelmap afmaken
  else dst="$BASE/${newest}_${label}"; fi

  used=$(bytesof "$t"); used=${used:-0}
  printf 'plan %d: %s  %s  ->  %s   (%s bestanden, %s)   [%s]\n' "$(( ${#T[@]} + 1 ))" "$label" "$t" "${dst#"$BASE"/}" "$n" "$(hum "$used")" "$where"
  T+=("$t"); LABEL+=("$label"); DST+=("$dst"); KEY+=("$key"); N+=("$n"); BYTES+=("$used"); WHERE+=("$where")
  START+=("$([[ -d $dst ]] && bytesof "$dst" || echo 0)")
done
(( DRY )) && exit 0
(( ${#T[@]} )) || exit 0

# ---------- 2. uitvoeren ----------
move_card() {   # i quiet
  local i=$1 quiet=$2 t=${T[$1]} label=${LABEL[$1]} dst=${DST[$1]} key=${KEY[$1]} t0=$SECONDS ej='' opts
  opts=(-rt --remove-source-files --chmod=D755,F644 --log-file="$LOG")
  (( quiet )) || opts+=(--info=progress2); [[ -n $BWLIMIT ]] && opts+=(--bwlimit="$BWLIMIT")
  echo "$dst" >"$key"; mkdir -p "$dst"
  if rsync "${opts[@]}" "$t/" "$dst/"; then
    find "$t" -mindepth 1 -type d -empty -delete 2>/dev/null || true
    rm -f "$key"; sync
    if (( EJECT )) && [[ -z ${SDMOVE_ANYDIR:-} ]]; then   # eject = umount + "stop unit": lampje uit, kaartje mag eruit
      if sudo -n eject "$t" 2>/dev/null || eject "$t" 2>/dev/null; then ej=', uitgeworpen'
      else umount "$t" 2>/dev/null || sudo -n umount "$t" 2>/dev/null || true; fi
      findmnt -nM "$t" >/dev/null 2>&1 || ej=${ej:-', ge-unmount (eject lukte niet: zie sudoers)'}
    fi
    printf '%s  %s %s -> %s  (%s bestanden, %s, %s, %s)\n' "$(date '+%F %T')" "$label" "$t" "${dst#"$BASE"/}" \
           "${N[$i]}" "$(hum "${BYTES[$i]}")" "${WHERE[$i]}" "$(dur $((SECONDS-t0)))" >>"$LOG"
    printf '%s✓ %s klaar in %s%s\n' "$CLR" "$label" "$(dur $((SECONDS-t0)))" "$ej"
  else
    printf '%s✗ %s: rsync meldde fouten; doelmap onthouden, draai sdmove straks nog eens\n' "$CLR" "$label" >&2
  fi
}
monitor() {     # één regel met de voortgang van de lopende kaartjes (op een terminal ververst, anders elke minuut)
  local i line pct
  while sleep "${SDMOVE_TICK:-$(( TTY ? 5 : 60 ))}"; do
    line=''
    for i in "${!T[@]}"; do
      [[ -f ${KEY[$i]} ]] || continue
      pct=$(( ( $(bytesof "${DST[$i]}") - START[$i] ) * 100 / (BYTES[$i] > 0 ? BYTES[$i] : 1) ))
      line+="${LABEL[$i]} ${pct}%  "
    done
    [[ -n $line ]] || continue
    if (( TTY )); then printf '%s   %s' "$CLR" "$line"; else echo "   $line"; fi
  done
}

t_all=$SECONDS
(( JOBS == 0 || JOBS > ${#T[@]} )) && JOBS=${#T[@]}
if (( JOBS <= 1 )); then
  echo "— ${#T[@]} kaartje(s), één voor één (met -j tegelijk) —"
  for i in "${!T[@]}"; do
    printf '▶ %d/%d %s  (%s bestanden, %s)\n' "$((i+1))" "${#T[@]}" "${LABEL[$i]}" "${N[$i]}" "$(hum "${BYTES[$i]}")"
    move_card "$i" 0
  done
else
  echo "— $JOBS tegelijk —"
  pids=(); monitor & mon=$!
  for i in "${!T[@]}"; do
    while (( $(running) >= JOBS )); do wait -n || true; done
    move_card "$i" 1 & pids+=("$!")
  done
  wait "${pids[@]}" || true
  kill "$mon" 2>/dev/null || true; wait "$mon" 2>/dev/null || true
  printf '%s' "$CLR"
fi
tot=0; for b in "${BYTES[@]}"; do tot=$(( tot + b )); done
echo "klaar: ${#T[@]} kaartje(s), $(hum "$tot") in $(dur $((SECONDS-t_all))) — sync gedaan; lampje uit = uitgeworpen, en ook de rest mag eruit"
