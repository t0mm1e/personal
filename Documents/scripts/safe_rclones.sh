#!/bin/sh

set -x -v

./rclone_to_BRAVESTORAGE.sh
#./rclone_Takeout_to_BRAVESTORAGE.sh
./rclone_to_Internxt.sh
./rclone_Takeout_to_Internxt.sh
