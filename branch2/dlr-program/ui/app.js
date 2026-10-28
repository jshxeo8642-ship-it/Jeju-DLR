"use strict";
const $ = id => document.getElementById(id);
let rollingResult = null;
let config = null, weather = null, result = null, editorDirty = false, busy = false;
const fmt = (v, digits = 2) => Number(v).toLocaleString("ko-KR", {maximumFractionDigits: digits});
const esc = value => String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const colors = {teal:"#087e85", slate:"#91a4b0", orange:"#c78232", pale:"#d9eeea"};

function message(text, error = false) { $("message").textContent = text; $("message").className = error ? "error" : "success"; }
function invalidate() {
  rollingResult = null; result = null; $("results").hidden = true; $("emptyState").hidden = false;
  $("downloadResult").disabled = true;
}
function syncControls() {
  $("slr").value = config.operation.slr_current_a;
  $("tmax").value = config.risk_limits.tmax_c;
  $("tmaxProbability").value = config.risk_limits.max_tmax_probability * 100;
  $("quantile").value = config.risk_limits.degradation_quantile * 100;
  $("doseLimit").value = config.risk_limits.max_additional_degradation;
  $("upperCurrent").value = config.operation.max_search_current_a;
  $("configEditor").value = JSON.stringify(config, null, 2); editorDirty = false;
  $("modelNote").textContent = config.degradation.note || "";
  updateInputLabel();
}
function updateInputLabel() {
  $("inputLabel").textContent = weather ? `${weather.source_kind === "synthetic_fixture" ? "합성 예제" : "외부 입력"} · ${weather.scenario_ids?.length ?? "?"}개 시나리오 · ${weather.span_ids?.length ?? "?"}개 경간` : "시나리오를 불러오세요";
}
function captureControls() {
  if (editorDirty) throw new Error("수정한 JSON의 ‘설정 적용’을 먼저 눌러주세요.");
  for (const id of ["slr","tmax","tmaxProbability","quantile","doseLimit","upperCurrent"])
    if (!$(id).value.trim() || !$(id).checkValidity()) throw new Error("분석 조건의 숫자와 허용 범위를 확인하세요.");
  config.operation.slr_current_a = Number($("slr").value);
  config.operation.max_search_current_a = Number($("upperCurrent").value);
  config.risk_limits = {...config.risk_limits, tmax_c:Number($("tmax").value),
    max_tmax_probability:Number($("tmaxProbability").value)/100,
    degradation_quantile:Number($("quantile").value)/100,
    max_additional_degradation:Number($("doseLimit").value)};
  $("configEditor").value = JSON.stringify(config,null,2);
}
async function loadExample() {
  const response = await fetch("/api/example");
  if (!response.ok) throw new Error("예제 입력을 불러올 수 없습니다.");
  const data = await response.json(); config = data.constant_data; weather = data.weather_scenarios_N;
  syncControls(); invalidate(); $("calculate").disabled = false;
  message("합성 예제가 준비되었습니다. 입력 규격을 확인하려면 ‘입력 예제’를 내려받으세요.");
}
function download(name, data) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)], {type:"application/json"}));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function setBusy(value) {
  busy = value;
  document.querySelectorAll(".control-panel input,.control-panel button,.control-panel textarea").forEach(e=>e.disabled=value);
  $("loading").hidden = !value; $("emptyState").hidden = value || !!result;
  $("calculate").textContent = value ? "계산 중…" : "DLR 계산하기 →";
}
async function calculate() {
  if (busy) return;
  let timer;
  try {
    captureControls(); invalidate(); setBusy(true); message("동일한 시나리오 세트로 SLR과 후보전류를 비교합니다.");
    const start = Date.now(); $("elapsed").textContent = "0";
    timer = setInterval(()=>$("elapsed").textContent=String(Math.floor((Date.now()-start)/1000)),500);
    const response = await fetch("/api/calculate", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({constant_data:config,weather_scenarios_N:weather})});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || "계산에 실패했습니다.");
    rollingResult = data; result = data; setupHourly(); renderResults(); message(`계산 완료 · ${fmt(result.elapsed_seconds,1)}초 · 결과는 현재 입력의 계산값입니다.`);
  } catch(error) { message(error.message,true); }
  finally { clearInterval(timer); setBusy(false); }
}

