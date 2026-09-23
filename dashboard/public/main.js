/**
 * The dashboard's bootstrap.
 *
 * It lived inline in index.html, and the Content-Security-Policy the page is
 * served with (firebase.json, and ironclad serve's STATIC_HEADERS) allows
 * scripts from 'self' only: Chrome refused the inline block, and the page
 * rendered no catalog and never started sign-in (PRODUCTIZE_NOTES §16.50).
 * As a file of its own it is 'self'.
 */

import { renderCatalog } from "/app.js";

const config = window.ICIT_CONFIG;

// The capability list, the presets and the framework picker all come from
// catalog.json, which is generated from the engine's registry. There is no
// second list of capabilities anywhere in this page.
const catalog = await fetch("/catalog.json").then((r) => r.json());
const parts = renderCatalog(catalog);
document.getElementById("capability-list").innerHTML = parts.modules;
document.getElementById("group-presets").innerHTML = parts.groups;
document.getElementById("framework-select").innerHTML = parts.frameworks;
document.getElementById("assessment-type-select").innerHTML = parts.assessmentTypes;

// Placeholders survive when the deploy step has not run. Say so plainly
// rather than failing with a console error nobody sees.
const configured = !JSON.stringify(config).includes("__");
if (!configured) {
  document.getElementById("not-configured").hidden = false;
} else {
  const { startAuth } = await import("/auth.js");
  await startAuth(config);
}
