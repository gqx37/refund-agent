// The chat surface. Vanilla on purpose: it owns #thread directly and the page
// around it is a static server component, so there is no hydration to race.
//
// Everything goes to same-origin /api/*, which attaches the shared secret
// server-side. The browser never sees a credential and never learns the backend
// URL.

const SUGGEST = [
  "I'm Alice Carter, show my orders",
  "Refund SO-10432, it arrived broken",
  "Refund SO-10440 in full",
  "Refund SO-10377",
];

const ICONS = {
  find_customer: '<svg viewBox="0 0 24 24"><circle cx="10" cy="8" r="3.2"/><path d="M4.5 19a5.5 5.5 0 0 1 11 0"/><circle cx="17.5" cy="15.5" r="2.4"/><path d="M19.4 17.4 21.5 19.5"/></svg>',
  list_orders:   '<svg viewBox="0 0 24 24"><path d="M8 6h11M8 12h11M8 18h11"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/></svg>',
  order_lookup:  '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.2"/><path d="M20 20l-3.6-3.6M9 9h4M9 12h4"/></svg>',
  issue_refund:  '<svg viewBox="0 0 24 24"><path d="M9 7H6a3 3 0 0 0-3 3v0a3 3 0 0 0 3 3h9a3 3 0 0 1 3 3v0a3 3 0 0 1-3 3h-3"/><path d="M12 4 9 7l3 3"/></svg>',
  policy:        '<svg viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.4-3 7.6-7 8.9C8 18.6 5 15.4 5 11V6l7-3Z"/><path d="M9 11.5l2 2 4-4"/></svg>',
};
const LABELS = { find_customer: "Finding your account", list_orders: "Pulling up orders", order_lookup: "Checking the order", issue_refund: "Processing refund", policy: "Policy check" };
const CARET = '<span class="caret"></span>';
const COPY_ICON = '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
const CHECK_ICON = '<svg viewBox="0 0 24 24"><path d="M5 12.5 10 17l9-10"/></svg>';

let threadId = null, busy = false;
const thread = document.getElementById("thread");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const form = document.getElementById("composer");
const modal = document.getElementById("modal");

// The backend idles suspended to keep the demo near free, so the first request
// after a deploy pays a full cold boot. Poke it the moment the page paints and
// again whenever the tab comes back, so the machine is booting while the visitor
// reads the suggestions instead of after they hit send.
let lastWarm = 0;
function warm(){
  const now = Date.now();
  if(now - lastWarm < 60000) return;
  lastWarm = now;
  fetch("/api/warm").catch(() => {});
}
warm();
document.addEventListener("visibilitychange", () => { if(!document.hidden) warm(); });
input.addEventListener("focus", warm);

function esc(s){ return (s??"").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }
function el(html){ const t=document.createElement("template"); t.innerHTML=html.trim(); return t.content.firstChild; }
function scroll(){ const m=document.querySelector("main"); m.scrollTop=m.scrollHeight; }

// Render markdown, then tuck the caret inline at the end of the last line.
function renderStreaming(node, raw){
  node.innerHTML = md(raw);
  let host = node.lastElementChild;
  if(host && (host.tagName === "UL" || host.tagName === "OL")) host = host.lastElementChild || host;
  (host || node).insertAdjacentHTML("beforeend", CARET);
}

