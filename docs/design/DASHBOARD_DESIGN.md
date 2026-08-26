# DESIGN.md — SASE Governance Dashboard Design System

> Input format compatible with agents/designer_agent.py (DESIGNER_SYSTEM).
> The dashboard's CSS implements these tokens exactly.

## Brand Direction
Dual-tone governance identity: **Black & Gold** = authority, decisions,
money-of-trust (sidebar, headers, decision buttons). **Blue & White** =
clarity, information, evidence (content surfaces, links, charts).

## Color Tokens
```yaml
palette:
  black-900: "#0B0B0D"   # app background, sidebar
  black-800: "#141419"   # panels, cards on dark
  black-700: "#1D1D24"   # hover surfaces
  gold-500:  "#D4AF37"   # PRIMARY accent: active nav, approve button, badges
  gold-300:  "#E8CD6E"   # gold hover
  blue-600:  "#2563EB"   # SECONDARY accent: links, info, primary actions on light
  blue-700:  "#1E40AF"   # blue hover
  white-50:  "#F8FAFC"   # content background (light surfaces)
  white-100: "#FFFFFF"   # cards
  slate-400: "#94A3B8"   # muted text on dark
  slate-600: "#475569"   # muted text on light
  danger-600:"#DC2626"   # reject / failed
  warn-500:  "#F59E0B"   # pending / blocked
  ok-500:    "#16A34A"   # passed / completed
```

## Typography
```yaml
font-family: "Segoe UI", system-ui, sans-serif
scale: { h1: 28px/700, h2: 20px/650, h3: 16px/600, body: 14px/400,
         small: 12px/400, mono: "Consolas, monospace" (ids, hashes, logs) }
```

## Spacing & Shape
```yaml
spacing-unit: 4px base (4/8/12/16/24/32)
radius: { card: 10px, button: 8px, input: 8px, badge: 999px }
shadow: { card: 0 1px 3px rgba(0,0,0,.25), pop: 0 8px 24px rgba(0,0,0,.35) }
```

## Components
- **Sidebar**: black-900 bg; items slate-400; active item gold-500 left-bar + white text.
- **Buttons**: `.btn-approve` gold-500/black text; `.btn-reject` danger-600/white;
  `.btn-primary` blue-600/white; `.btn-ghost` transparent/slate border.
- **Cards**: white-100 on white-50 content area; section headers carry a 3px gold top-border.
- **Status badges**: pill radius; running=blue, pending/blocked=warn, passed/completed=ok, failed/rejected=danger, awaiting-human=gold.
- **Tables**: dense 13px rows, sticky header, zebra on white-100/white-50.
- **Identity ribbon**: every decision action shows "Acting as <user>" in gold.
