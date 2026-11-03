#!/bin/bash

set -x -v

if [ -z "$1" ]; then
	echo "no volume given"
	exit 1
fi

cd "/Volumes/$1"

sudo rm -Rf \
	.fseventsd \
	10_Bit_Log_Encoding.url \
	Get_started_with_GoPro.url \
	mdb* \
	DCIM/leinfo.sav \
	.Trashes

cd ..

diskutil eject "$1"