// Minimal, safe markdown: escape first, then bold / italic / code / lists / headings.
function md(src){
  const inline = s => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*(?!\s)([^*\n]+?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/`([^`]+?)`/g, "<code>$1</code>");
  const lines = (src||"").replace(/\r/g,"").split("\n");
  let out="", i=0;
  const listRe = /^\s*([-*]|\d+\.)\s+/;
  while(i < lines.length){
    if(/^\s*[-*]\s+/.test(lines[i])){ out+="<ul>"; while(i<lines.length && /^\s*[-*]\s+/.test(lines[i])){ out+="<li>"+inline(lines[i].replace(/^\s*[-*]\s+/,""))+"</li>"; i++; } out+="</ul>"; continue; }
    if(/^\s*\d+\.\s+/.test(lines[i])){ out+="<ol>"; while(i<lines.length && /^\s*\d+\.\s+/.test(lines[i])){ out+="<li>"+inline(lines[i].replace(/^\s*\d+\.\s+/,""))+"</li>"; i++; } out+="</ol>"; continue; }
    const h = lines[i].match(/^(#{1,3})\s+(.*)/);
    if(h){ out+="<h4>"+inline(h[2])+"</h4>"; i++; continue; }
    if(lines[i].trim()===""){ i++; continue; }
    const para=[]; while(i<lines.length && lines[i].trim()!=="" && !listRe.test(lines[i]) && !/^#{1,3}\s+/.test(lines[i])){ para.push(lines[i]); i++; }
    out+="<p>"+para.map(inline).join("<br>")+"</p>";
  }
  return out;
}

function renderEmpty(){
  const wrap = el(`<div class="empty"><h2>Refund Agent</h2>
    <p>Look up an order or customer, then request a refund. Policy is checked on every one.</p>
    <div class="suggest"></div></div>`);
  const box = wrap.querySelector(".suggest");
  SUGGEST.forEach(s => { const b=el(`<button>${esc(s)}</button>`); b.onclick=()=>{ input.value=s; submit(); }; box.appendChild(b); });
  thread.appendChild(wrap);
}
function clearEmpty(){ thread.querySelector(".empty")?.remove(); }
function resetChat(){ threadId=null; thread.innerHTML=""; renderEmpty(); input.focus(); }

function addUser(text){
  clearEmpty();
  thread.appendChild(el(`<div class="msg user"><div class="bubble">${esc(text)}</div></div>`));
  scroll();
}

// Tool dialog
function openTool(rec){
  document.getElementById("modalIcon").innerHTML = (ICONS[rec.name]||"").replace("<svg", '<svg class="mi"');
  document.getElementById("modalTitle").textContent = LABELS[rec.name] || rec.name;
  const body = document.getElementById("modalBody");
  if(rec.name === "policy"){
    const reasons = (rec.reasons||[]).map(r => `<li>${esc(r)}</li>`).join("") || "<li>no rules recorded</li>";
    body.innerHTML = `<div class="k">Decision</div><div class="v">${esc(rec.outcome)}</div>`
      + `<div class="k">Rules evaluated</div><ul class="reasons">${reasons}</ul>`;
  } else {
    const argStr = Object.entries(rec.args||{}).filter(([,v]) => v!==null&&v!==undefined&&v!=="").map(([k,v]) => `${k}: ${v}`).join("\n") || "none";
    body.innerHTML = `<div class="k">Input</div><div class="v">${esc(argStr)}</div>`
      + `<div class="k">Result</div><div class="v">${esc(rec.result || (rec.result===null ? "running..." : "none"))}</div>`;
  }
  modal.hidden = false;
}
function closeModal(){ modal.hidden = true; }
modal.addEventListener("click", e => { if(e.target === modal || e.target.closest(".modal-close")) closeModal(); });
document.addEventListener("keydown", e => { if(e.key === "Escape" && !modal.hidden) closeModal(); });

function newAssistant(){
  const node = el(`<div class="msg assistant"><div class="body">
      <div class="chips" hidden></div>
      <div class="text md" hidden></div>
      <div class="meta" hidden></div>
    </div></div>`);
  thread.appendChild(node);
  const chips = node.querySelector(".chips");
  const text = node.querySelector(".text");
  const meta = node.querySelector(".meta");
  const toolEls = {};
  let raw = "";

  // Show the blinking caret immediately as the loading ticker.
  text.hidden = false;
  text.insertAdjacentHTML("beforeend", CARET);

  function addTool(name, args){
    chips.hidden = false;
    const chip = el(`<button class="chip pending" type="button">${ICONS[name]||""}<span class="lbl">${esc(LABELS[name]||name)}</span><span class="spin"></span></button>`);
    const rec = { name, chip, args: args||{}, result: null };
    chip.onclick = () => openTool(rec);
    chips.appendChild(chip);
    (toolEls[name] = toolEls[name] || []).push(rec);
    scroll();
    return rec;
  }
  function addPolicy(ev){
    chips.hidden = false;
    const cls = ev.outcome === "approve" ? "approve" : ev.outcome === "deny" ? "deny" : "hold";
    const label = ev.outcome === "approve" ? "Policy: approved" : ev.outcome === "deny" ? "Policy: blocked" : "Policy: review needed";
    const chip = el(`<button class="chip ${cls}" type="button">${ICONS.policy}<span class="lbl">${esc(label)}</span></button>`);
    const rec = { name: "policy", outcome: ev.outcome, reasons: ev.reasons || [] };
    chip.onclick = () => openTool(rec);
    chips.appendChild(chip);
    scroll();
  }
  function finishTool(name, guardrail, content){
    if(!name) return;
    let list = toolEls[name]; let rec;
    if(!list || !list.length){ rec = addTool(name, {}); } else { rec = list[list.length-1]; }
    rec.result = content || "";
    rec.chip.querySelector(".spin")?.remove();
    rec.chip.classList.remove("pending");
    if(name === "issue_refund"){
      if(guardrail === "approve"){ rec.chip.classList.add("approve"); rec.chip.querySelector(".lbl").textContent = "Refund approved"; }
      else if(guardrail === "deny"){ rec.chip.classList.add("deny"); rec.chip.querySelector(".lbl").textContent = "Blocked by policy"; }
    }
  }
  // Stream markdown (no bubble) with a trailing box caret; wrap in a bubble on seal.
  let sealed = false;
  function seal(cls){ text.innerHTML = md(raw); text.classList.add(cls); sealed = true; }
  function token(t){ raw += t; text.hidden = false; renderStreaming(text, raw); scroll(); }
  function fill(t, {escalated=false}={}){ raw = t; text.hidden = false; seal(escalated ? "escalated" : "boxed"); scroll(); }
  function hold(){ const list = toolEls["issue_refund"]; if(list&&list.length){ const r=list[list.length-1]; r.chip.querySelector(".spin")?.remove(); r.chip.classList.remove("pending"); r.chip.classList.add("hold"); r.chip.querySelector(".lbl").textContent="Held for review"; } }

  // Only while we are still waiting for the stream to open — say what is
  // happening rather than leaving a caret blinking at nothing.
  function waking(){ if(raw || sealed) return; text.innerHTML = '<span class="hint">Waking the agent…</span>' + CARET; }
  function settled(){ if(raw || sealed) return; text.innerHTML = CARET; }

  function done(){
    if(!raw){ text.remove(); }
    else {
      if(!sealed) seal("boxed");  // drop the caret, wrap the final answer in a bubble
      meta.hidden = false;
      const copy = el(`<button title="Copy">${COPY_ICON}<span>Copy</span></button>`);
      copy.onclick = async () => { try { await navigator.clipboard.writeText(raw); copy.innerHTML = CHECK_ICON+"<span>Copied</span>"; setTimeout(()=>copy.innerHTML=COPY_ICON+"<span>Copy</span>", 1400);} catch{} };
      meta.appendChild(copy);
    }
    scroll();
  }
  return { addTool, addPolicy, finishTool, token, fill, hold, waking, settled, done, get raw(){ return raw; } };
}

function escalationCopy(review){
  const amount = (review.amount_cents/100).toLocaleString(undefined,{style:"currency",currency:"USD"});
  const reason = (review.policy_reasons||[]).slice(-1)[0] || "it needs a second look";
  return `This one needs a quick human sign-off before it goes through: **${amount}** on **${review.order_id}**. ${reason}\n\nReply **approve** to release the refund, or **deny** to hold it.`;
}

function setBusy(b){ busy=b; updateSend(); input.disabled=b; if(!b) input.focus(); }
function updateSend(){ sendBtn.disabled = busy || !input.value.trim(); }

async function submit(){
  const text = input.value.trim();
  if(!text || busy) return;
  addUser(text); input.value=""; autosize(); setBusy(true);
  const turn = newAssistant();
  // The backend emits its `thread` event the instant the stream opens, so this
  // only ever fires while the machine is still cold-booting.
  const wakeTimer = setTimeout(() => turn.waking(), 1500);
  let opened = false;
  const opening = () => { if(opened) return; opened = true; clearTimeout(wakeTimer); turn.settled(); };
  try {
    const res = await fetch("/api/stream", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ message:text, thread_id: threadId }) });
    opening();
    if(!res.ok){ const j = await res.json().catch(()=>({})); turn.fill(j.detail || "The demo is unavailable right now. Please try again."); return; }
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf="";
    while(true){
      const { value, done } = await reader.read(); if(done) break;
      buf += dec.decode(value, { stream:true });
      let i;
      while((i = buf.indexOf("\n\n")) >= 0){
        const line = buf.slice(0, i).trim(); buf = buf.slice(i+2);
        if(line.startsWith("data:")) handle(JSON.parse(line.slice(5).trim()), turn);
      }
    }
  } catch(e){ turn.fill("Sorry, the connection dropped. Please try again."); }
  finally { clearTimeout(wakeTimer); turn.done(); setBusy(false); }
}

function handle(ev, turn){
  switch(ev.type){
    case "thread": threadId = ev.thread_id; break;
    case "tool": turn.addTool(ev.name, ev.args); break;
    case "policy": turn.addPolicy(ev); break;
    case "tool_result": turn.finishTool(ev.name, ev.guardrail, ev.content); break;
    case "token": turn.token(ev.text); break;
    case "escalated": turn.hold(); turn.fill(escalationCopy(ev.review), {escalated:true}); break;
    case "error": turn.fill(ev.message); break;
  }
}

function autosize(){ input.style.height="auto"; input.style.height = Math.min(input.scrollHeight, 140)+"px"; }
input.addEventListener("input", () => { autosize(); updateSend(); });
input.addEventListener("keydown", e => { if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); submit(); } });
form.addEventListener("submit", e => { e.preventDefault(); submit(); });
document.getElementById("reset").addEventListener("click", resetChat);

renderEmpty();
