#!/usr/bin/env bash
# This script gives the server a voice of its own. The voice is Piper, which is open source and runs on the processor, and it speaks whenever the hosted voice
# is out of credit or out of reach, so that a caller never hears silence. The hosted voice stays the first choice.
#
#   bash setup_voice.sh install    installs the package and one English voice, points the settings at it, restarts the application and speaks a test sentence
#   bash setup_voice.sh check      speaks a test sentence with the voice and shows how long it took
#
# Please run it as root, with the application installed in /opt/sofa-health. That folder holds src for the code, venv for its Python and data for its files, and
# the application runs there as the systemd service sofa-health (see deploy/sofa-health.service). The voice is a download of about 60 MB.
set -euo pipefail

NEW=/opt/sofa-health
ENVFILE="$NEW/src/.env"
# A clear British English voice is the first choice. The usual alternative is en_US-lessac-medium, and PIPER_VOICE can name any other Piper voice.
VOICE="${PIPER_VOICE:-en_GB-jenny_dioco-medium}"
FALLBACK_VOICE=en_US-lessac-medium
DIR="$NEW/data/voices"

[[ $EUID -eq 0 ]] || { echo "Please run this script as root."; exit 1; }

# Sets one plain setting in the application's .env file, replacing any earlier line for the same name.
set_env() { sed -i "/^$1=/d" "$ENVFILE"; echo "$1=$2" >> "$ENVFILE"; }

check() {
  (cd "$NEW/src" && sudo -u sofa "$NEW/venv/bin/python" -m scripts.voice_local_check)
}

install_voice() {
  [[ -d "$NEW/src" ]] || { echo "The application is not in $NEW yet. Please install it there first."; exit 1; }
  echo "Step 1 of 4: Installing the Piper package."
  "$NEW/venv/bin/pip" install --quiet piper-tts
  echo "Step 2 of 4: Downloading the voice $VOICE, which is about 60 MB."
  install -d -o sofa -g sofa "$DIR"
  if ! sudo -u sofa "$NEW/venv/bin/python" -m piper.download_voices "$VOICE" --data-dir "$DIR"; then
    echo "   That voice was not available, so $FALLBACK_VOICE is being used instead."
    VOICE="$FALLBACK_VOICE"
    sudo -u sofa "$NEW/venv/bin/python" -m piper.download_voices "$VOICE" --data-dir "$DIR"
  fi
  echo "Step 3 of 4: Pointing the settings at the voice and restarting the application."
  set_env PIPER_MODEL "$DIR/$VOICE.onnx"
  chown sofa:sofa "$ENVFILE"
  systemctl restart sofa-health
  # The application listens on port 8001 behind the web server, so it is asked whether it is ready for up to a minute.
  for i in $(seq 1 30); do curl -fsS --max-time 5 http://127.0.0.1:8001/health >/dev/null 2>&1 && break; sleep 2; done
  echo "Step 4 of 4: Speaking a test sentence."
  check
}

case "${1:-}" in
  install) install_voice ;;
  check) check ;;
  *) echo "Usage: bash setup_voice.sh install|check"; exit 2 ;;
esac
