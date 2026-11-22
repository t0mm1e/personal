#!/bin/bash

set -x -v

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
