- `claude-usage/connector_stats.py` — leest een Claude-export (`conversations.json`) en telt per connector hoe vaak die is aangeroepen, in hoeveel gesprekken, hoe groot de resultaten waren en wanneer. Alleen standaardbibliotheek, leest alleen.
  `python3 claude-usage/connector_stats.py conversations.json --per-maand --csv stats.csv`
