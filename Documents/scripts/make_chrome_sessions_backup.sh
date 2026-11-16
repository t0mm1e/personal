#!/bin/bash

set -x -v 

NOW=$(date +%Y%m%d%H%M%S)

cp -aR ~/Library/Application\ Support/Google/Chrome/Default ~/tmp/Chrome_sessions/${NOW}_Default
