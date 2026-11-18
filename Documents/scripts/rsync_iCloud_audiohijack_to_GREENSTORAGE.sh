#!/bin/bash

set -x -v

/opt/homebrew/bin/rsync \
	--progress \
	--exclude=.tmp.\* \
	--times \
	--size-only \
	--no-owner \
	--no-group \
	--verbose \
	--verbose \
	--recursive \
	--info=progress \
		/Users/thomas/Library/Mobile\ Documents/com\~apple\~CloudDocs/Audio\ Hijack/ \
		/Volumes/personal_folder/Audio\ Hijack\ v2/
