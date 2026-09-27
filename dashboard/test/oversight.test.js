import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { RECORD_FIELDS, FORM_FIELDS, GOVERNANCE_FIELDS, FIELD_LABELS, DEFAULTS, buildRecord, diffRevisions, renderHistory, renderRecords, saveFailureMessage } from "../public/oversight-core.js";
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

test("the page's field list is the rules' field list, and its defaults are in vocabulary",()=>{
  assert.deepEqual(RECORD_FIELDS,allowedFields);
  for(const f of FORM_FIELDS) assert.ok(FIELD_LABELS[f],`${f} has a label for the history view`);
  for(const [field,fallback] of Object.entries(DEFAULTS)){
    if(CLOSED.includes(field)) assert.ok(vocabulary(field).includes(fallback),`${field} default "${fallback}"`);
  }
});

test("every stored field can be edited on the form, within the rules' bounds",()=>{
  // Edit reopens a record in this form; a field with no input could be neither
  // corrected nor seen before saving.
  for(const f of FORM_FIELDS) assert.match(html,new RegExp(`<(?:input|select|textarea) name="${f}"`),`form has an input for ${f}`);
  for(const m of rules.matchAll(/optionalText\(d, '(\w+)', (\d+)\)/g)){
    const input=html.match(new RegExp(`<(?:input|textarea) name="${m[1]}"[^>]*?maxlength="(\\d+)"`));
    assert.ok(input,`${m[1]} has a maxlength`);
    assert.equal(input[1],m[2],`${m[1]} maxlength matches firestore.rules`);
  }
  assert.match(html,/<input name="name" required maxlength="120">/);
});

const STAMP={sentinel:"serverTimestamp"};
const CREATED={seconds:1};
const base={name:"PRIMO",business_owner:"Practice manager",status:"Active",risk:"Low",agreement_status:"Executed",baa_status:"Executed",data_access:"PHI",notes:"broker"};

test("a new record starts at revision 1, stamped by its author, and a contributor's is unrated",()=>{
  const {record}=buildRecord({form:{...base,risk:"Critical"},canApprove:false,uid:"u1",clientId:"sage-spine",stamp:STAMP});
  assert.equal(record.revision,1);
  assert.equal(record.tenant_id,"sage-spine");
  assert.deepEqual([record.created_by,record.updated_by,record.created_at,record.updated_at],["u1","u1",STAMP,STAMP]);
  assert.deepEqual(GOVERNANCE_FIELDS.map(f=>record[f]),["Pending information","Unrated","Pending review","Pending review"]);
  for(const k of Object.keys(record)) assert.ok(allowedFields.includes(k),k);
  const approved=buildRecord({form:base,canApprove:true,uid:"u2",clientId:"sage-spine",stamp:STAMP}).record;
  assert.equal(approved.risk,"Low");
  assert.deepEqual(buildRecord({form:{...base,name:"  "},canApprove:true,uid:"u",clientId:"c",stamp:STAMP}),{error:"Name is required."});
});

test("an edit is the next revision: creation kept, untouched fields carried, governance held for a contributor",()=>{
  const prior={...base,tenant_id:"sage-spine",revision:3,created_at:CREATED,created_by:"seed",updated_at:{seconds:2},updated_by:"u0",assurance:"SOC 2 Type II",port_protocol:"HTTPS/443"};
  // A contributor's governance selects are disabled, so the browser does not
  // submit them; a tampered form that does is ignored all the same.
  const {record}=buildRecord({form:{name:"PRIMO",notes:"broker, v2",risk:"Unrated",status:"Retired"},prior,canApprove:false,uid:"u5",clientId:"sage-spine",stamp:STAMP});
  assert.equal(record.revision,4);
  assert.deepEqual([record.created_at,record.created_by],[CREATED,"seed"]);
  assert.deepEqual([record.updated_at,record.updated_by],[STAMP,"u5"]);
  assert.equal(record.notes,"broker, v2");
  assert.equal(record.assurance,"SOC 2 Type II");
  assert.equal(record.port_protocol,"HTTPS/443");
  // What contributorKeepsGovernanceState() checks: no governance key moves.
  for(const f of GOVERNANCE_FIELDS) assert.equal(record[f],prior[f],f);
  const changed=Object.keys(record).filter(k=>JSON.stringify(record[k])!==JSON.stringify(prior[k]));
  assert.deepEqual(changed.sort(),["notes","revision","updated_at","updated_by"]);

  const rated=buildRecord({form:{...base,risk:"High",data_access:""},prior,canApprove:true,uid:"u6",clientId:"sage-spine",stamp:STAMP}).record;
  assert.equal(rated.risk,"High");
  assert.equal(rated.data_access,"PHI","an unchosen select keeps the stored value");
});

test("a record seeded before history existed is edited as revision 1",()=>{
  const seeded={...base,tenant_id:"sage-spine",created_at:CREATED,created_by:"seed",updated_at:CREATED,updated_by:"seed"};
  assert.equal(buildRecord({form:{name:"PRIMO"},prior:seeded,canApprove:true,uid:"u",clientId:"sage-spine",stamp:STAMP}).record.revision,1);
});

