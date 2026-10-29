# AFH website

The download page for Agent Flow Harness: plain HTML/CSS/JS, no build step.
Three.js draws the 3D scene, GSAP ScrollTrigger and Lenis drive the scroll animation (all from CDNs).

Preview it:

    python -m http.server 5520 --directory website

then open http://127.0.0.1:5520/.

The Download buttons point at `downloads/AFH-Setup-<version>.exe` (not committed: copy the
installer from `desktop/dist/`). When the site goes online, point the `data-download` links in
`index.html` at wherever the installer is hosted (for example a GitHub release) and update the
version and size shown on the page.
