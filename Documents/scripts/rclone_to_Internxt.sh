#!/bin/bash

# https://claude.ai/chat/7ebe12c2-e1a1-4335-b8c6-9043bb818e19
# https://claude.ai/chat/2cfc91ec-47e0-4d61-9263-b6bc68449e2d

set -x -v

MAPS="Movies Documents Desktop Downloads"

for map in $MAPS; do
	rclone sync \
		~/$map internxt:$map \
                --exclude ".DS_Store" \
                --exclude "*.backup_*" \
                --exclude "/.inProgress.nosync/**" \
                --exclude "/Boom/**" \
                --exclude "/Infuse/**" \
                --exclude "/Loom/**" \
		--exclude "*.crdownload" \
		--exclude "*.download/**" \
                --suffix ".backup_$(date +%Y-%m-%d_%H%M)" \
                --min-age 1m \
                --min-size 1B \
                --links \
		--progress \
		--verbose
done
