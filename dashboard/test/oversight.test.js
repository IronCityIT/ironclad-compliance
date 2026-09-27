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

// firestore.rules closes the register's vocabulary. The page and the seed are
// held to that same vocabulary here, so an option the rules would refuse is
// caught without an emulator rather than as a failed save in front of a client.
const rules=fs.readFileSync(path.join(root,"firestore.rules"),"utf8");
const list=(src)=>[...src.matchAll(/'([^']*)'/g)].map(m=>m[1]);
function vocabulary(field){
  const direct=rules.match(new RegExp(String.raw`d\.${field} in \[([^\]]*)\]`));
  if(direct) return list(direct[1]);
  const optional=rules.match(new RegExp(String.raw`optionalOneOf\(d, '${field}', \[([^\]]*)\]\)`));
  if(optional) return list(optional[1]);
  const shared=rules.match(new RegExp(String.raw`d\.${field} in (\w+)\b`));
  if(shared) return list(rules.match(new RegExp(String.raw`let ${shared[1]} = \[([^\]]*)\]`))[1]);
  throw new Error(`no vocabulary for ${field} in firestore.rules`);
}
const CLOSED=["status","risk","agreement_status","baa_status","data_access","data_flow_direction"];
const allowedFields=list(rules.match(/function oversightFields\(\) \{\s*return \[([^\]]*)\]/)[1]);

test("every form option is a value the rules accept",()=>{
  for(const field of CLOSED){
    const select=html.match(new RegExp(`<select name="${field}">(.*?)</select>`));
    assert.ok(select,`form has a ${field} select`);
    const options=[...select[1].matchAll(/<option(?: value="([^"]*)")?>([^<]*)<\/option>/g)].map(m=>m[1]??m[2]);
    const allowed=vocabulary(field);
    for(const o of options) assert.ok(allowed.includes(o),`${field}: "${o}" is refused by firestore.rules`);
  }
  for(const m of html.matchAll(/<(?:input|select|textarea) name="(\w+)"/g)){
    if(m[1]!=="record_type") assert.ok(allowedFields.includes(m[1]),`form field ${m[1]} is not in oversightFields()`);
  }
});

test("the page writes only fields the rules allow, and its defaults are in vocabulary",()=>{
  const written=js.match(/const record=\{(.*?)\};/s)[1];
  for(const m of written.matchAll(/(\w+):/g)) assert.ok(allowedFields.includes(m[1]),`page writes ${m[1]}`);
  for(const [field,fallback] of [["status","Pending information"],["risk","Unrated"],["agreement_status","Pending review"],["baa_status","Pending review"],["data_access","Unknown"]]){
    assert.ok(vocabulary(field).includes(fallback),`${field} default "${fallback}"`);
  }
});

test("every Sage Spine seed record fits the register's closed shape",()=>{
  const DATE=/^(|\d{4}-\d{2}-\d{2})$/;
  for(const kind of ["partners","integrations"]){
    for(const r of sage.oversight[kind]){
      for(const key of Object.keys(r)) assert.ok(allowedFields.includes(key),`${r.name}: ${key}`);
      for(const field of CLOSED) if(field in r) assert.ok(vocabulary(field).includes(r[field]),`${r.name}: ${field}="${r[field]}"`);
      for(const field of ["review_due","baa_execution_date","cert_expiration_date"]) if(field in r) assert.match(r[field],DATE,`${r.name}: ${field}`);
      assert.ok(r.name.length>0&&r.name.length<=120);
    }
  }
});

// firestore.rules refuses a register write that does not file history/{revision}
// in the same batch. The page is held to that path here, so a regression to a
// bare addDoc shows up as a failing test rather than as every save refused.
test("the page files each new record with its revision 1 history entry in one batch",()=>{
  assert.ok(allowedFields.includes("revision"),"revision is in oversightFields()");
  assert.doesNotMatch(js,/\baddDoc\b/);
  assert.match(js,/revision:1,/);
  const save=js.match(/const batch=writeBatch\(db\);(.*?)await batch\.commit\(\)/s);
  assert.ok(save,"the save is a single batch");
  assert.match(save[1],/batch\.set\(ref,record\)/);
  assert.match(save[1],/batch\.set\(doc\(ref,"history","1"\),record\)/);
});

test("the form is reset from a reference taken before the save is awaited",()=>{
  // e.currentTarget is null once the handler has yielded; resetting through it
  // would report a successful save as an error.
  const handler=js.match(/onsubmit=async e=>\{(.*)\}\}\);?\s*$/s)[1];
  const awaited=handler.indexOf("await ");
  assert.ok(awaited>0);
  assert.doesNotMatch(handler.slice(awaited),/e\.currentTarget/);
});
