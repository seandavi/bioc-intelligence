# Branding: Bioconductor palette, scheme B

The SPA uses the colours from Bioconductor's official stylesheet,
<https://bioconductor.org/style/base/colors.css>, with one rule added: each metric family has
its own colour everywhere it appears. This page records the tokens, the colour code and the
contrast checks so another Bioconductor site can reuse the scheme.

Mockups from the palette review are in [`design/`](design/):
[`palette-b.html`](design/palette-b.html) / [`.png`](design/palette-b.png) is the adopted scheme.
The two rejected alternatives are:

- **A, Bioconductor light** ([html](design/palette-a.html), [png](design/palette-a.png)). Neutral
  n50 page, deep-teal header, no hero. It was the closest to the old look but had no landing
  identity.
- **C, Deep teal dark** ([html](design/palette-c.html), [png](design/palette-c.png)). Dark p500
  dashboard. It had the highest contrast, but every chart and badge would need a dark variant,
  and exported figures for grant documents need a white background.

## Palette tokens

Tailwind (`frontend/tailwind.config.js`) defines only these colours in `theme.colors`, plus
Tailwind's `red` for error states. Key `300` is the unsuffixed base step in colors.css (for
example `--primary`).

| Token | Hex | colors.css step | Where used |
|---|---|---|---|
| `primary-50` | `#ebf4f7` | `--primary-p50` | page background, repo badges, teal chips, table heads |
| `primary-75` | `#add2dd` | `--primary-p75` | card and table borders; "Intelligence" wordmark and snapshot stamp on the header |
| `primary-100` | `#8bc0cf` | `--primary-p100` | chart category ramp |
| `primary-200` | `#59a5bb` | `--primary-p200` | chart category ramp |
| `primary-300` | `#3792ad` | `--primary` | (defined, unused) |
| `primary-400` | `#035771` | `--primary-p400` | header, links, buttons, active preset pill, `--metric-pubs` text |
| `primary-500` | `#003242` | `--primary-p500` | button hover, nav hover, hero scrim, translucent hero cards |
| `secondary-50` | `#f3fae9` | `--secondary-s50` | (defined, unused) |
| `secondary-75` | `#cfe9a6` | `--secondary-s75` | biocViews chip background |
| `secondary-100` | `#bbe081` | `--secondary-s100` | biocViews chip hover |
| `secondary-200`–`300` | `#9ed34a`, `#8aca25` | `--secondary-s200`, `--secondary` | (defined, unused) |
| `secondary-400` | `#618d1a` | `--secondary-s400` | (defined, unused) |
| `secondary-500` | `#547b17` | `--secondary-s500` | `--metric-usage` text; favicon gradient end |
| `secondary-600` | `#3f5d10` | *derived* (scheme-B mockup) | biocViews chip text |
| `warning-50` | `#fef9eb` | `--warning-w50` | (defined, unused) |
| `warning-300` | `#f1c736` | `--warning` | `--metric-grants-fill` |
| `warning-400`, `500` | `#a98b26`, `#937921` | `--warning-w400`, `--warning-w500` | (defined; not used for text, see below) |
| `neutral-50` | `#f9f9f9` | `--neutral-n50` | table row hover, expanded rows, grant report panel |
| `neutral-75` | `#e7e8ea` | `--neutral-n75` | row dividers, code and method pills, bar tracks, era band in charts |
| `neutral-100` | `#a1a6b3` | `--neutral-n100` | input and button borders; chart category ramp |
| `neutral-200` | `#797f92` | `--neutral-n200` | bars for counts with no metric family (packages, biocViews terms); InfoDot ring |
| `neutral-300` | `#5d657c` | `--neutral` | muted text (labels, captions, footer), `--metric-people-fill` |
| `neutral-400` | `#414757` | `--neutral-n400` | secondary text, section headings, chart titles, `--metric-people` text |
| `neutral-500` | `#393e4c` | `--neutral-n500` | strong secondary text, tooltips, code block |
| `ink` | `#070707` | `--default-body` | body text, page headings, uncoded stat values |
| `brand-teal` | `#0087af` | `--gradient-brand` stop 1 | focus rings, `--metric-pubs-fill` |
| `brand-green` | `#18a603` | `--gradient-brand` stop 3 | `--metric-usage-fill` |
| *(derived)* | `#7d671c` | `--warning-w500` darkened 15% | `--metric-grants` text |

The chart category ramp (`CATEGORY` in `components/charts.ts`) is `#035771, #8bc0cf, #5d657c,
#59a5bb, #a1a6b3`. It colours nominal series such as repositories and compared packages. It
uses only teal and slate steps so that no category looks like a metric colour.

## Semantic metric colours

Each metric family has one colour on every surface: stat cards (a 4px top border and the
value), table columns, chart series, profile section headings and badges. A reader who learns
the code once can then read any page by colour.

| Family | Covers | Text (`--metric-*`) | Fill (`--metric-*-fill`) |
|---|---|---|---|
| `pubs` | publications, citations, RCR | `#035771` | `#0087af` |
| `usage` | downloads, distinct IPs, usage rank | `#547b17` | `#18a603` |
| `grants` | NIH awards, ICs, funding | `#7d671c` | `#f1c736` |
| `people` | maintainers, authors, ORCID coverage | `#414757` | `#5d657c` |

