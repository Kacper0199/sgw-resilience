// Fails the image build when the built index.html has an inline <script>: the Caddyfile CSP allows only
// 'self' scripts, so the browser would block it. Usage: node check-no-inline-scripts.mjs <index.html>
import { readFileSync } from "node:fs";

const html = readFileSync(process.argv[2], "utf8");
const inline = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].filter(([, body]) => body.trim());
if (inline.length > 0) {
  console.error(`index.html has ${inline.length} inline script(s); move them to web/public/*.js (CSP script-src 'self')`);
  process.exit(1);
}
console.log("index.html: no inline scripts");
