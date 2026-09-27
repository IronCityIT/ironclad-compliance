import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { RECORD_FIELDS, FORM_FIELDS, GOVERNANCE_FIELDS, SETTLED_FIELDS, FIELD_LABELS, DEFAULTS, buildRecord, diffRevisions, renderHistory, renderRecords, saveFailureMessage, attentionFindings, renderAttention, isoToday, ATTENTION_WINDOW_DAYS, REVIEW_HORIZON_DAYS, ELEVATED_RISK, AGREEMENT_SETTLED, registerCsv, exportFileName, EXPORT_COLUMNS } from "../public/oversight-core.js";
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

test("a contributor proposes data access; once stored, only an approver moves it, as the rules hold it",()=>{
  const guarded=rules.match(/affectedKeys\(\)\.hasAny\(\s*\[([^\]]*)\]/);
  assert.ok(guarded);
  assert.deepEqual(list(guarded[1]).sort(),[...GOVERNANCE_FIELDS,...SETTLED_FIELDS].sort());
  const proposed=buildRecord({form:{name:"PRIMO",data_access:"PHI"},canApprove:false,uid:"u1",clientId:"sage-spine",stamp:STAMP}).record;
  assert.equal(proposed.data_access,"PHI");
  const prior={...base,tenant_id:"sage-spine",revision:2,created_at:CREATED,created_by:"u1",updated_at:CREATED,updated_by:"u1"};
  // A tampered form that submits the disabled select is ignored all the same.
  const edited=buildRecord({form:{name:"PRIMO",data_access:"PII",notes:"v2"},prior,canApprove:false,uid:"u5",clientId:"sage-spine",stamp:STAMP}).record;
  assert.equal(edited.data_access,"PHI");
  assert.equal(edited.notes,"v2");
  const settled=buildRecord({form:{name:"PRIMO",data_access:"PII"},prior,canApprove:true,uid:"u6",clientId:"sage-spine",stamp:STAMP}).record;
  assert.equal(settled.data_access,"PII");
  // The edit form holds the settled select for a contributor, and frees it for a new record.
  assert.match(js,/function holdSettled[\s\S]*?SETTLED_FIELDS[\s\S]*?disabled = held/);
  assert.match(js,/function startEdit[\s\S]*?holdSettled\(true\)[\s\S]*?function endEdit[\s\S]*?holdSettled\(false\)/);
  assert.match(html,/so is data access once a record is saved/);
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

// The review queue. Fixed date so the cases do not drift with the calendar.
const TODAY="2026-09-26";
const codes=(r)=>attentionFindings(r,TODAY).map(f=>f.code);
const clean={name:"Clean",business_owner:"Practice manager",status:"Active",risk:"Low",data_access:"PHI",phi_scope:"Demographics and imaging",data_flow_direction:"Bidirectional",agreement_status:"Executed",baa_status:"Executed",baa_execution_date:"2025-01-15",baa_document_ref:"Contract 42",review_due:"2027-03-01",cert_expiration_date:"2027-06-30",assurance:"SOC 2 Type II report, 2026"};

test("a fully governed PHI record needs no attention",()=>{
  assert.deepEqual(attentionFindings(clean,TODAY),[]);
});

test("PHI without an executed BAA is a high finding, whatever the BAA status says",()=>{
  for(const baa_status of ["Pending review","Under review","Required - pending","Not required",""]){
    const f=attentionFindings({...clean,baa_status},TODAY);
    assert.equal(f[0].code,"phi-without-baa",baa_status);
    assert.equal(f[0].level,"high");
  }
  assert.ok(!codes({...clean,data_access:"Operational only",baa_status:"Not required",phi_scope:""}).includes("phi-without-baa"));
});

test("an executed BAA without its evidence is called out",()=>{
  assert.match(attentionFindings({...clean,baa_execution_date:""},TODAY)[0].message,/no execution date recorded/);
  assert.match(attentionFindings({...clean,baa_document_ref:"",baa_execution_date:""},TODAY)[0].message,/execution date or document reference/);
});

test("a BAA dated after today is not yet in effect",()=>{
  const f=attentionFindings({...clean,baa_execution_date:"2026-09-27"},TODAY);
  assert.deepEqual(f.map(x=>[x.level,x.code]),[["high","baa-not-yet-effective"]]);
  assert.match(f[0].message,/2026-09-27, after today/);
  assert.deepEqual(codes({...clean,baa_execution_date:TODAY}),[],"executed today is in effect");
});

test("PHI with no scope, and a record with no business owner, are notices",()=>{
  assert.deepEqual(codes({...clean,phi_scope:""}),["phi-scope-missing"]);
  assert.deepEqual(codes({...clean,data_access:"PII",phi_scope:""}),[],"no PHI, no scope owed");
  assert.deepEqual(codes({...clean,business_owner:" "}),["owner-unassigned"]);
});

test("PHI with no data flow direction recorded is a notice",()=>{
  assert.deepEqual(codes({...clean,data_flow_direction:""}),["phi-flow-unrecorded"]);
  assert.deepEqual(codes({...clean,data_flow_direction:undefined}),["phi-flow-unrecorded"]);
  assert.deepEqual(codes({...clean,data_access:"Operational only",baa_status:"Not required",baa_execution_date:"",phi_scope:"",data_flow_direction:""}),[],"no PHI, no direction owed");
  for(const data_flow_direction of ["Bidirectional","Outbound / push","Inbound / pull","Unidirectional"]){
    assert.deepEqual(codes({...clean,data_flow_direction}),[],data_flow_direction);
  }
});

test("a High or Critical rating with no assurance expiry is a notice",()=>{
  assert.deepEqual(ELEVATED_RISK,["High","Critical"]);
  assert.deepEqual(codes({...clean,risk:"High",cert_expiration_date:""}),["assurance-undated"]);
  assert.deepEqual(codes({...clean,risk:"Critical",cert_expiration_date:"soon"}),["assurance-undated"]);
  assert.deepEqual(codes({...clean,risk:"Medium",cert_expiration_date:""}),[],"only elevated ratings owe a dated assurance");
  assert.deepEqual(codes({...clean,risk:"High"}),[],"a dated assurance satisfies it");
});

test("an assurance expiry with no assurance named is a notice",()=>{
  assert.deepEqual(codes({...clean,assurance:""}),["assurance-unnamed"]);
  assert.deepEqual(codes({...clean,assurance:undefined}),["assurance-unnamed"]);
  assert.deepEqual(codes({...clean,assurance:"  "}),["assurance-unnamed"]);
  assert.deepEqual(codes({...clean,assurance:"",cert_expiration_date:""}),[],"no expiry, no name owed");
  assert.deepEqual(codes({...clean,assurance:"",cert_expiration_date:"soon"}),[],"an unreadable expiry is not a recorded one");
  assert.deepEqual(codes({...clean,assurance:"",cert_expiration_date:"2026-01-01"}),["assurance-expired","assurance-unnamed"]);
});

test("a BAA execution date on a BAA not marked executed is a notice",()=>{
  const ops={...clean,data_access:"Operational only",phi_scope:""};
  for(const baa_status of ["Pending review","Under review","Required - pending","Not required","",undefined]){
    assert.deepEqual(codes({...ops,baa_status}),["baa-date-unexecuted"],String(baa_status));
  }
  assert.deepEqual(codes(ops),[],"an executed BAA may carry its date");
  assert.deepEqual(codes({...ops,baa_status:"Under review",baa_execution_date:""}),[],"a document reference alone is a draft");
  assert.deepEqual(codes({...ops,baa_status:"Not required",baa_execution_date:"Jan 2025"}),[],"an unreadable date is not a recorded one");
  assert.deepEqual(codes({...ops,baa_status:"Not required",status:"Retired"}),[],"retired records need no attention");
});

test("a PHI scope on a record whose data access is not PHI is a notice",()=>{
  const off={...clean,baa_status:"Not required",baa_execution_date:""};
  for(const data_access of ["PII","Operational only","No production data"]){
    const f=attentionFindings({...off,data_access},TODAY);
    assert.deepEqual(f.map(x=>[x.level,x.code]),[["notice","phi-scope-contradicted"]],data_access);
    assert.equal(f[0].message,`PHI scope recorded but data access is ${data_access}.`);
  }
  assert.deepEqual(codes({...off,data_access:"PII",phi_scope:" "}),[],"a blank scope is none");
  assert.ok(!codes({...off,data_access:"Unknown"}).includes("phi-scope-contradicted"),"unknown access is its own finding");
  assert.deepEqual(codes(clean),[],"a PHI record may carry its scope");
  assert.deepEqual(codes({...off,data_access:"PII",status:"Retired"}),[],"retired records need no attention");
});

test("an Active relationship with no executed agreement is high",()=>{
  assert.deepEqual(AGREEMENT_SETTLED,["Executed","Not required"]);
  for(const agreement_status of ["Pending review","Under review","Required - pending",""]){
    const f=attentionFindings({...clean,agreement_status},TODAY);
    assert.deepEqual(f.map(x=>[x.level,x.code]),[["high","agreement-not-executed"]],agreement_status);
  }
  assert.deepEqual(codes({...clean,agreement_status:"Not required"}),[],"an approver ruled it unneeded");
  assert.deepEqual(codes({...clean,status:"Onboarding",agreement_status:"Required - pending"}),[],"not live yet");
});

test("an Active relationship never risk-rated is high, not the notice",()=>{
  for(const risk of ["Unrated","",undefined]){
    const f=attentionFindings({...clean,risk},TODAY);
    assert.deepEqual(f.map(x=>[x.level,x.code]),[["high","active-unrated"]],String(risk));
  }
  for(const status of ["Pending information","Onboarding","Under review","Offboarding"]){
    assert.deepEqual(codes({...clean,status,risk:"Unrated"}),["risk-unrated"],status);
  }
  assert.deepEqual(codes({...clean,status:"Retired",risk:"Unrated"}),[],"retired records need no attention");
});

test("an Active relationship of unknown data access is high, not the notice",()=>{
  for(const data_access of ["Unknown","",undefined]){
    const f=attentionFindings({...clean,data_access},TODAY);
    assert.deepEqual(f.map(x=>[x.level,x.code]),[["high","active-access-unknown"]],String(data_access));
  }
  assert.deepEqual(codes({...clean,data_access:"Unknown",baa_status:"Pending review",baa_execution_date:""}),["active-access-unknown"],"the BAA check cannot fire without PHI");
  for(const status of ["Pending information","Onboarding","Under review","Offboarding"]){
    assert.deepEqual(codes({...clean,status,data_access:"Unknown"}),["data-access-unknown"],status);
  }
  assert.deepEqual(codes({...clean,status:"Retired",data_access:"Unknown"}),[],"retired records need no attention");
});

test("review and assurance dates: overdue, within the window, beyond it, absent",()=>{
  const edge=new Date(`${TODAY}T00:00:00Z`);edge.setUTCDate(edge.getUTCDate()+ATTENTION_WINDOW_DAYS);
  const inWindow=edge.toISOString().slice(0,10);
  edge.setUTCDate(edge.getUTCDate()+1);
  const beyond=edge.toISOString().slice(0,10);
  assert.deepEqual(codes({...clean,review_due:"2026-09-25"}),["review-overdue"]);
  assert.deepEqual(codes({...clean,review_due:TODAY}),["review-due-soon"]);
  assert.deepEqual(codes({...clean,review_due:inWindow}),["review-due-soon"]);
  assert.deepEqual(codes({...clean,review_due:beyond}),[]);
  assert.deepEqual(codes({...clean,review_due:""}),["review-unscheduled"]);
  assert.deepEqual(codes({...clean,cert_expiration_date:"2026-01-01"}),["assurance-expired"]);
  assert.deepEqual(codes({...clean,cert_expiration_date:inWindow}),["assurance-expiring"]);
  assert.deepEqual(codes({...clean,cert_expiration_date:""}),[],"no expiry recorded is not itself a finding");
});

test("a review scheduled beyond the horizon is a notice",()=>{
  assert.equal(REVIEW_HORIZON_DAYS,365);
  const edge=new Date(`${TODAY}T00:00:00Z`);edge.setUTCDate(edge.getUTCDate()+REVIEW_HORIZON_DAYS);
  const last=edge.toISOString().slice(0,10);
  edge.setUTCDate(edge.getUTCDate()+1);
  const beyond=edge.toISOString().slice(0,10);
  assert.deepEqual(codes({...clean,review_due:last}),[],"the last day of the horizon");
  assert.deepEqual(codes({...clean,review_due:beyond}),["review-too-distant"]);
  assert.deepEqual(codes({...clean,review_due:"2099-12-31"}),["review-too-distant"]);
  assert.deepEqual(codes({...clean,status:"Retired",review_due:"2099-12-31"}),[]);
});

test("high findings sort ahead of notices; retired records are excluded",()=>{
  const f=attentionFindings({...clean,status:"Under review",risk:"Unrated",baa_status:"Pending review",baa_execution_date:"",review_due:"2020-01-01"},TODAY);
  assert.deepEqual(f.map(x=>x.level),["high","high","notice"]);
  assert.deepEqual(attentionFindings({...clean,status:"Retired",baa_status:"",review_due:"2020-01-01"},TODAY),[]);
  assert.equal(isoToday(new Date("2026-09-26T23:59:00Z")),"2026-09-26");
});

// The same table ironclad/oversight.py is held to, so the browser's queue and
// the server's cannot drift while both exist.
const spec=JSON.parse(fs.readFileSync(path.join(root,"tests","fixtures","oversight-attention.json"),"utf8"));
test("the review queue matches the shared specification, case by case",()=>{
  assert.equal(spec.window_days,ATTENTION_WINDOW_DAYS);
  assert.equal(spec.review_horizon_days,REVIEW_HORIZON_DAYS);
  assert.ok(spec.cases.length>=15);
  for(const c of spec.cases){
    const record={...spec.base};
    for(const [k,v] of Object.entries(c.patch)) record[k]=v;
    assert.deepEqual(attentionFindings(record,spec.today),c.expected,c.name);
  }
});

test("every Sage Spine seed record surfaces its missing BAA",()=>{
  const all=[...sage.oversight.partners,...sage.oversight.integrations];
  for(const r of all) assert.ok(codes(r).includes("phi-without-baa"),r.name);
  const html=renderAttention({partners:sage.oversight.partners,integrations:sage.oversight.integrations},TODAY);
  assert.match(html,new RegExp(`${all.length} records to review as of ${TODAY}; ${all.length} with a high-priority finding`));
});

test("the review queue escapes stored values and says when nothing is due",()=>{
  const queue=renderAttention({partners:[{...clean,name:"<img src=x onerror=alert(1)>",baa_status:"<b>x</b>"}],integrations:[]},TODAY);
  assert.doesNotMatch(queue,/<img|<b>/);
  assert.match(queue,/&lt;img/);
  assert.match(renderAttention({partners:[clean],integrations:[]},TODAY),/Nothing needs attention as of 2026-09-26/);
  assert.match(js,/renderAttention\(/,"the page renders the queue");
  assert.match(html,/id="attention"/,"the page has somewhere to render it");
});

// The register export. A minimal RFC 4180 reader, so the cases check what a
// spreadsheet would see rather than the exact bytes.
function parseCsv(src){
  const rows=[];let row=[],cell="",quoted=false;
  for(let i=0;i<src.length;i++){
    const c=src[i];
    if(quoted){
      if(c==='"'&&src[i+1]==='"'){cell+='"';i++;}
      else if(c==='"') quoted=false;
      else cell+=c;
    }else if(c==='"') quoted=true;
    else if(c===","){row.push(cell);cell="";}
    else if(c==="\r"&&src[i+1]==="\n"){row.push(cell);rows.push(row);row=[];cell="";i++;}
    else cell+=c;
  }
  assert.equal(cell+row.length,"0","ends on a CRLF");
  return rows;
}

test("the register exports every field the rules allow, plus its findings",()=>{
  assert.deepEqual(EXPORT_COLUMNS,["record_type","id",...RECORD_FIELDS,"attention_level","attention"]);
  const [head,...rows]=parseCsv(registerCsv({partners:[{id:"p1",...clean}],integrations:[{id:"i1",...clean,name:"Feed",baa_status:"Pending review",baa_execution_date:"",review_due:""}]},TODAY));
  assert.deepEqual(head,EXPORT_COLUMNS);
  assert.equal(rows.length,2);
  const at=(row,col)=>row[EXPORT_COLUMNS.indexOf(col)];
  assert.deepEqual(rows.map(r=>at(r,"record_type")),["Partner","Integration"]);
  assert.equal(at(rows[0],"attention_level"),"");
  assert.equal(at(rows[0],"baa_document_ref"),"Contract 42");
  assert.equal(at(rows[1],"attention_level"),"high");
  assert.match(at(rows[1],"attention"),/^Handles PHI without an executed BAA \(BAA: Pending review\)\. \| No review date set\.$/);
});

test("the export keeps retired records, sorts by name, and writes stamps as UTC",()=>{
  const stamp={toDate:()=>new Date("2026-09-20T14:05:00Z")};
  const csv=registerCsv({partners:[{...clean,name:"Zeta",status:"Retired",baa_status:""},{...clean,name:"Alpha",updated_at:stamp,created_at:new Date("bad")}],integrations:[]},TODAY);
  const [,a,z]=parseCsv(csv);
  const at=(row,col)=>row[EXPORT_COLUMNS.indexOf(col)];
  assert.deepEqual([at(a,"name"),at(z,"name")],["Alpha","Zeta"]);
  assert.equal(at(z,"attention"),"","a retired record is inventory, not queue");
  assert.equal(at(a,"updated_at"),"2026-09-20T14:05:00.000Z");
  assert.equal(at(a,"created_at"),"","an unreadable stamp is left blank, not 'Invalid Date'");
});

test("the export quotes delimiters and neutralises spreadsheet formulas",()=>{
  const notes='Line one, "quoted"\r\nline two';
  const port=["HTTPS/443","DICOM/104"].join(String.fromCharCode(13,10));
  const csv=registerCsv({partners:[{...clean,name:"=HYPERLINK(\"http://x\",\"y\")",notes,business_owner:"+1 cmd",technical_owner:"-2",phi_scope:"@SUM(A1)",assurance:"\tTab",port_protocol:port}],integrations:[]},TODAY);
  const rows=parseCsv(csv);
  assert.equal(rows.length,2,"a line break inside a cell does not start a row");
  const [,row]=rows;
  const at=(col)=>row[EXPORT_COLUMNS.indexOf(col)];
  assert.equal(at("notes"),notes,"commas, quotes and line breaks survive a round trip");
  assert.equal(at("port_protocol"),port,"a line break alone is quoted too");
  assert.equal(at("name"),"'=HYPERLINK(\"http://x\",\"y\")");
  assert.equal(at("business_owner"),"'+1 cmd");
  assert.equal(at("technical_owner"),"'-2");
  assert.equal(at("phi_scope"),"'@SUM(A1)");
  assert.equal(at("assurance"),"'\tTab");
  assert.equal(at("review_due"),"2027-03-01","an ISO date is not mistaken for a formula");
});

test("every Sage Spine seed record exports with its missing BAA; the file is named for the tenant",()=>{
  const [,...rows]=parseCsv(registerCsv({partners:sage.oversight.partners,integrations:sage.oversight.integrations},TODAY));
  assert.equal(rows.length,sage.oversight.partners.length+sage.oversight.integrations.length);
  for(const r of rows) assert.match(r[EXPORT_COLUMNS.indexOf("attention")],/Handles PHI without an executed BAA/,r[EXPORT_COLUMNS.indexOf("name")]);
  assert.equal(exportFileName("sage-spine",TODAY),"oversight-register-sage-spine-2026-09-26.csv");
  assert.equal(exportFileName("../../etc",TODAY),"oversight-register-etc-2026-09-26.csv");
  assert.equal(exportFileName("",TODAY),"oversight-register-tenant-2026-09-26.csv");
});

// ironclad/oversight.py::register_csv is held to the same file, byte for byte.
const exportSpec=JSON.parse(fs.readFileSync(path.join(root,"tests","fixtures","oversight-export.json"),"utf8"));
test("the export matches the shared specification the server's export is held to",()=>{
  assert.equal(registerCsv(exportSpec.register,exportSpec.today),exportSpec.csv);
  assert.equal(exportFileName(exportSpec.tenant_id,exportSpec.today),exportSpec.filename);
});

test("the page offers the export only once both kinds have loaded",()=>{
  assert.match(html,/<button id="export-csv"[^>]*disabled/);
  assert.match(js,/registerCsv\(/);
  assert.match(js,/\$\("export-csv"\)\.disabled = loaded\.size < KINDS\.length/);
  assert.match(js,/URL\.revokeObjectURL/);
});
