# personal
4THEPLANET

Persoonlijke scripts van t0mm1e, grotendeels samen met Claude geschreven. Openbaar, omdat dat kan: lezen, gebruiken, doorvertellen — ga je gang.

Scripts erin, data erbuiten: geen exports, databases, sleutels of wachtwoorden. De `.gitignore` houdt de gebruikelijke verdachten tegen.

Mapje per onderwerp. Elk script heeft bovenin een paar regels gebruiksaanwijzing.

## Inhoud

- `claude-usage/connector_stats.py` — leest een Claude-export (`conversations.json`) en telt per connector hoe vaak die is aangeroepen, in hoeveel gesprekken, hoe groot de resultaten waren en wanneer. Alleen standaardbibliotheek, leest alleen.
  `python3 claude-usage/connector_stats.py conversations.json --per-maand --csv stats.csv`
