from __future__ import annotations

import html
import math


BLUE = "#1864ab"
GRAY = "#777777"
PURPLE = "#862e9c"
RED = "#c92a2a"
GREEN = "#087f5b"


def series(label, color, points, dash=""):
    return {"label": label, "color": color, "points": points, "dash": dash}


def figure(title, subtitle, panels, columns=2, panel_width=540, panel_height=325):
    rows = math.ceil(len(panels) / columns)
    width, height = columns * panel_width + 40, rows * panel_height + 90
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                '<rect width="100%" height="100%" fill="white"/>',
                '<style>text{font-family:Arial,sans-serif;fill:#202020} .tick{font-size:11px} .legend{font-size:11px}</style>',
                f'<text x="24" y="28" font-size="20">{html.escape(title)}</text>',
                f'<text x="24" y="51" font-size="12">{html.escape(subtitle)}</text>']
    for index, panel in enumerate(panels):
        left = 24 + (index % columns) * panel_width
        top = 78 + (index // columns) * panel_height
        px, py, pw, ph = left + 62, top + 31, panel_width - 91, panel_height - 113
        elements.append(f'<text x="{left}" y="{top + 14}" font-size="15">{html.escape(panel["title"])}</text>')
        values = [v for s in panel["series"] for _, v in s["points"] if v is not None and math.isfinite(v)]
        if panel.get("threshold") is not None:
            values.append(panel["threshold"])
        if not values:
            elements.append(f'<text x="{px}" y="{py + 30}">No observed values</text>')
            continue
        low, high = min(values), max(values)
        padding = (high - low) * .09 or max(.01, abs(high) * .01)
        low, high = low - padding, high + padding
        if panel.get("nonnegative"):
            low = max(0., low)
        maximum_epoch = max((e for s in panel["series"] for e, _ in s["points"]), default=1) or 1
        xpos = lambda epoch: px + pw * epoch / maximum_epoch
        ypos = lambda value: py + ph * (high - value) / (high - low)
        for k in range(5):
            value = low + (high - low) * k / 4
            y = ypos(value)
            elements += [f'<line x1="{px}" y1="{y:.2f}" x2="{px + pw}" y2="{y:.2f}" stroke="#eeeeee"/>',
                         f'<text class="tick" x="{px - 6}" y="{y + 4:.2f}" text-anchor="end">{value:.4g}</text>']
        epochs = sorted({0, maximum_epoch // 4, maximum_epoch // 2, 3 * maximum_epoch // 4, maximum_epoch})
        for epoch in epochs:
            x = xpos(epoch)
            elements.append(f'<text class="tick" x="{x:.2f}" y="{py + ph + 16}" text-anchor="middle">{epoch}</text>')
        elements += [f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py + ph}" stroke="#999999"/>',
                     f'<line x1="{px}" y1="{py + ph}" x2="{px + pw}" y2="{py + ph}" stroke="#999999"/>',
                     f'<text class="tick" x="{px + pw / 2}" y="{py + ph + 31}" text-anchor="middle">Measured epoch</text>']
        if panel.get("threshold") is not None:
            y = ypos(panel["threshold"])
            elements.append(f'<line x1="{px}" y1="{y:.2f}" x2="{px + pw}" y2="{y:.2f}" stroke="{RED}" stroke-dasharray="5 4"/>')
        for i, s in enumerate(panel["series"]):
            segments, points, last = [], [], None
            for epoch, value in sorted(s["points"]):
                if value is None or not math.isfinite(value):
                    if points:
                        segments.append(points)
                    points, last = [], None
                    continue
                if last is not None and epoch != last + 1:
                    segments.append(points)
                    points = []
                points.append((xpos(epoch), ypos(value)))
                elements.append(f'<circle cx="{xpos(epoch):.2f}" cy="{ypos(value):.2f}" r="2.5" fill="{s["color"]}"><title>{html.escape(s["label"])}; epoch {epoch}; {value:.8g}</title></circle>')
                last = epoch
            if points:
                segments.append(points)
            for segment in segments:
                coordinates = " ".join(f"{x:.2f},{y:.2f}" for x, y in segment)
                elements.append(f'<polyline points="{coordinates}" fill="none" stroke="{s["color"]}" stroke-width="1.8" stroke-dasharray="{s["dash"]}"/>')
            lx, ly = left + (i % 2) * (panel_width - 15) / 2, py + ph + 52 + (i // 2) * 15
            elements += [f'<line x1="{lx}" y1="{ly - 4}" x2="{lx + 17}" y2="{ly - 4}" stroke="{s["color"]}" stroke-width="2" stroke-dasharray="{s["dash"]}"/>',
                         f'<text class="legend" x="{lx + 22}" y="{ly}">{html.escape(s["label"])}</text>']
    elements.append("</svg>\n")
    return "\n".join(elements)


def history_figure(rows, identifier):
    histories = {p: sorted((r for r in rows if r["block_id"] == identifier and r["policy"] == p), key=lambda r: r["epoch"])
                 for p in ("adaptive", "control")}
    def points(policy, key):
        return [(r["epoch"], r[key]) for r in histories[policy]]
    panels = [{"title": "Accumulated relative movement from baseline", "nonnegative": True,
               "series": [series("Full ILR norm", BLUE, points("adaptive", "relative_net_norm")),
                          series("Selected projection norm", PURPLE, points("adaptive", "local_projected_net_norm"))]}]
    for title, key, threshold in (
        ("Advertising goodput (nonempty replies/s)", "advertising_goodput", None),
        ("Checkout request p95 (ms; boundary 500)", "checkout_p95_ms", 500),
        ("Accounting timely fraction (boundary 0.99)", "accounting_timely_fraction", .99),
        ("Advertising timely fraction (boundary 0.99)", "advertising_timely_fraction", .99),
        ("Accounting observed p99 lag (ms; diagnostic)", "accounting_observed_p99_lag_ms", 5000),
    ):
        panels.append({"title": title, "nonnegative": True, "threshold": threshold,
                       "series": [series("Adaptive", BLUE, points("adaptive", key)),
                                  series("Unchanged control", GRAY, points("control", key))]})
    return figure(identifier + ": accumulated state and measured outcomes",
                  "Original fixed example. Lines join measured allocation vertices, not unobserved within-window states.", panels)


def witness_figure(blocks, witnesses):
    if not witnesses:
        return figure("Selected-history comparisons", "No equal-prefix safe/unsafe witness in these data.", [])
    first = min(witnesses, key=lambda r: (r["unsafe_epoch"], r["unsafe_block"], r["safe_block"]))
    uid, epoch = first["unsafe_block"], first["unsafe_epoch"]
    bids = [uid] + sorted({r["safe_block"] for r in witnesses if r["unsafe_block"] == uid and r["unsafe_epoch"] == epoch})
    observations = {bid: [w for w in blocks[bid]["histories"]["adaptive"]["observations"] if w["epoch"] <= epoch] for bid in bids}
    ref = observations[uid]
    labels = ("CPU checkout / payment", "CPU frontend / ad", "RAM accounting / Kafka")
    local_series = [series(labels[i], color, [(w["epoch"], w["representation"]["local"][i] - ref[0]["representation"]["local"][i]) for w in ref])
                    for i, color in enumerate((BLUE, PURPLE, GREEN))]
    full_series, slo_series = [], []
    for bid, color in zip(bids, (RED, BLUE, GREEN)):
        label = "Runner " + bid.rsplit("-", 1)[1]
        for part, name, dash in (("astronomy-db", "DB", ""), ("kafka", "Kafka", "5 3")):
            full_series.append(series(label + " " + name, color, [(w["epoch"], w["allocation"]["cpu"][part]) for w in observations[bid]], dash))
        slo_series.append(series(label, color, [(w["epoch"], w["checkout"]["p95_ms"]) for w in observations[bid]]))
    panels = [
        {"title": "Selected cumulative traces coincide", "series": local_series},
        {"title": "Differing CPU paths hidden by those traces", "nonnegative": True, "series": full_series},
        {"title": "Measured checkout p95 (ms; boundary 500)", "nonnegative": True, "threshold": 500, "series": slo_series},
    ]
    return figure("Entire selected-history collision: " + first["initial_state"] + " / " + first["profile"],
                  f"Retrospective example, baseline through epoch {epoch}. Shared unsafe runner: overlapping comparisons, not causal effects.",
                  panels, columns=3, panel_width=440, panel_height=365)
