# Fantasy League Analyzer

A personal, non-commercial tool for analyzing my own private Yahoo Fantasy Basketball league
(8 teams, head-to-head, 9 categories).

## What it does

`yahoo_export.py` reads my league's data through the Yahoo Fantasy Sports API (read-only) and saves it
as a JSON file on my own computer. I then load that file into a private web page to:

- compare all teams' strength in each of the 9 categories,
- evaluate free-agent pickups for my team,
- explore trade ideas that help both sides.

## Data and privacy

- Read-only access: league settings, team rosters, the weekly scoreboard, available players,
  and player season stats.
- Data stays on my computer. It is not shared, published, resold, or used commercially.
- Low volume: about 30–60 API requests, run manually once or twice a week.
- API credentials and tokens are kept locally and are never committed to this repository.

## Usage

```
pip3 install requests
python3 yahoo_export.py
```

The first run creates `yahoo_config.json`; fill in your own Client ID and Client Secret.

Fantasy data provided by Yahoo Fantasy.
