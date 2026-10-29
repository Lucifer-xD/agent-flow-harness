# AFH website

The download page for Agent Flow Harness and its API reference: plain HTML/CSS/JS, no build step.
Three.js draws the 3D scene, GSAP ScrollTrigger and Lenis drive the scroll animation (all from CDNs).

- `index.html` — the landing page with the download
- `api.html` — the API and SDK reference (`docs.css`, `js/docs.js`)
- `sdk/` — copies of `sdk/python/afh_sdk.py` and `sdk/js/afh.mjs` to download; copy them again
  when the SDKs change

Preview it:

    python -m http.server 5520 --directory website

then open http://127.0.0.1:5520/.

## Downloads and updates

The Download buttons point at `downloads/AFH-Setup-<version>.exe` (not committed: copy the
installer from `desktop/dist/`). Copy `desktop/dist/latest.yml` there too: the app's updater reads
it. Once the site is online, put the address of that folder
(e.g. `https://your-site.com/downloads/`) in AFH → Settings → About → Update address, and every
copy of AFH set to it will download new versions in the background.

When you publish a version, update the version and size shown on the landing page.