// Small dependency-free SVG renderer. Labels are escaped; uploaded content is never HTML.
function chart(target, {series=[], xValues, yMin, yMax, yLabel="", xLabel="", xFormat=v=>fmt(v,1), yFormat=v=>fmt(v,2), band=null, hlines=[], vlines=[], dots=false, yTransform=v=>v, yInverse=v=>v, step=false}) {
  const width=620,height=275,left=66,right=20,top=22,bottom=48;
  let xMin=Math.min(...xValues),xMax=Math.max(...xValues);
  if(xMax===xMin){xMin-=.5;xMax+=.5;}
  if(yMax===yMin){yMax+=.5;yMin-=.5;}
  const yLo=yTransform(yMin),yHi=yTransform(yMax);
  const px=x=>left+(x-xMin)/(xMax-xMin)*(width-left-right);
  const py=y=>top+(1-(yTransform(y)-yLo)/(yHi-yLo))*(height-top-bottom);
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(yLabel)} 그래프"><title>${esc(yLabel)}</title>`;
  for(let i=0;i<=4;i++){
    const y=yInverse(yLo+(yHi-yLo)*i/4),p=py(y);
    svg+=`<line x1="${left}" x2="${width-right}" y1="${p}" y2="${p}" stroke="#e7edf1"/><text x="${left-10}" y="${p+4}" text-anchor="end">${esc(yFormat(y))}</text>`;
    const x=xMin+(xMax-xMin)*i/4;
    svg+=`<text x="${px(x)}" y="${height-bottom+23}" text-anchor="middle">${esc(xFormat(x))}</text>`;
  }
  svg+=`<text class="axis-title" x="${left}" y="12">${esc(yLabel)}</text><text class="axis-title" x="${width-right}" y="${height-3}" text-anchor="end">${esc(xLabel)}</text>`;
  if(band){
    const points=band.x.map((x,i)=>`${px(x)},${py(band.high[i])}`).concat(band.x.map((x,i)=>`${px(x)},${py(band.low[i])}`).reverse()).join(" ");
    svg+=`<polygon points="${points}" fill="${band.color||colors.pale}" opacity=".65"/>`;
  }
  for(const line of hlines) if(line.value>=yMin&&line.value<=yMax)
    svg+=`<line x1="${left}" x2="${width-right}" y1="${py(line.value)}" y2="${py(line.value)}" stroke="${line.color||colors.orange}" stroke-dasharray="5 4"/><text x="${width-right}" y="${py(line.value)-5}" text-anchor="end">${esc(line.label||"")}</text>`;
  for(const line of vlines) if(line.value>=xMin&&line.value<=xMax)
    svg+=`<line x1="${px(line.value)}" x2="${px(line.value)}" y1="${top}" y2="${height-bottom}" stroke="${colors.orange}" stroke-dasharray="5 4"/>`;
  for(const s of series){
    const points=s.x.map((x,i)=>[px(x),py(s.y[i])]);
    const path=points.map((p,i)=>i===0?`M${p[0]},${p[1]}`:step?`H${p[0]}V${p[1]}`:`L${p[0]},${p[1]}`).join(" ");
    svg+=`<path d="${path}" fill="none" stroke="${s.color||colors.teal}" stroke-width="${s.width||2.2}" opacity="${s.opacity||1}"/>`;
    if(dots) s.x.forEach((x,i)=>{svg+=`<circle cx="${px(x)}" cy="${py(s.y[i])}" r="3" fill="${s.color||colors.teal}"><title>${esc(s.name||"")} · ${esc(xFormat(x))}: ${esc(fmt(s.y[i],5))}</title></circle>`;});
  }
  $(target).innerHTML=svg+"</svg>";
}
function renderRisk() {
  if(!result)return;
  const c=result.degradation_risk_curve, log=$("logScale").checked;
  const first=c.threshold[0],last=c.threshold.at(-1),pad=Math.max((last-first)*.05,.005);
  const x=[first-pad,...c.threshold,last+pad], y=[1,...c.exceedance_probability,0];
  const allowed=x.map((_,i)=>i).filter(i=>!log||y[i]>0);
  const floor=Math.min(.1,c.probability_resolution);
  chart("riskChart",{xValues:x,series:[{x:allowed.map(i=>x[i]),y:allowed.map(i=>y[i])}],
    yMin:log?floor:0,yMax:1,yLabel:log?"초과확률 % · 로그축 (0 제외)":"초과확률 %",xLabel:"추가 열노화 · 기준온도 환산 h",yFormat:v=>fmt(100*v,3),step:true,
    yTransform:log?Math.log10:v=>v,yInverse:log?v=>10**v:v=>v,
    vlines:[{value:result.risk_limits.max_additional_degradation}]});
  exploreQuantile();
}
function exploreQuantile() {
  if(!result)return;
  const p=Number($("exploreQuantile").value)/100;
  if(!(p>0&&p<=1)){$("exploreValue").textContent="0 초과 100 이하를 입력하세요";return;}
  const c=result.degradation_risk_curve;
  const i=c.cdf.findIndex(v=>v+1e-14>=p);
  $("exploreValue").textContent=`${fmt(c.threshold[i<0?c.threshold.length-1:i],5)} 환산 h`;
  const sparse=(1-p)*result.scenario_count<1;
  $("sampleNote").textContent=`N=${result.scenario_count} · 경험확률 해상도 ${fmt(100/result.scenario_count,4)}%p. ${sparse?"선택 분위수는 표본 최댓값입니다. q99.9 등의 극단 꼬리를 외삽하지 않습니다.":"입력 시나리오를 동일 가중치로 집계한 경험분포입니다."}`;
}
function timeLabel(timestamp) {return new Date(timestamp).toLocaleTimeString("ko-KR",{timeZone:"Asia/Seoul",hour:"2-digit",minute:"2-digit",hour12:false});}
function renderSpan() {
  if(!result)return;
  const index=Number($("spanSelect").value||0), s=result.spans[index];
  const x=result.time_edges.map(t=>new Date(t).getTime());
  const temp=s.dlr_temperature, slr=s.slr_temperature;
  const lo=Math.min(...temp.min,...slr.min)-3, hi=Math.max(...temp.max,...slr.max,result.risk_limits.tmax_c)+5;
  chart("temperatureChart",{xValues:x,series:[...s.sample_temperatures.map(y=>({x,y,color:colors.teal,width:.8,opacity:.17})),{x,y:slr.p50,color:colors.slate},{x,y:temp.p50,color:colors.teal}],
    band:{x,low:temp.p05,high:temp.p95},yMin:lo,yMax:hi,yLabel:"도체온도 °C",xLabel:"한국시간 (KST)",xFormat:timeLabel,hlines:[{value:result.risk_limits.tmax_c,label:"Tmax"}]});
  const w=s.wind_speed;
  const extend=a=>[...a,a.at(-1)];
  chart("weatherChart",{xValues:x,series:[{x,y:extend(w.p50)}],yMin:0,yMax:Math.max(...w.max)*1.1,yLabel:"풍속 m/s",xLabel:"한국시간 (KST)",xFormat:timeLabel,step:true,
    band:{x,low:extend(w.min),high:extend(w.max)}});
}
function metric(id,value,unit,digits=1){$(id).innerHTML=value===null?"산출 불가":`${esc(fmt(value,digits))}<small>${esc(unit)}</small>`;}
function renderResults() {
  $("results").hidden=false; $("emptyState").hidden=true; $("downloadResult").disabled=false;
  const status=result.search.status;
  const labels={converged:"안전조건을 만족하는 전류 탐색 완료",search_cap_reached:"탐색 상한 도달 · 최대값 미확정",infeasible:"안전조건을 만족하는 전류 없음"};
  $("resultStatus").textContent=labels[status]; $("resultStatus").className=`pill ${status==="converged"?"status-good":status==="infeasible"?"status-bad":"status-warn"}`;
  $("resultMeta").textContent=`${result.scenario_count}개 시나리오 · ${result.spans.length}개 경간 · ${fmt(result.elapsed_seconds,1)}초`;
  metric("dlrValue",result.recommended_DLR,"A"); metric("slrValue",result.SLR,"A");
  $("dlrQualifier").textContent=status==="infeasible"?"":status==="search_cap_reached"?"(설정상한)":"";
  $("dlrDelta").textContent=result.increase_a===null?"그래프는 0 A 진단 결과":`SLR 대비 ${result.increase_a>=0?"+":""}${fmt(result.increase_a,1)} A (${result.increase_percent>=0?"+":""}${fmt(result.increase_percent,1)}%)`;
  metric("tmaxValue",100*result.Tmax_risk,"%",3);
  $("tmaxLimit").textContent=`허용 ${fmt(100*result.risk_limits.max_tmax_probability,3)}% · 전체 경간·시간`;
  $("doseTitle").textContent=`추가 열노화 q${fmt(100*result.risk_limits.degradation_quantile,4)}`;
  metric("doseValue",result.additional_degradation_quantile,"환산 h",4);
  $("doseCaption").textContent=`허용 ${fmt(result.risk_limits.max_additional_degradation,4)} h · 기준 ${result.degradation_model.reference_temperature_c}°C`;
  const trace=[...result.search_trace].sort((a,b)=>a.current_a-b.current_a),x=trace.map(t=>t.current_a),y=trace.map(t=>t.additional_degradation_quantile);
  // Signed log1p retains negative paired differences below SLR.
  const transform=v=>Math.sign(v)*Math.log1p(Math.abs(v)), inverse=v=>Math.sign(v)*Math.expm1(Math.abs(v));
  chart("searchChart",{xValues:x,series:[{x,y,name:"추가 열노화 분위수"}],yMin:Math.min(0,...y),yMax:Math.max(.001,...y,result.risk_limits.max_additional_degradation)*1.05,
    yLabel:"추가 열노화 환산 h · 부호 보존 log(1+|값|)축",xLabel:"고정 후보전류 A",dots:true,yTransform:transform,yInverse:inverse,
    hlines:[{value:result.risk_limits.max_additional_degradation}],vlines:[{value:result.SLR}]});
  $("searchNote").textContent=`${result.search.iterations}회 탐색 · 전류 허용오차 ${result.configuration.operation.current_tolerance_a} A · Tmax와 추가 열노화 조건을 동시에 적용합니다.`;
  $("spanSelect").replaceChildren(...result.spans.map((s,i)=>new Option(s.name,String(i))));
  const spanName=id=>result.spans.find(s=>s.id===id)?.name||id;
  const details=[["온도 기준 병목",spanName(result.temperature_bottleneck_span)],["열노화 분위수 기준 병목",spanName(result.degradation_bottleneck_span)],["전체 최고 도체온도",`${fmt(result.peak_temperature_c,2)} °C`],["최고온도 발생 시각",new Date(result.peak_time).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"})+" KST"],["해당 시나리오",result.peak_scenario_id]];
  $("peakDetails").innerHTML=details.map(([a,b])=>`<div><span>${esc(a)}</span><strong>${esc(b)}</strong></div>`).join("");
  $("spanRows").innerHTML=result.spans.map(s=>`<tr><td>${esc(s.name)}</td><td>${esc(fmt(s.maximum_temperature_c,1))}°C</td><td>${esc(fmt(100*s.Tmax_risk,3))}%</td><td>${esc(fmt(s.additional_degradation_quantile,4))} h</td></tr>`).join("");
  const notes=[...result.warnings,...(result.configuration.conductor.assumptions||[]),...(result.configuration.assumptions||[])];
  $("warnings").replaceChildren(...notes.map(t=>{const li=document.createElement("li");li.textContent=t;return li;}));
  $("provenance").textContent=`입력 SHA-256: ${result.provenance.weather_scenarios_sha256} · ${result.source_label}`;
  renderRisk();renderSpan();
}

$("calculate").addEventListener("click",calculate);
$("resetExample").addEventListener("click",()=>loadExample().catch(e=>message(e.message,true)));
$("downloadResult").addEventListener("click",()=>result&&download("dlr_result.json",rollingResult || result));
$("downloadWeather").addEventListener("click",()=>weather&&download("weather_scenarios.json",weather));
$("downloadConfig").addEventListener("click",()=>{try{captureControls();download("constant_data.json",config);}catch(e){message(e.message,true);}});
$("spanSelect").addEventListener("change",renderSpan);
$("logScale").addEventListener("change",renderRisk);
$("exploreQuantile").addEventListener("input",exploreQuantile);
$("configEditor").addEventListener("input",()=>{editorDirty=true;invalidate();message("JSON 수정 후 ‘설정 적용’을 눌러주세요.");});
document.querySelectorAll(".input-grid input").forEach(input=>input.addEventListener("input",()=>{invalidate();message("설정이 바뀌었습니다. 다시 계산하면 새 조건이 적용됩니다.");}));
function applyConfig(value) {
  // Deeper numerical validation runs in Branch 2; guard basic UI structure here.
  if(!value||value.schema_version!=="1.0"||!value.operation||!value.risk_limits||!value.degradation||!value.conductor||!Array.isArray(value.spans))throw new Error("설정 JSON의 schema_version·operation·risk_limits·degradation·conductor·spans를 확인하세요.");
  config=value;syncControls();invalidate();message("설정을 적용했습니다. 계산 시 입력 규격과 물성 범위를 검사합니다.");
}
$("applyConfig").addEventListener("click",()=>{try{applyConfig(JSON.parse($("configEditor").value));}catch(e){message(e.message,true);}});
async function readUpload(event,kind) {
  const file=event.target.files[0]; if(!file)return;
  try{
    if(file.size>32*1024*1024)throw new Error("파일 크기는 최대 32 MB입니다.");
    const parsed=JSON.parse((await file.text()).replace(/^\uFEFF/,""));
    if(kind==="config")applyConfig(parsed);
    else{if(!Array.isArray(parsed.scenario_ids)||!Array.isArray(parsed.span_ids)||!Array.isArray(parsed.time_edges))throw new Error("시나리오 JSON의 필수 필드를 확인하세요.");weather=parsed;updateInputLabel();invalidate();message(`${file.name}을 불러왔습니다. 경간 ID와 설정을 확인한 뒤 계산하세요.`);}
  }catch(e){message(e.message,true);}finally{event.target.value="";}
}
$("weatherFile").addEventListener("change",e=>readUpload(e,"weather"));
$("configFile").addEventListener("change",e=>readUpload(e,"config"));
loadExample().catch(e=>message(e.message,true));

function setupHourly(){
 if(!rollingResult?.hourly_results)return;
 $("hourSelect").replaceChildren(...rollingResult.hourly_results.map((r,i)=>new Option(`${i}~${i+1}h · ${fmt(r.recommended_DLR,1)} A · ${r.search.status}`,String(i))));
 const values=rollingResult.hourly_DLR_trajectory_24h;
 const x=Array.from({length:25},(_,i)=>i);
 chart("hourlyChart",{xValues:x,series:[{x,y:[...values,values.at(-1)]}],yMin:0,yMax:Math.max(...values,rollingResult.SLR)*1.1,yLabel:"시간별 DLR · A",xLabel:"현재로부터 시간 h",step:true,hlines:[{value:rollingResult.SLR,label:"SLR"}]});
 const init=rollingResult.initialization;
 $("initializationNote").textContent=`초기온도: ${init.temperature_c.map(v=>fmt(v,2)).join(" / ")} °C · ${init.status} · 과거 전류는 SLR 가정`;
}
$("hourSelect").addEventListener("change",()=>{result=rollingResult.hourly_results[Number($("hourSelect").value)];renderResults();});
