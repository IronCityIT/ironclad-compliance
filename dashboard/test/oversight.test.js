import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,"..","..");
const html=fs.readFileSync(path.join(root,"dashboard","public","oversight.html"),"utf8");
const js=fs.readFileSync(path.join(root,"dashboard","public","oversight.js"),"utf8");
const sage=JSON.parse(fs.readFileSync(path.join(root,"tenants","sage-spine","seed.json"),"utf8"));

test("oversight workspace is tenant-claim driven and CSP-safe",()=>{
  assert.match(js,/token\.claims\.client_id/);
  assert.match(js,/owner.*compliance_manager.*contributor/);
  assert.doesNotMatch(html,/on(click|submit|load)=/i);
  assert.doesNotMatch(html,/javascript:/i);
  assert.match(html,/Partner & Integration Oversight/);
});

test("Sage Spine seed captures the live clinical integration chain",()=>{
  assert.equal(sage.tenant_id,"sage-spine");
  const partners=sage.oversight.partners.map(x=>x.name);
  for(const name of ["DrChrono","PRIMO","Fujifilm"]) assert.ok(partners.includes(name),name);
  const integrations=sage.oversight.integrations.map(x=>x.name);
  for(const name of ["DrChrono to PRIMO","PRIMO to Fuji MWL","OEC Storage SCP"]) assert.ok(integrations.includes(name),name);
  assert.ok(sage.oversight.partners.every(x=>x.data_access==="PHI"));
});