#!/usr/bin/env bash
# This script puts a SIP trunk in front of the streamed-call agent. Asterisk accepts the trunk's calls and hands each one to Talk over AudioSocket, on
# 127.0.0.1:4574. Nothing here touches the callback path, so the HTTPS callback keeps working until the number's callback is switched in the telephony
# provider's dashboard.
#
#   bash setup_sip.sh install    installs Asterisk, writes its settings, opens the SIP port to the trunk's address only and switches the agent on
#   bash setup_sip.sh status     says whether everything is up and listening, and what the last streamed calls did
#   bash setup_sip.sh selftest   makes a test call through Asterisk into the agent, with a spoken sentence played as the caller, and shows what Talk heard and said
#   bash setup_sip.sh log        shows the last lines of Asterisk's own log
#   bash setup_sip.sh doctor     shows the dialplan, the open channels and the recent lines of both logs, which is useful for finding a fault
#   bash setup_sip.sh sniff [s]  shows the SIP messages that reach this machine for s seconds (90 by default), to find out whether the trunk's call arrives at all
#   bash setup_sip.sh off        stops Asterisk, closes the ports and switches the agent off, and leaves the callback path untouched
#
# Please run it as root, with the application installed in /opt/sofa-health. That folder holds src for the code, venv for its Python and data for its files, and
# the application runs there as the systemd service sofa-health (see deploy/sofa-health.service).
set -euo pipefail

NEW=/opt/sofa-health
ENVFILE="$NEW/src/.env"
# The address of the telephony provider's SIP server. Set TRUNK_IP before running this script if your provider uses a different address.
TRUNK_IP="${TRUNK_IP:-102.223.37.68}"
RTP_FROM=10000
RTP_TO=10100
AGENT_PORT=4574
STAMP="$(date +%Y%m%d-%H%M)"
MARK="; Talk SIP trunk (written by setup_sip.sh; the earlier file is kept beside it as *.talk-backup-*)"

[[ $EUID -eq 0 ]] || { echo "Please run this script as root."; exit 1; }

# Sets one plain setting in the application's .env file, replacing any earlier line for the same name.
set_env() {
  sed -i "/^$1=/d" "$ENVFILE"; echo "$1=$2" >> "$ENVFILE"
}

# Writes one Asterisk settings file from the text on standard input, and keeps the file it replaces, once, beside it.
write_conf() {
  local f="$1"
  if [[ -f "$f" ]] && ! grep -qF "Talk SIP trunk" "$f"; then cp "$f" "$f.talk-backup-$STAMP"; fi
  { echo "$MARK"; cat; } > "$f"
}

# Opens (add) or closes (remove) the SIP and audio ports in the firewall, when ufw is active on this machine.
firewall() {
  if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    if [[ "$1" == add ]]; then
      ufw allow from "$TRUNK_IP" to any port 5060 proto udp >/dev/null
      # The trunk's audio may come from a different address than its signalling, so the audio ports are open to everyone. Asterisk ignores audio for a call that it did not set up.
      ufw allow "$RTP_FROM:$RTP_TO/udp" >/dev/null
      echo "   The firewall now allows SIP (5060/udp) from $TRUNK_IP only, and audio on $RTP_FROM-$RTP_TO/udp."
    else
      ufw delete allow from "$TRUNK_IP" to any port 5060 proto udp >/dev/null 2>&1 || true
      ufw delete allow "$RTP_FROM:$RTP_TO/udp" >/dev/null 2>&1 || true
      echo "   The SIP and audio ports are closed again in the firewall."
    fi
  else
    echo "   The ufw firewall is not active on this machine. If your provider gives you a firewall panel, please allow 5060/udp from $TRUNK_IP and $RTP_FROM-$RTP_TO/udp there."
  fi
}

