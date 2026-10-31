#!/bin/bash
# CCC Move Master - Wist de bron pas na een 100% succesvolle match

set -x -v -e

EXIT_STATUS="$3"

# Alleen slopen als de CCC-transfer status code 0 (succes) teruggeeft
if [ "$EXIT_STATUS" -eq 0 ]; then
	rm /Volumes/MIC\ PRO/*.wav
	diskutil eject /Volumes/MIC\ PRO
fi

exit 0
