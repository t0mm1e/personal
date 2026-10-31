#!/bin/bash

# https://claude.ai/chat/1b7744ad-e47d-48fa-86cc-a717e252e9a5

set -x -v

grep -o 'href="[^"#]*\.xhtml' toc.xhtml | sed 's/^href="//' | awk '!s[$0]++' \
  | xargs pandoc -f html -t gfm-raw_html --wrap=none -o YY.md
  