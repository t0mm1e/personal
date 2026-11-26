#!/bin/bash

set -x -v

# hash problems conversation:
# https://claude.ai/chat/2cfc91ec-47e0-4d61-9263-b6bc68449e2d

rclone copy \
	~/tmp/Takeout ugreen:/home/Takeout \
	--sftp-path-override "/home/t0mm2e/Takeout" \
	--exclude ".DS_Store" \
	--exclude "*.backup_*" \
	--exclude "/.inProgress.nosync/**" \
	--exclude "/Boom/**" \
	--exclude "/Infuse/**" \
	--exclude "/Loom/**" \
	--exclude "*.crdownload" \
	--exclude "*.download/**" \
	--suffix ".backup_$(date +%Y-%m-%d_%H%M)" \
	--min-age 10s \
	--links \
	--progress \
	--verbose