- The CSS variables are defined in `frontend/src/index.css`.
- The Tailwind utilities are `text-metric-pubs`, `border-t-metric-pubs-fill` and so on.
- Vega specs use `METRIC` in `components/charts.ts`, which holds the fill hexes.
- `StatCard` and the package-profile `Section` take a `metric` prop.
- Counts with no metric family (packages, biocViews terms, releases) stay uncoded: `ink`
  values and `neutral-200` bars.

Each family needs two shades because the bright fills do not reach 4.5:1 as text. The fills
are used only for bars, lines and borders. Text uses the darker shade.

The amber text colour is derived. colors.css's darkest amber, w500 `#937921`, is only 4.20:1 on
white, so grant figures use w500 darkened 15% (`#7d671c`, 5.48:1). A main-site adoption should
make the same adjustment or add a w600 step.

`usage` text is 4.97:1 on white but only 4.46:1 on the `#ebf4f7` page background. Metric text is
therefore placed only on white or `neutral-50` surfaces (cards and tables), never directly on
the page. For the same reason, table row hover uses `neutral-50`, not `primary-50`.

## Gradient rule

`--gradient-brand` (`linear-gradient(to right, #0087af, #0484a9, #18a603)`) appears **only in
the landing hero** on By the Numbers (`.hero-brand` in `index.css`). Every other page has the
plain dark-teal header and no gradient.

White text on the raw gradient fails 4.5:1 (4.13 at `#0087af`, 3.23 at `#18a603`). The hero
therefore lays a 30% `#003242` (p500) scrim over the exact brand gradient. That gives effective
stops of `#006e8e`, `#036b8a` and `#118316`, with white at 5.80, 6.04 and 4.90:1. The entry cards
are p500 at 25% opacity with a 40% white border, not translucent white: white-translucent cards
lighten the band and drop below 4.5:1. Measured at the card backgrounds, white text is
7.18–7.40:1 on teal and 6.34:1 on green.

The favicon uses a p400 → s500 gradient (`#035771` → `#547b17`) behind a white "Bi". These are
the darker brand steps, so the glyph stays legible (8.06 / 4.97:1).

## Links, chips and buttons

- **Links:** `primary-400` `#035771`, underlined in running text (footer, inline prose) and on
  hover in tables. The spec's `#0087af` is 4.13:1 on white and 3.70:1 on the page, so it is used
  only for focus rings and fills.
- **Buttons:** solid `primary-400` with white text, `primary-500` on hover. White on `#0087af`
  would be 4.13:1.
- **Chips:** biocViews chips are green-tinted (`secondary-75` background, `secondary-600`
  text). Repo badges and generic chips (filters, vignettes, compared packages) are
  teal-tinted (`primary-50` / `primary-400`).
- **Header:** `primary-400` background, white wordmark, `primary-50` nav text. The active tab is
  a white pill with `primary-400` text, hover is `primary-500`, and the snapshot stamp is
  `primary-75`.

## Type and spacing (unchanged)

- System UI sans-serif stack (`ui-sans-serif, system-ui, …`).
- Headings: `text-2xl font-semibold`. Section labels: `text-sm uppercase tracking-wide`.
- Stat values: `text-3xl font-semibold tabular-nums`.
- Cards: `rounded-xl`, 1px border, `p-4`/`p-5`, `shadow-sm`.
- Layout: `max-w-6xl` centred with `px-6`.
- Chart titles: 13px in `neutral-400`.
- Charts keep Vega-Lite's default white background, so PNG/SVG exports drop cleanly into
  documents.

## Contrast results

WCAG 2 relative-luminance ratios. Body and small text need ≥ 4.5:1.

| Foreground | Background | Ratio | Use |
|---|---|---|---|
| `#070707` ink | white / `#ebf4f7` | 20.14 / 18.05 | body text |
| `#5d657c` n300 | white / `#ebf4f7` / `#f9f9f9` / `#e7e8ea` | 5.80 / 5.20 / 5.51 / 4.73 | muted text |
| `#414757` n400 | white / `#ebf4f7` / `#e7e8ea` | 9.28 / 8.31 / 7.57 | secondary text, pills |
| `#035771` p400 | white / `#ebf4f7` / `#add2dd` | 8.06 / 7.22 / 5.00 | links, badges, pubs text |
| white / `#ebf4f7` | `#035771` p400 | 8.06 / 7.22 | header, nav, buttons |
| `#add2dd` p75 | `#035771` p400 | 5.00 | wordmark, snapshot stamp |
| `#547b17` s500 | white / `#f9f9f9` | 4.97 / 4.72 | usage text |
| `#7d671c` (derived) | white / `#f9f9f9` | 5.48 / 5.21 | grants text |
| `#3f5d10` | `#cfe9a6` / `#bbe081` | 5.70 / 5.06 | biocViews chips (rest / hover) |
| white | hero after scrim (`#006e8e` … `#118316`) | 5.80 – 4.90 | hero text |
| `#f9f9f9` / white | `#393e4c` n500 | 10.14 / 10.67 | code block, tooltips |
| `#b91c1c` red-700 | white / `#ebf4f7` | 6.47 / 5.80 | error messages |

These colour pairs fail and are not used for text: `#0087af` on white (4.13), `#937921` on
white (4.20), `#797f92` n200 on white (3.99), `#547b17` on `#ebf4f7` (4.46), and white on raw
`#18a603` (3.23).
