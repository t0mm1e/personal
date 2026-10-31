#!/bin/bash

set -x -v

# Internxt Drive

#if [ -x "/opt/homebrew/bin/rsync" ]; then
#	RSYNC=/opt/homebrew/bin/rsync
#else
#	RSYNC=rsync
#fi
#$RSYNC --progress --exclude=.tmp.\* --times --size-only --no-owner --no-group --verbose --verbose  --recursive --info=progress ~/Movies /Users/thomas/Library/CloudStorage/InternxtDrive/
#$RSYNC --progress --exclude=.tmp.\* --times --size-only --no-owner --no-group --verbose --verbose  --recursive --info=progress ~/Documents /Users/thomas/Library/CloudStorage/InternxtDrive/
#$RSYNC --progress --exclude=.tmp.\* --times --size-only --no-owner --no-group --verbose --verbose  --recursive --info=progress ~/Downloads /Users/thomas/Library/CloudStorage/InternxtDrive/
#$RSYNC --progress --exclude=.tmp.\* --times --size-only --no-owner --no-group --verbose --verbose  --recursive --info=progress ~/Desktop /Users/thomas/Library/CloudStorage/InternxtDrive/

for map in \
	.agents \
	.antigravity \
	.aws \
	.bash_history \
	.claude \
	.codeium \
	.codex \
	.config \
	.cursor \
	.grok \
	.grokbot \
	.omi \
	.openclaw \
	.ssh \
	.zprofile \
	.zsh_history \
	.zshrc \
	Desktop \
	Documents \
	Downloads \
	Movies \
; do
	rclone sync \
		~/$map ugreen:/home/Thomas\ Mac\ Studio/Users/thomas/$map \
		--sftp-path-override "/home/t0mm2e/Thomas Mac Studio/Users/thomas/$map" \
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
done