install_all() {
  [[ -d "$NEW/src" ]] || { echo "The application is not in $NEW yet. Please install it there first."; exit 1; }
  echo "Step 1 of 5: Installing Asterisk, which takes a few minutes."
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq asterisk >/dev/null
  systemctl stop asterisk >/dev/null 2>&1 || true

  echo "Step 2 of 5: Writing the Asterisk settings."
  # The older SIP module would compete for port 5060, so it is switched off.
  grep -q "noload *= *chan_sip.so" /etc/asterisk/modules.conf || sed -i '/^\[modules\]/a noload = chan_sip.so' /etc/asterisk/modules.conf
  write_conf /etc/asterisk/pjsip.conf <<EOF
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:5060

[trunk]
type=endpoint
transport=transport-udp
context=from-trunk
disallow=all
allow=alaw
allow=ulaw
direct_media=no
rtp_symmetric=yes
force_rport=yes
trust_id_inbound=yes

; The trunk is recognised by the address that its calls come from.
[trunk-address]
type=identify
endpoint=trunk
match=$TRUNK_IP
EOF
  write_conf /etc/asterisk/rtp.conf <<EOF
[general]
rtpstart=$RTP_FROM
rtpend=$RTP_TO
strictrtp=yes
EOF
  # AudioSocket carries no caller id of its own, so the caller's digits are written into the call's id, right-aligned in 32 places and filled with zeros.
  write_conf /etc/asterisk/extensions.conf <<EOF
[from-trunk]
exten => _.,1,NoOp(a call for Talk)
 same => n,Answer()
 same => n,Set(DIGITS=\${FILTER(0-9,\${CALLERID(num)})})
 same => n,Set(PADDED=00000000000000000000000000000000\${DIGITS})
 same => n,Set(ID=\${PADDED:-32})
 same => n,Set(CALLID=\${ID:0:8}-\${ID:8:4}-\${ID:12:4}-\${ID:16:4}-\${ID:20:12})
 same => n,Log(NOTICE,talk: call \${CALLID} goes to the agent)
 same => n,AudioSocket(\${CALLID},127.0.0.1:$AGENT_PORT)
 same => n,Log(NOTICE,talk: call \${CALLID} is over)
 same => n,Hangup()

; The two contexts below can only be reached from this machine, by "setup_sip.sh selftest", and never from the trunk. The first is the Talk side of the call, as if
; the trunk had sent it. The second is the caller's side: one sound file that is quiet through the greeting, then holds the sentence, then is quiet again.
[selftest]
exten => 1,1,Set(CALLERID(num)=+2348055550000)
 same => n,Goto(from-trunk,self,1)

[selftest-caller]
exten => caller,1,Log(NOTICE,talk selftest: the caller side is up)
 same => n,Playback(talk/selftest)
 same => n,Log(NOTICE,talk selftest: the sound ended: \${PLAYBACKSTATUS})
 same => n,Hangup()
EOF
  write_conf /etc/asterisk/logger.conf <<EOF
[general]
dateformat=%F %T

[logfiles]
console => notice,warning,error
messages => notice,warning,error
EOF
  chown -R asterisk:asterisk /etc/asterisk 2>/dev/null || true

  echo "Step 3 of 5: Opening the ports."
  firewall add

  echo "Step 4 of 5: Starting Asterisk and switching the agent on."
  systemctl enable asterisk >/dev/null 2>&1
  systemctl restart asterisk
  set_env SIP_ENABLED true
  set_env SIP_PORT "$AGENT_PORT"
  chown sofa:sofa "$ENVFILE"
  systemctl restart sofa-health
  sleep 6

  echo "Step 5 of 5: Checking that everything is up."
  status_all
  echo
  echo "The next step is to run: bash setup_sip.sh selftest"
}

status_all() {
  echo "   Asterisk is $(systemctl is-active asterisk)."
  echo "   $(asterisk -rx 'module show like audiosocket' 2>/dev/null | grep -c 'Running' || true) of the 3 AudioSocket modules (res_, app_ and chan_) are running."
  asterisk -rx 'pjsip show endpoints' 2>/dev/null | grep -E "Endpoint:|Identify" | sed 's/^/   /' || true
  echo "   $(ss -lun | grep -c ':5060') SIP port(s) are listening, and $(ss -ltn | grep -c ":$AGENT_PORT ") listener(s) are on the agent port $AGENT_PORT."
  echo "   The agent's log holds $(journalctl -u sofa-health -n 200 --no-pager 2>/dev/null | grep -c 'streamed calls: listening') start line(s)."
  echo "   These are the last streamed calls:"
  journalctl -u sofa-health --no-pager 2>/dev/null | grep -E "streamed (call|turn)" | tail -8 | sed 's/^/     /' || true
}

