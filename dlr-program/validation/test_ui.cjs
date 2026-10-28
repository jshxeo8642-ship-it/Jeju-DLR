/* UI logic smoke tests with a minimal DOM double. No browser or layout certification. */
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const example = {constant_data:JSON.parse(fs.readFileSync(path.join(root,"config/example_ascc430.json"),"utf8")), weather_scenarios_N:JSON.parse(fs.readFileSync(path.join(root,"data/example_scenarios.json"),"utf8"))};
const output = JSON.parse(fs.readFileSync(path.join(root,"output/result.json"),"utf8"));
const ids = [...fs.readFileSync(path.join(root,"ui/index.html"),"utf8").matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
const nodes = new Map(ids.map(id=>[id,{id,value:"",innerHTML:"",textContent:"",hidden:false,disabled:false,checked:false,files:[],listeners:{},className:"",addEventListener(k,v){this.listeners[k]=v;},checkValidity(){return true;},replaceChildren(...children){this.children=children;},click(){}}]));
for (const node of nodes.values()) {
  let value = "";
  Object.defineProperty(node,"value",{get(){return value;},set(v){value=String(v);}});
}
const sandbox={console,setTimeout,clearTimeout,setInterval,clearInterval,Blob,URL,
  Option:function(name,value){this.name=name;this.value=value;},
  document:{getElementById:id=>{assert(nodes.has(id),`Missing HTML element: ${id}`);return nodes.get(id);},querySelectorAll:()=>[],createElement:()=>({click(){}})},
  fetch:async url=>({ok:true,json:async()=>JSON.parse(JSON.stringify(url==="/api/example"?example:output))})};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root,"ui/app.js"),"utf8"),sandbox);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(nodes.get("slr").value,"600");
  await vm.runInContext("calculate()",sandbox);
  assert.equal(nodes.get("results").hidden,false);
  assert.equal(nodes.get("downloadResult").disabled,false);
  assert(nodes.get("hourlyChart").innerHTML.includes("<svg"));
  assert.equal(nodes.get("hourSelect").children.length,24);
  nodes.get("hourSelect").value="23";
  nodes.get("hourSelect").listeners.change();
  assert.equal(vm.runInContext("result.hour_index",sandbox),23);
  for(const id of ["riskChart","searchChart","temperatureChart","weatherChart"]){
    assert(nodes.get(id).innerHTML.includes("<svg"));
    assert(!/NaN|Infinity|undefined/.test(nodes.get(id).innerHTML),`${id} contains invalid coordinates`);
  }
  nodes.get("logScale").checked=true;
  vm.runInContext("renderRisk()",sandbox);
  assert(!/NaN|Infinity/.test(nodes.get("riskChart").innerHTML));
  nodes.get("exploreQuantile").value="99.99";
  vm.runInContext("exploreQuantile()",sandbox);
  assert(nodes.get("sampleNote").textContent.includes("표본 최댓값"));
  nodes.get("spanSelect").value="1";
  vm.runInContext("renderSpan()",sandbox);
  assert(!/NaN|Infinity/.test(nodes.get("temperatureChart").innerHTML));
  assert.equal(vm.runInContext("esc('<script>')",sandbox),"&lt;script&gt;");
  vm.runInContext("invalidate()",sandbox);
  assert.equal(nodes.get("results").hidden,true);
  assert.equal(nodes.get("downloadResult").disabled,true);
  vm.runInContext("editorDirty=true",sandbox);
  assert.throws(()=>vm.runInContext("captureControls()",sandbox),/설정 적용/);
  console.log("PASS: initial load, calculation flow, 4 SVG charts, log scale, extreme quantile, span selection, escaping, stale result clearing, unapplied editor guard.");
})().catch(error=>{console.error(error);process.exitCode=1;});
