#!/bin/sh

set -x -v -e

# https://gemini.google.com/app/fa13be535fdd6957
# https://share.gemini.google/H3dtjVh4WqKm

# https://claude.ai/chat/6ba25711-c15e-47c3-946a-879f5093ad24
# https://claude.ai/share/1c1c640a-f798-47f1-ab81-c265ef318954

for ext in avif AVIF gif GIF heic HEIC jpg JPG jpeg JPEG png PNG tif TIF tiff TIFF webp WEBP; do
	set -- *."$ext"
	[ -e "$1" ] && cp -avc "$@" Images/
#	compgen -G "*.$extension" >/dev/null && cp -avc *.$extension Images/
done

