#!/bin/bash

set -x -v

rclone copy \
	~/tmp/Takeout internxt:Takeout \
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
