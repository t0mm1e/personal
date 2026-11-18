#!/bin/bash

set -x -v

rclone copy \
	~/Library/Mobile\ Documents/com\~apple\~CloudDocs/Audio\ Hijack 'box:Audio Hijack' \
	--exclude ".DS_Store" \
	--exclude "*.backup_*" \
	--exclude "/.inProgress.nosync/**" \
	--exclude "/Boom/**" \
	--exclude "/Infuse/**" \
	--exclude "/Loom/**" \
	--suffix ".backup_$(date +%Y-%m-%d_%H%M)" \
	--min-age 1h \
	--links \
	--progress \
	--verbose