// firestore.rules refuses a register write that does not file history/{revision}
// in the same batch. The page is held to that path here, so a regression to a
// bare addDoc shows up as a failing test rather than as every save refused.
test("the page saves the record and history/{revision} in one batch, from buildRecord",()=>{
  assert.doesNotMatch(js,/\baddDoc\b/);
  const save=js.match(/const batch = writeBatch\(db\);(.*?)await batch\.commit\(\)/s);
  assert.ok(save,"the save is a single batch");
  assert.match(save[1],/batch\.set\(ref, record\)/);
  assert.match(save[1],/batch\.set\(doc\(ref, "history", String\(record\.revision\)\), record\)/);
  assert.match(js,/const \{ record \} = built;/);
});

test("the form is reset from a reference taken before the save is awaited",()=>{
  // e.currentTarget is null once the handler has yielded; resetting through it
  // would report a successful save as an error.
  const handler=js.slice(js.indexOf("onsubmit = async (e) =>"));
  const awaited=handler.indexOf("await ");
  assert.ok(awaited>0);
  assert.doesNotMatch(handler.slice(awaited),/e\.currentTarget/);
  // The record being edited is captured before the await too, so a Cancel
  // clicked mid-save cannot turn an edit's failure into a create's.
  const captured=handler.indexOf("const current = editing");
  assert.ok(captured>0&&captured<awaited);
});

test("history lists what changed between adjacent revisions, newest first",()=>{
  const r1={...base,revision:1,updated_by:"u1",updated_at:new Date("2026-09-26T10:00:00Z")};
  const r2={...r1,revision:2,risk:"High",notes:"",updated_by:"u2",updated_at:new Date("2026-09-26T11:30:00Z")};
  assert.deepEqual(diffRevisions(r1,r2),[{field:"risk",from:"Low",to:"High"},{field:"notes",from:"broker",to:""}]);
  const out=renderHistory([r2,r1]);
  assert.ok(out.indexOf("Revision 2")<out.indexOf("Revision 1"));
  assert.match(out,/Risk: Low → High/);
  assert.match(out,/Purpose \/ notes: broker → \(empty\)/);
  assert.match(out,/2026-09-26 11:30 UTC · by u2/);
  assert.match(out,/Record created\./);
  assert.match(renderHistory([]),/No changes recorded yet/);
});

test("history says when the revision before an entry is missing rather than inventing a diff",()=>{
  const out=renderHistory([{...base,revision:1,updated_by:"u"},{...base,revision:3,risk:"High",updated_by:"u"}]);
  assert.match(out,/Earlier revisions are not in the history/);
  assert.doesNotMatch(out,/Low → High/);
});

test("history and cards escape every stored value",()=>{
  const evil='<img src=x onerror=alert(1)>"\'';
  const entry=Object.fromEntries(FORM_FIELDS.map(f=>[f,evil]));
  const out=renderHistory([{...entry,revision:1,updated_by:evil},{...entry,revision:2,name:"x",updated_by:evil}])
    +renderRecords([{...entry,id:evil,revision:evil}],"partners",{canEdit:true});
  assert.doesNotMatch(out,/<img/);
  assert.doesNotMatch(out,/="[^"]*"[^ >\/]/,"no attribute value breaks out of its quotes");
  assert.match(out,/&lt;img src=x onerror=alert\(1\)&gt;&quot;&#39;/);
});

test("only an editor is offered Edit; everyone in the tenant can open History",()=>{
  const r=[{id:"a",name:"PRIMO"}];
  assert.doesNotMatch(renderRecords(r,"partners"),/data-action="edit"/);
  assert.match(renderRecords(r,"partners"),/data-action="history" data-kind="partners" data-id="a"/);
  assert.match(renderRecords(r,"integrations",{canEdit:true}),/data-action="edit" data-kind="integrations" data-id="a"/);
  assert.match(js,/data-action[\s\S]*button\.dataset\.action === "edit" && canEdit/);
});

test("a refused edit is explained as a stale form, not a raw error",()=>{
  assert.match(saveFailureMessage({code:"permission-denied",message:"x"},{id:"a"}),/changed since you opened it/);
  assert.equal(saveFailureMessage({code:"permission-denied",message:"raw"},null),"raw");
  assert.equal(saveFailureMessage({},null),"Record could not be saved.");
});

test("every Sage Spine seed record renders with its actions",()=>{
  for(const kind of ["partners","integrations"]){
    const out=renderRecords(sage.oversight[kind].map((r,i)=>({id:String(i),...r})),kind,{canEdit:true});
    for(const r of sage.oversight[kind]) assert.ok(out.includes(r.name.replace(/&/g,"&amp;")),r.name);
    assert.equal(out.match(/data-action="edit"/g).length,sage.oversight[kind].length);
  }
});
