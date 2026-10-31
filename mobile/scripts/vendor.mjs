// Copies the libraries the app bundles into www/vendor (kept out of git): Ionic's components and
// icons from node_modules, marked + DOMPurify from the desktop UI. Runs before every `cap sync`.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const app = join(here, "..");
const out = join(app, "www", "vendor");
const ionic = join(app, "node_modules", "@ionic", "core");

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "ionic"), { recursive: true });
// the ES module build only: the SystemJS fallbacks are for browsers no phone runs any more
for (const f of readdirSync(join(ionic, "dist", "ionic"))) {
  if (f.endsWith(".js") && !f.includes(".system") && f !== "ionic.js") cpSync(join(ionic, "dist", "ionic", f), join(out, "ionic", f));
}
cpSync(join(ionic, "dist", "ionic", "svg"), join(out, "ionic", "svg"), { recursive: true });
cpSync(join(ionic, "css", "ionic.bundle.css"), join(out, "ionic.bundle.css"));
cpSync(join(ionic, "css", "palettes", "dark.always.css"), join(out, "dark.css"));
for (const f of ["marked.min.js", "purify.min.js"]) {
  const src = join(app, "..", "web", "vendor", f);
  if (!existsSync(src)) throw new Error(`missing ${src}`);
  cpSync(src, join(out, f));
}
console.log("vendor ready:", out);
