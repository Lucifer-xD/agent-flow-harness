# AFH website

https://agentflowharness.com — plain HTML/CSS/JS, no build step. Three.js draws the 3D world behind
every page; GSAP (and on the home page ScrollTrigger and Lenis) drive the motion. All from CDNs.

Design: "Luminous Light": a warm ivory page in light mode, a dark mode, white cards with soft warm
shadows, the amber to magenta gradient for accents, and Plus Jakarta Sans for display type. The 3D is
"the harness line", a single glossy line that runs through the page (`js/scene.js`). Tokens live in
`styles.css`, and `js/layout.js` adds the `.wash` backdrop behind the canvas.

## Pages

Clean addresses: nginx serves `/features` from `features.html`.

- `index.html` — home: the scroll story (`js/main.js`, `sections.css`)
- `features.html`, `models.html`, `download.html`, `changelog.html`, `404.html` — `pages.css`
- `docs.html` (getting started) and `api.html` (API reference) — `docs.css`, `js/docs.js`

Shared by every page:

- `js/layout.js` — the header, phone menu and footer (pages hold `<header data-nav>` and
  `<footer data-footer>`), entrance animations (`data-reveal`), and the current release read from
  `downloads/latest.yml` (fills `data-version`, `data-size`, `data-date`, `data-file` and the
  `data-download` links)
- `js/scene.js` — the 3D world; `js/page.js` steers it on every page but home. `<body data-scene>`
  picks the starting look, and any element with `data-scene='{"net":1}'` changes it while on screen
  (keys are listed at the top of `scene.js`)
- `styles.css` — tokens, nav, footer, buttons

## Data

- `data/providers.json` — the Models page's directory. Rebuild it when the provider catalogue or
  the bundled models.dev snapshot changes: `python scripts/website-data.py`
- `sdk/` — copies of `sdk/python/afh_sdk.py` and `sdk/js/afh.mjs`; copy them again when they change
- `changelog.html` — add each release at the top

## Preview and publish

    python scripts/preview-website.py        # http://127.0.0.1:5520/, same clean URLs as nginx

Publishing a release: copy `desktop/dist/AFH-Setup-<version>.exe` and `latest.yml` into
`downloads/` (not committed), then `powershell -ExecutionPolicy Bypass -File scripts/deploy-website.ps1`.
The app's updater reads `downloads/latest.yml`, so every installed copy picks the release up.
