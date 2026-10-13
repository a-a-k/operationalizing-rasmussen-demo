from __future__ import annotations

import html
import math


def figure(block: dict | None, identifier: str) -> str:
    width,height=1040,610
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
         '<rect width="100%" height="100%" fill="white"/>',
         '<style>text{font-family:Arial,sans-serif;font-size:12px} .title{font-weight:bold;font-size:14px}</style>',
         f'<text x="35" y="25" class="title">Prespecified example: {html.escape(identifier)}</text>',
         '<text x="35" y="46" fill="#1967b3">Adaptive</text><text x="115" y="46" fill="#666">Unchanged control</text>']
    if not block:
        out.append('<text x="35" y="80">The prespecified pair was not received; no replacement example was selected.</text></svg>')
        return "".join(out)
    panels=[
        ("Advertising CPU ceiling",lambda w:w["allocation"]["cpu"]["ad"],None),
        ("Advertising memory ceiling (MiB)",lambda w:w["allocation"]["memory"]["ad"]/2**20,None),
        ("Advertising goodput (responses/s)",lambda w:w["advertising"]["goodput"],None),
        ("Checkout p95 (ms)",lambda w:w["checkout"]["p95_ms"],500),
        ("Advertising timely fraction",lambda w:w["advertising"]["timely_fraction"],.99),
        ("Accounting timely fraction",lambda w:w["accounting"]["timely_fraction"],.99),
    ]
    for index,(title,value,threshold) in enumerate(panels):
        col,row=index%3,index//3
        x,y=55+col*340,95+row*250
        pw,ph=280,170
        series={p:[(w["epoch"],value(w)) for w in h["observations"]
                   if value(w) is not None and math.isfinite(value(w))]
                for p,h in block["histories"].items()}
        all_values=[v for points in series.values() for _,v in points]
        low=min([0]+all_values) if threshold!=.99 else max(0,min(all_values+[.99])-.01)
        high=max(all_values+[threshold or 0,1e-6])
        high+=max((high-low)*.10,.005 if threshold==.99 else 1e-6)
        if high<=low:high=low+1
        end=max([20]+[e for points in series.values() for e,_ in points])
        px=lambda e:x+pw*e/end
        py=lambda v:y+ph-ph*(v-low)/(high-low)
        out.append(f'<text x="{x}" y="{y-18}" class="title">{html.escape(title)}</text>')
        out.append(f'<path d="M{x},{y} V{y+ph} H{x+pw}" fill="none" stroke="#555"/>')
        for tick in (0,5,10,15,20):
            out.append(f'<text x="{px(tick)-5}" y="{y+ph+18}">{tick}</text>')
        out.append(f'<text x="{x+95}" y="{y+ph+37}">Measured cycle</text>')
        for v in (low,(low+high)/2,high):
            label=f"{v:.3f}" if threshold==.99 else f"{v:.2f}" if index==0 else f"{v:.1f}"
            out.append(f'<text x="{x-48}" y="{py(v)+4}">{label}</text>')
        if threshold is not None:
            out.append(f'<path d="M{x},{py(threshold)} H{x+pw}" stroke="#ba3b20" stroke-dasharray="5 4"/>')
        for policy,points in series.items():
            color="#1967b3" if policy=="adaptive" else "#888"
            dash="" if policy=="adaptive" else ' stroke-dasharray="5 3"'
            points_text=" ".join(f"{px(e):.2f},{py(v):.2f}" for e,v in points)
            out.append(f'<polyline points="{points_text}" fill="none" stroke="{color}" stroke-width="2"{dash}/>')
    out.append("</svg>")
    return "".join(out)
