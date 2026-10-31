#!/usr/bin/env python3
"""
connector_stats.py — hoe vaak is welke connector gebruikt?

Leest een Claude-export (conversations.json) en telt per `integration_name`
(Gmail, Google Drive, Receiptor, …) hoe vaak er tool-aanroepen waren, in hoeveel
gesprekken, hoe groot de resultaten waren die terugkwamen, en wanneer.

Gebruik:
    python3 connector_stats.py conversations.json
    python3 connector_stats.py conversations.json --per-maand
    python3 connector_stats.py conversations.json --csv stats.csv --top 50

Leest alleen. Schrijft niets, behalve de optionele CSV. Alleen standaardbibliotheek.

Bij het lezen van de cijfers:
- '~tokens' is een ruwe schatting (tekens / 4) van de tekst die tool-resultaten
  teruggaven. Dat is het deel dat daarna elke beurt opnieuw meegelezen werd.
  De vaste envelop per beurt (tool-definities, handleidingen van connectors)
  staat niet in de export en zit hier dus NIET in.
- Tools zonder integration_name (web_search, artifacts, repl, …) vallen onder
  '(ingebouwd)'.
- Een grote export wordt in één keer in het geheugen geladen; even geduld.
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime


def parse_ts(value):
    """ISO-tijdstempel ('...Z' of met offset) -> datetime, anders None."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def text_len(content):
    """Aantal tekens in een tool_result-inhoud (string, lijst van blokken of dict)."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(text_len(c) for c in content)
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return len(content["text"])
        return len(json.dumps(content, ensure_ascii=False))
    return len(str(content))


def load_export(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("conversations", "chats", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    sys.exit("Onbekende structuur: verwacht een lijst van gesprekken (conversations.json).")


def new_bucket():
    return {
        "calls": 0, "results": 0, "errors": 0, "chars": 0,
        "convs": set(), "tools": Counter(), "first": None, "last": None,
    }


def collect(conversations):
    totals = {
        "convs": len(conversations), "msgs": 0, "tool_calls": 0,
        "convs_with_tools": set(), "convs_with_connectors": set(),
    }
    buckets = defaultdict(new_bucket)
    per_month = defaultdict(Counter)
    per_tool = Counter()

    for conv in conversations:
        cid = conv.get("uuid") or conv.get("id") or id(conv)
        for msg in conv.get("chat_messages") or []:
            totals["msgs"] += 1
            msg_ts = parse_ts(msg.get("created_at"))
            for item in msg.get("content") or []:
                if not isinstance(item, dict):
                    continue
                kind = item.get("type")
                if kind not in ("tool_use", "tool_result"):
                    continue
                integration = item.get("integration_name") or "(ingebouwd)"
                tool = item.get("name") or "?"
                b = buckets[integration]
                if kind == "tool_use":
                    b["calls"] += 1
                    b["tools"][tool] += 1
                    b["convs"].add(cid)
                    per_tool[(tool, integration)] += 1
                    totals["tool_calls"] += 1
                    totals["convs_with_tools"].add(cid)
                    if integration != "(ingebouwd)":
                        totals["convs_with_connectors"].add(cid)
                    ts = parse_ts(item.get("start_timestamp")) or msg_ts
                    if ts:
                        if b["first"] is None or ts < b["first"]:
                            b["first"] = ts
                        if b["last"] is None or ts > b["last"]:
                            b["last"] = ts
                        per_month[ts.strftime("%Y-%m")][integration] += 1
                else:
                    b["results"] += 1
                    b["chars"] += text_len(item.get("content"))
                    if item.get("is_error"):
                        b["errors"] += 1
    return totals, buckets, per_month, per_tool


def fmt_int(n):
    return f"{n:,}".replace(",", ".")


def fmt_date(dt):
    return dt.strftime("%Y-%m-%d") if dt else "-"


def print_table(rows, headers, align_right=()):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def line(cells):
        out = []
        for i, cell in enumerate(cells):
            s = str(cell)
            out.append(s.rjust(widths[i]) if i in align_right else s.ljust(widths[i]))
        return "  ".join(out).rstrip()

    print(line(headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(line(row))


def main():
    ap = argparse.ArgumentParser(description="Connector-statistieken uit een Claude-export.")
    ap.add_argument("export", help="pad naar conversations.json")
    ap.add_argument("--csv", help="schrijf de connector-tabel ook naar dit CSV-bestand")
    ap.add_argument("--per-maand", action="store_true", help="toon ook aanroepen per maand")
    ap.add_argument("--top", type=int, default=30, help="aantal regels per tabel (standaard 30)")
    args = ap.parse_args()

    conversations = load_export(args.export)
    totals, buckets, per_month, per_tool = collect(conversations)
    n = totals["convs"] or 1
    ranked = sorted(buckets.items(), key=lambda kv: (-kv[1]["calls"], kv[0]))

    with_tools = len(totals["convs_with_tools"])
    with_conn = len(totals["convs_with_connectors"])
    print(f"Export: {fmt_int(totals['convs'])} gesprekken, {fmt_int(totals['msgs'])} berichten, "
          f"{fmt_int(totals['tool_calls'])} tool-aanroepen.")
    print(f"Gesprekken met minstens één tool-aanroep (incl. ingebouwd): "
          f"{fmt_int(with_tools)} ({with_tools / n:.1%})")
    print(f"Gesprekken met minstens één connector-aanroep:              "
          f"{fmt_int(with_conn)} ({with_conn / n:.1%})")
    print()

    rows = []
    for name, b in ranked[:args.top]:
        top_tools = ", ".join(f"{t} ({c})" for t, c in b["tools"].most_common(3))
        rows.append([
            name, fmt_int(b["calls"]), fmt_int(len(b["convs"])), f"{len(b['convs']) / n:.1%}",
            fmt_int(b["chars"]), fmt_int(b["chars"] // 4), fmt_int(b["errors"]),
            fmt_date(b["first"]), fmt_date(b["last"]), top_tools,
        ])
    print("Per connector (gesorteerd op aanroepen):")
    print_table(
        rows,
        ["connector", "calls", "gesprekken", "% gespr.", "resultaat (tekens)",
         "~tokens", "fouten", "eerste", "laatste", "meest gebruikte tools"],
        align_right={1, 2, 3, 4, 5, 6},
    )

    print()
    print("Per tool:")
    rows = [[tool, integ, fmt_int(c)] for (tool, integ), c in per_tool.most_common(args.top)]
    print_table(rows, ["tool", "connector", "calls"], align_right={2})

    if args.per_maand and per_month:
        print()
        print("Per maand (top-8 connectors):")
        cols = [name for name, _ in ranked[:8]]
        rows = []
        for month in sorted(per_month):
            c = per_month[month]
            rows.append([month] + [fmt_int(c.get(col, 0)) for col in cols] + [fmt_int(sum(c.values()))])
        print_table(rows, ["maand"] + cols + ["totaal"], align_right=set(range(1, len(cols) + 2)))

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["connector", "calls", "gesprekken", "pct_gesprekken", "resultaat_tekens",
                        "tokens_schatting", "fouten", "eerste", "laatste", "tools"])
            for name, b in ranked:
                w.writerow([
                    name, b["calls"], len(b["convs"]), round(len(b["convs"]) / n * 100, 2),
                    b["chars"], b["chars"] // 4, b["errors"],
                    b["first"].isoformat() if b["first"] else "",
                    b["last"].isoformat() if b["last"] else "",
                    "; ".join(f"{t}:{c}" for t, c in b["tools"].most_common()),
                ])
        print(f"\nCSV geschreven: {args.csv}")


if __name__ == "__main__":
    main()