selftest() {
  [[ "$(systemctl is-active asterisk)" == active ]] || { echo "Asterisk is not running. Please run: bash setup_sip.sh install"; exit 1; }
  # The test sound must be where Asterisk looks for sounds, which on Ubuntu is /usr/share/asterisk/sounds and not /var/lib. So Asterisk is asked first, and otherwise the first folder that exists is used.
  local data sounds since
  data="$(asterisk -rx 'core show settings' 2>/dev/null | grep -i -E 'data +dir' | head -1 | sed 's/^[^:]*: *//' | tr -d '[:space:]')"
  [[ -n "$data" && -d "$data" ]] || data="$(for d in /usr/share/asterisk /var/lib/asterisk; do [[ -d "$d/sounds" ]] && { echo "$d"; break; }; done)"
  sounds="${data:-/var/lib/asterisk}/sounds/talk"
  install -d -o sofa -g asterisk -m 775 "$sounds"
  rm -f "$sounds"/selftest.*
  echo "   The test sound is being written to $sounds."
  since="$(date +%s)"
  (cd "$NEW/src" && SELFTEST_SOUNDS="$sounds" sudo -E -u sofa "$NEW/venv/bin/python" -m scripts.sip_selftest make "$@")
  echo "Now the script is calling Talk through Asterisk."
  asterisk -rx "channel originate Local/1@selftest/n extension caller@selftest-caller" | sed 's/^/   /'
  if ! (cd "$NEW/src" && SELFTEST_SINCE="$since" sudo -E -u sofa "$NEW/venv/bin/python" -m scripts.sip_selftest result); then
    diagnose
    return 1
  fi
  echo
  echo "This is the timing of that call from the agent's log, in milliseconds after the caller stopped speaking."
  { journalctl -u sofa-health --no-pager --since "3 min ago" 2>/dev/null | grep -E "streamed turn" | sed 's/^.*INFO:sofa.sip://' | sed 's/^/   /'; } || true
}

# Shows the SIP messages that arrive on port 5060 while a call is made, to find out whether the trunk's call reaches this machine at all.
sniff() {
  command -v tcpdump >/dev/null 2>&1 || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tcpdump >/dev/null
  echo "Listening for SIP on port 5060 for ${1:-90} seconds. Please make the call now."
  timeout "${1:-90}" tcpdump -nn -A -s0 -l -i any udp port 5060 2>/dev/null | grep -E "^[0-9:.]+ IP |^INVITE |^SIP/2.0 |^From: |^To: |^User-Agent: " | cut -c1-160 || true
  echo "Listening has finished."
}

diagnose() {
  echo
  echo "---- This is what Asterisk and the agent say, to help find the fault. ----"
  echo "The dialplan:"; asterisk -rx 'dialplan show selftest' 2>&1 | head -8 | sed 's/^/   /'
  asterisk -rx 'dialplan show selftest-caller' 2>&1 | head -6 | sed 's/^/   /' || true
  echo "The channels that are open now:"; asterisk -rx 'core show channels' 2>&1 | head -8 | sed 's/^/   /'
  echo "The Asterisk log (the files are: $(ls /var/log/asterisk 2>/dev/null | tr '\n' ' ')):"
  { tail -n 25 /var/log/asterisk/messages 2>/dev/null | cut -c1-220 | sed 's/^/   /'; } || true
  echo "The last 12 lines of Asterisk in the system journal:"
  { journalctl -u asterisk --no-pager -n 12 2>/dev/null | cut -c1-200 | sed 's/^/   /'; } || true
  echo "The last 20 lines of the agent's log about streamed calls and errors:"
  { journalctl -u sofa-health --no-pager -n 400 2>/dev/null | grep -E "streamed|sofa.sip|Traceback|Error" | tail -20 | cut -c1-240 | sed 's/^/   /'; } || true
}

case "${1:-}" in
  install) install_all ;;
  status) status_all ;;
  selftest) shift; selftest "$@" ;;
  log) tail -n 60 /var/log/asterisk/messages 2>/dev/null || journalctl -u asterisk -n 60 --no-pager ;;
  doctor) diagnose ;;
  sniff) shift; sniff "$@" ;;
  off)
    systemctl disable --now asterisk >/dev/null 2>&1 || true
    firewall remove
    set_env SIP_ENABLED false; chown sofa:sofa "$ENVFILE"; systemctl restart sofa-health
    echo "Streamed calls are now off. The callback path was not touched." ;;
  *) echo "Usage: bash setup_sip.sh install|status|selftest|log|doctor|sniff|off"; exit 2 ;;
esac
