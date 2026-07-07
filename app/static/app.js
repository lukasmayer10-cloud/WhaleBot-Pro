let lastSignalKey = "";
let activeChartSymbol = "BTCUSDT";
let prevPrices = {};

function buttonFlash(btn){
  btn.classList.remove('clicked');
  void btn.offsetWidth;
  btn.classList.add('clicked');
  setTimeout(()=>btn.classList.remove('clicked'),430);
}

function setHTML(el, html){
  if(el && el.innerHTML !== html) el.innerHTML = html;
}

function showToast(title, body){
  const box=document.getElementById("toasts");
  if(!box) return;
  const el=document.createElement("div");
  el.className="toast";
  el.innerHTML=`<b>${title}</b><span>${body}</span>`;
  box.prepend(el);
  setTimeout(()=>el.remove(),4200);
}

function playPing(){
  try{
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine"; osc.frequency.value = 740; gain.gain.value = 0.045;
    osc.connect(gain); gain.connect(ctx.destination); osc.start();
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
    osc.stop(ctx.currentTime + 0.2);
  }catch(e){}
}

async function api(p,o={}){return fetch(p,o).then(r=>r.json())}
async function startBot(){await api('/api/start',{method:'POST'});refresh()}
async function stopBot(){await api('/api/stop',{method:'POST'});refresh()}
async function demoMarket(){demoBtn.classList.add('activeDemo');await api('/api/demo-market',{method:'POST'});refresh();setTimeout(()=>demoBtn.classList.remove('activeDemo'),900)}
async function saveSettings(){
  await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
    min_confidence:setConfidence.value, whale_usd_min:setWhale.value, position_size_usd:setSize.value
  })});refresh()
}

function money(x){return '$'+Number(x||0).toFixed(2)}
function cls(side){return (side==='BUY'||side==='LONG'||side==='BUY_WALL')?'buy':'sell'}

function setButtonState(running){
  if(running){
    startBtn.classList.add('activeRun'); stopBtn.classList.remove('activeStop');
    startBtn.classList.remove('inactive'); stopBtn.classList.add('inactive');
  }else{
    stopBtn.classList.add('activeStop'); startBtn.classList.remove('activeRun');
    stopBtn.classList.remove('inactive'); startBtn.classList.add('inactive');
  }
}

function setConfidence(score, side){
  const pct=Math.max(0,Math.min(99,Number(score||0)));
  confArc.style.strokeDashoffset=314-(314*pct/100);
  confNum.textContent=pct.toFixed(0)+'%';
  confSide.textContent=side||'WAIT';
}

function drawPriceChart(candles=[], markers=[], positions=[]){
  const c=document.getElementById('priceChart'), ctx=c.getContext('2d');
  c.width=c.clientWidth; c.height=280;
  ctx.clearRect(0,0,c.width,c.height);

  const padL=54, padR=16, padT=26, padB=26;
  const W=c.width-padL-padR, H=c.height-padT-padB;
  ctx.fillStyle='rgba(8,8,14,.96)'; ctx.fillRect(0,0,c.width,c.height);
  ctx.strokeStyle='rgba(157,78,221,.20)'; ctx.lineWidth=1;
  for(let i=0;i<6;i++){const y=padT+(H*i/5);ctx.beginPath();ctx.moveTo(padL,y);ctx.lineTo(c.width-padR,y);ctx.stroke()}

  const rows=(candles||[]).slice(-85).filter(k=>Number.isFinite(k.o)&&Number.isFinite(k.h)&&Number.isFinite(k.l)&&Number.isFinite(k.c));
  if(rows.length<6){
    ctx.strokeStyle='rgba(25,230,129,.85)';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(padL,c.height-padB);ctx.lineTo(c.width-padR,c.height-padB);ctx.stroke();
    ctx.fillStyle='#8d8aa7';ctx.fillText('Warte auf Live Candles...',padL,45);return;
  }

  let hi=Math.max(...rows.map(x=>x.h)), lo=Math.min(...rows.map(x=>x.l));
  positions.filter(p=>p.symbol===activeChartSymbol).forEach(p=>{hi=Math.max(hi,p.tp||hi,p.sl||lo);lo=Math.min(lo,p.tp||hi,p.sl||lo)});
  const span=(hi-lo)||1, step=W/rows.length, bodyW=Math.max(3,Math.min(9,step*.58));
  const y=(price)=>padT+(hi-price)/span*H, x=(i)=>padL+i*step+step/2;

  ctx.fillStyle='#8d8aa7';ctx.font='11px Segoe UI';
  for(let i=0;i<6;i++){const price=hi-(span*i/5), yy=padT+(H*i/5);ctx.fillText(price.toFixed(2),4,yy+4)}

  rows.forEach((k,i)=>{
    const xx=x(i), up=k.c>=k.o;
    ctx.strokeStyle=up?'rgba(25,230,129,.95)':'rgba(255,77,95,.95)';
    ctx.fillStyle=up?'rgba(25,230,129,.72)':'rgba(255,77,95,.72)';
    ctx.beginPath();ctx.moveTo(xx,y(k.h));ctx.lineTo(xx,y(k.l));ctx.stroke();
    const top=Math.min(y(k.o),y(k.c)), bh=Math.max(2,Math.abs(y(k.o)-y(k.c)));
    ctx.fillRect(xx-bodyW/2,top,bodyW,bh);
  });

  // EMA 20 / EMA 50
  function emaLine(period, color){
    if(rows.length<period) return;
    const vals=rows.map(r=>r.c), k=2/(period+1); let e=vals.slice(0,period).reduce((a,b)=>a+b,0)/period;
    ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();
    for(let i=period-1;i<vals.length;i++){
      if(i>period-1) e=vals[i]*k+e*(1-k);
      const xx=x(i), yy=y(e);
      if(i===period-1) ctx.moveTo(xx,yy); else ctx.lineTo(xx,yy);
    }
    ctx.stroke();
  }
  emaLine(20,'rgba(255,207,90,.8)');
  emaLine(50,'rgba(157,78,221,.8)');

  // SL/TP lines
  positions.filter(p=>p.symbol===activeChartSymbol).forEach(p=>{
    [['TP',p.tp,'rgba(25,230,129,.75)'],['SL',p.sl,'rgba(255,77,95,.75)']].forEach(([label,price,color])=>{
      ctx.strokeStyle=color;ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(padL,y(price));ctx.lineTo(c.width-padR,y(price));ctx.stroke();ctx.setLineDash([]);
      ctx.fillStyle=color;ctx.fillText(label,c.width-42,y(price)-4);
    });
  });

  const relevant=(markers||[]).filter(m=>!m.symbol || m.symbol===activeChartSymbol).slice(-16);
  relevant.forEach((m,idx)=>{
    const mi=Math.max(0, rows.length - 1 - (relevant.length-1-idx)*4);
    const xx=x(mi), price=Number.isFinite(m.price)?m.price:rows[mi].c, yy=y(Math.max(lo,Math.min(hi,price)));
    const isSell=m.side==='SHORT'||m.side==='SELL';
    ctx.fillStyle=m.type==='exit'?'rgba(255,207,90,.95)':m.type==='sl'?'rgba(255,77,95,.95)':m.type==='tp'?'rgba(25,230,129,.95)':isSell?'rgba(255,77,95,.95)':'rgba(25,230,129,.95)';
    ctx.beginPath();ctx.arc(xx,yy,5,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#f4efff';ctx.font='10px Segoe UI';
    const label=m.type==='entry'?'ENTRY':m.type==='cluster'?'CLUSTER':m.type==='exit'?'EXIT':m.type==='whale'?'🐋':m.type?.toUpperCase()||'SIG';
    ctx.fillText(label,xx+7,yy+4);
  });

  const last=rows[rows.length-1], prev=rows[rows.length-2]||last, change=((last.c-prev.c)/prev.c)*100;
  const yy=y(last.c);
  ctx.strokeStyle=change>=0?'rgba(25,230,129,.55)':'rgba(255,77,95,.55)';ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(padL,yy);ctx.lineTo(c.width-padR,yy);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle=change>=0?'#19e681':'#ff4d5f';ctx.font='13px Segoe UI';ctx.fillText(`${activeChartSymbol} ${last.c.toFixed(2)}  ${change>=0?'+':''}${change.toFixed(3)}%`,padL,padT-8);
}

function drawHeatmap(walls){
  const c=document.getElementById('heatmap'), ctx=c.getContext('2d');
  c.width=c.clientWidth; c.height=220; ctx.clearRect(0,0,c.width,c.height);
  if(!walls||walls.length===0){ctx.fillStyle='#8d8aa7';ctx.fillText('Noch keine Orderbook Walls...',20,40);return}
  const max=Math.max(...walls.map(w=>w.value));
  walls.slice(0,16).forEach((w,i)=>{
    const width=(w.value/max)*(c.width-125), y=10+i*13, isBuy=w.side==='BUY_WALL';
    const grad=ctx.createLinearGradient(95,y,95+width,y);
    grad.addColorStop(0,isBuy?'rgba(25,230,129,.25)':'rgba(255,77,95,.25)');
    grad.addColorStop(1,isBuy?'rgba(25,230,129,.85)':'rgba(255,77,95,.85)');
    ctx.fillStyle=grad;ctx.shadowBlur=8;ctx.shadowColor=isBuy?'rgba(25,230,129,.55)':'rgba(255,77,95,.55)';
    ctx.fillRect(95,y,width,9);ctx.shadowBlur=0;ctx.fillStyle='#f4efff';ctx.font='11px Segoe UI';ctx.fillText(w.symbol,8,y+9);
  });
}

function renderOrbitCoins(prices, radarData, priceChange){
  const symbols=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','DOGEUSDT'];
  const positions=[{x:82,y:45},{x:72,y:72},{x:50,y:76},{x:24,y:48},{x:32,y:24},{x:74,y:24}];
  const html=symbols.map((sym,i)=>{
    const r=radarData[sym], hot=r?'hot':'', score=r?.score||0, label=sym.replace('USDT',''), ch=priceChange?.[sym]||0;
    const price=prices[sym]?Number(prices[sym]).toFixed(label==='DOGE'?5:2):'watching';
    return `<div class="orbitCoin ${hot}" style="left:${positions[i].x}%;top:${positions[i].y}%;">
      <strong>${label}</strong><small>${score?score+'%':price}</small>${r?`<em>${r.side}</em>`:`<em class="${ch>=0?'positive':'negative'}">${ch>=0?'+':''}${ch.toFixed(2)}%</em>`}</div>`;
  }).join('');
  setHTML(orbitCoins, html);
}

function confBars(scores={}){
  const keys=['whale','cluster','wall','momentum','trend','rsi','macd','volume','volatility'];
  const html=keys.map(k=>{
    const v=scores[k]||0;
    return `<div class="confRow"><span>${k}</span><div class="confTrack"><div class="confFill" style="width:${v}%"></div></div><b>${v}%</b></div>`;
  }).join('');
  setHTML(confidenceBars, html);
}


function renderAI(aiDecisions){
  const rows = Object.entries(aiDecisions || {})
    .sort((a,b)=>(b[1].score||0)-(a[1].score||0))
    .slice(0,4);

  if(!rows.length){
    setHTML(aiPanel, "Warte auf AI-Daten...");
    return;
  }

  const html = rows.map(([sym,a])=>{
    const scores = a.scores || {};
    const keys = ['whale','cluster','wall','momentum','trend','rsi','macd','volume','volatility'];
    return `<div class="aiCoin">
      <b>${sym}</b><span class="aiScore">${a.score||0}%</span><br>
      <span class="aiStatus">${a.side||'WATCH'} · ${a.status||'WATCH'}</span>
      <div class="aiGrid">
        ${keys.map(k=>`<div class="aiRow"><span>${k}</span><div class="aiTrack"><div class="aiFill" style="width:${scores[k]||0}%"></div></div><b>${scores[k]||0}</b></div>`).join('')}
      </div>
    </div>`;
  }).join('');
  setHTML(aiPanel, html);
}




function renderNextAction(source, config){
  let box = document.getElementById("nextActionBox");
  if(!box){
    const sig = document.getElementById("signal");
    if(sig){
      box = document.createElement("div");
      box.id = "nextActionBox";
      box.className = "nextActionBox";
      sig.insertAdjacentElement("afterend", box);
    }
  }
  if(!box) return;

  if(!source){
    setHTML(box, `<div class="nextActionGrid">
      <div>Next Action<b>WAIT</b></div>
      <div>Status<b>NO DATA</b></div>
      <div>Trend<b>--</b></div>
    </div>`);
    return;
  }

  const score = source.quality || source.score || 0;
  const action = source.action || (score >= 85 ? "PAPER_TRADE" : score >= 70 ? "PREPARE" : "WATCH");
  const trend = source.trend || (source.rising ? "RISING" : "STABLE");
  const risk = source.risk_ok === false ? "BLOCKED" : "OK";

  setHTML(box, `<div class="nextActionGrid">
    <div>Next Action<b>${action}</b></div>
    <div>Risk<b>${risk}</b></div>
    <div>Trend<b>${trend}</b></div>
  </div>`);
}

function aiReasonHTML(a){
  const scores = a?.scores || {};
  const checks = [];
  if((scores.whale||0) >= 70) checks.push("✓ Whale Cluster");
  if((scores.wall||0) >= 70) checks.push("✓ Wall");
  if((scores.rsi||0) >= 70) checks.push("✓ RSI");
  if((scores.macd||0) >= 70) checks.push("✓ MACD");
  if((scores.trend||0) >= 70) checks.push("✓ Trend");
  if((scores.momentum||0) >= 70) checks.push("✓ Momentum");
  if(!checks.length) checks.push("watching");
  return `<div class="aiReason">${checks.map(x=>`<span>${x}</span>`).join('')}<br>Decision: <b>${a?.side||'WATCH'}</b></div>`;
}


function statusBadge(status){
  const s = (status || 'WATCH').replace(' ', '_');
  return `<span class="statusBadge ${s}">${s}</span>`;
}

function renderConfidenceTrend(source){
  let el = document.getElementById("confTrend");
  const signalBox = document.getElementById("signal");
  if(!el && signalBox){
    el = document.createElement("div");
    el.id = "confTrend";
    el.className = "confTrend";
    signalBox.insertAdjacentElement("afterend", el);
  }
  if(!el) return;
  if(!source){
    setHTML(el, `<div>Next<b>WAIT</b></div><div>Trend<b>--</b></div><div>Risk<b>--</b></div>`);
    return;
  }
  const score = source.quality || source.score || 0;
  const action = source.action || (score>=85?'PAPER_TRADE':score>=70?'PREPARE':'WATCH');
  const trend = source.trend || (source.rising ? 'RISING' : 'STABLE');
  const risk = source.risk_ok === false ? 'BLOCKED' : 'OK';
  setHTML(el, `<div>Next<b>${action}</b></div><div>Trend<b>${trend}</b></div><div>Risk<b>${risk}</b></div>`);
}

function aiReasonHTML(a){
  const scores = a?.scores || {};
  const checks = [];
  if((scores.whale||0) >= 70) checks.push("✓ Whale");
  if((scores.cluster||0) >= 70) checks.push("✓ Cluster");
  if((scores.wall||0) >= 70) checks.push("✓ Wall");
  if((scores.rsi||0) >= 70) checks.push("✓ RSI");
  if((scores.macd||0) >= 70) checks.push("✓ MACD");
  if((scores.momentum||0) >= 70) checks.push("✓ Momentum");
  if(!checks.length) checks.push("watching");
  return `<div class="aiReason">${checks.map(x=>`<span>${x}</span>`).join('')}<br>Decision: <b>${a?.side||'WATCH'}</b></div>`;
}


function renderActionPipeline(action){
  let el = document.getElementById("actionPipeline");
  const signalBox = document.getElementById("signal");
  if(!el && signalBox){
    el = document.createElement("div");
    el.id = "actionPipeline";
    el.className = "actionPipeline";
    signalBox.insertAdjacentElement("afterend", el);
  }
  if(!el) return;
  const steps = ["WAIT","PREPARE","READY","ENTER","MANAGE","EXIT"];
  let active = "WAIT";
  if(action === "PREPARE") active = "PREPARE";
  if(action === "PAPER_TRADE") active = "READY";
  if(action === "LIVE") active = "ENTER";
  setHTML(el, steps.map(s=>`<span class="actionStep ${s===active?'active':''}">${s}</span>`).join(""));
}

function statePipelineHTML(action){
  const steps = ["WAIT","PREPARE","READY","ENTRY","MANAGE","EXIT"];
  let active = "WAIT";
  if(action === "PREPARE") active = "PREPARE";
  if(action === "PAPER_TRADE") active = "READY";
  if(action === "LIVE") active = "ENTRY";
  return `<div class="statePipeline">${steps.map(s=>`<span class="statePipeStep ${s===active?'active':''}">${s}</span>`).join("")}</div>`;
}

function platformMonitorHTML(p){
  return `<div class="systemRows">
    <div>AI Engine<b>ONLINE</b></div>
    <div>Scanner<b>ONLINE</b></div>
    <div>Risk<b>ONLINE</b></div>
    <div>Exchange<b>${p?.exchange?.enabled?'KEYS':'OFFLINE'}</b></div>
    <div>Latency<b>${document.getElementById('latency')?.textContent||'--'}</b></div>
    <div>Trading<b>PAPER</b></div>
  </div>`;
}

async function refreshCore(){
  try{
    const c = await api('/api/core');
    const setups = c.setups || [];
    if(!setups.length){
      setHTML(corePanel, "Warte auf Core Setups...");
      renderNextAction(null, {});
      renderConfidenceTrend(null);
      renderActionPipeline('WAIT');
      return;
    }
    const html = setups.slice(0,8).map(s=>{
      const p=s.plan||{};
      const cls=s.action==="PAPER_TRADE"?"trade":s.action==="PREPARE"?"prepare":"";
      const hist=(s.history||[]).slice(-6).map((h,i,arr)=>{
        const prev=i?arr[i-1].quality:h.quality;
        const trend=h.quality>prev?'up':h.quality<prev?'down':'';
        return `<span class="point ${trend}">${h.ts} ${h.quality}%</span>`;
      }).join('');
      return `<div class="coreSetup ${cls}">
        <div class="coreHead">
          <b>${s.side} ${s.symbol}</b>
          ${statusBadge(s.action)}
        </div>
        <div class="coreGrid">
          <div class="coreMetric">Quality<b>${s.quality}%</b></div>
          <div class="coreMetric">Entry<b>${Number(p.entry||0).toFixed(4)}</b></div>
          <div class="coreMetric">SL<b>${Number(p.sl||0).toFixed(4)}</b></div>
          <div class="coreMetric">TP1<b>${Number(p.tp1||0).toFixed(4)}</b></div>
          <div class="coreMetric">TP2<b>${Number(p.tp2||0).toFixed(4)}</b></div>
          <div class="coreMetric">RR<b>${p.rr||0}</b></div>
          <div class="coreMetric">Size<b>$${Number(p.size_usd||0).toFixed(2)}</b></div>
          <div class="coreMetric">Risk<b>${s.risk_ok?'OK':'BLOCK'}</b></div>
        </div>
        <div class="coreExplain">${(s.explain||[]).join(' · ')}</div>${statePipelineHTML(s.action)}
        <div class="coreHistory"><b>Score History:</b><br>${hist || 'noch keine Änderungen'}</div>
      </div>`;
    }).join('');
    setHTML(corePanel, html);
    renderNextAction(setups[0], {});
    renderConfidenceTrend(setups[0]);
    renderActionPipeline(setups[0]?.action);
  }catch(e){}
}

async function refreshPlatform(){
  try{
    const p = await api('/api/platform');
    const html = `
      <div class="platformBox">
        <b>Execution</b><br>
        ${p.platform.execution_mode.toUpperCase()} · Live ${p.platform.live_enabled ? 'ON' : 'OFF'} · Testnet ${p.platform.testnet_enabled ? 'ON' : 'OFF'}
      </div>
      <div class="platformGrid">
        <div class="platformMetric">Exchange<span>${p.exchange.mode || 'testnet'} / ${p.exchange.enabled ? 'keys ok' : 'no keys'}</span></div>
        <div class="platformMetric">Orders<span>${p.exchange.allow_trading ? 'enabled' : 'safe disabled'}</span></div>
        <div class="platformMetric">Imbalance<span>${p.orderflow.imbalance}%</span></div>
        <div class="platformMetric">Profit Factor<span>${p.analytics.profit_factor}</span></div>
        <div class="platformMetric">Trades<span>${p.analytics.total_trades}</span></div>
        <div class="platformMetric">Max DD<span>${money(p.analytics.max_drawdown)}</span></div>
      </div>`;
    setHTML(platformPanel, html);
  }catch(e){}
}


function renderTradePlanSafe(sigOrAI, config){
  const el = document.getElementById("tradePlan");
  if(!el) return;
  if(!sigOrAI || !sigOrAI.symbol){
    setHTML(el, "Kein aktiver Trade Plan");
    return;
  }
  const prices = window.__lastPrices || {};
  const entry = Number(sigOrAI.price || prices[sigOrAI.symbol] || 0);
  if(!entry){
    setHTML(el, "Warte auf Entry-Daten...");
    return;
  }
  const side = sigOrAI.side || "WATCH";
  const slPct = Number(config?.stop_loss_pct || 0.8);
  const tpPct = Number(config?.take_profit_pct || 1.4);
  const size = Number(config?.position_size_usd || 50);
  let sl, tp;
  if(side === "SHORT"){
    sl = entry * (1 + slPct/100);
    tp = entry * (1 - tpPct/100);
  }else{
    sl = entry * (1 - slPct/100);
    tp = entry * (1 + tpPct/100);
  }
  const rr = Math.abs(tp-entry) / Math.max(0.000001, Math.abs(entry-sl));
  setHTML(el, `<b>${side} ${sigOrAI.symbol}</b> · Score <b class="positive">${sigOrAI.score||0}%</b>
    <div class="tradePlanGrid">
      <div>Entry<b>${entry.toFixed(4)}</b></div>
      <div>Position<b>$${size.toFixed(2)}</b></div>
      <div>Stop Loss<b>${sl.toFixed(4)}</b></div>
      <div>Take Profit<b>${tp.toFixed(4)}</b></div>
      <div>Risk<b>${slPct.toFixed(2)}%</b></div>
      <div>RR<b class="tradeRR">1 : ${rr.toFixed(2)}</b></div>
    </div>`);
}

function renderEngineStatusSafe(s){
  const el = document.getElementById("engineStatus");
  if(!el) return;
  const online = s.running || (s.system?.stream === "LIVE");
  const html = `
    <div><span class="led ${Object.keys(s.ai_decisions||{}).length?'on':'warn'}"></span> AI Engine</div>
    <div><span class="led ${online?'on':'off'}"></span> Scanner</div>
    <div><span class="led on"></span> Risk Engine</div>
    <div><span class="led ${s.system?.api==='PUBLIC'?'warn':'on'}"></span> Exchange</div>
    <div><span class="led on"></span> Analytics</div>`;
  setHTML(el, html);
}


function fmtDur(sec){
  sec=Number(sec||0);
  const m=Math.floor(sec/60), s=sec%60;
  return `${m}m ${s}s`;
}


function managerHTML(p){
  const m = p.manager || {};
  return `<div class="managerBox">
    <span class="managerFlag ${m.break_even?'on':''}">BE</span>
    <span class="managerFlag ${m.tp1?'on':''}">TP1</span>
    <span class="managerFlag ${m.trailing?'on':''}">TRAIL</span>
    <span class="managerFlag ${m.tp2?'on':''}">TP2</span>
  </div>
  <div class="managerAction">Manager: ${m.last_action || p.state || 'MANAGE'} · RR now ${p.rr_now ?? p.rr ?? 0}</div>`;
}

function renderPositionsV2(positions){
  if(!positions || !positions.length){
    setHTML(positionsEl || positions, "");
    const el=document.getElementById("positions");
    if(el) setHTML(el, "Keine offenen Positionen");
    return;
  }
  const html=positions.map(p=>{
    const pnl=Number(p.pnl||0);
    const cls=pnl>=0?'win':'loss';
    return `<div class="positionCard ${cls}">
      <div class="posHead">
        <b>${p.side} ${p.symbol}</b>
        <button class="closeBtn" onclick="closePosition(${p.id})">Close</button>
      </div>
      <div class="posGrid">
        <div class="posMetric">Entry<b>${Number(p.entry||0).toFixed(4)}</b></div>
        <div class="posMetric">Current<b>${Number(p.current||0).toFixed(4)}</b></div>
        <div class="posMetric">PnL<b class="${pnl>=0?'pnlPos':'pnlNeg'}">${money(pnl)}</b></div>
        <div class="posMetric">SL<b>${Number(p.sl||0).toFixed(4)}</b></div>
        <div class="posMetric">TP<b>${Number(p.tp||0).toFixed(4)}</b></div>
        <div class="posMetric">Duration<b>${fmtDur(p.duration_sec)}</b></div>
        <div class="posMetric">Fees<b>${money(p.fees||0)}</b></div>
        <div class="posMetric">RR<b>${p.rr||0}</b></div>
        <div class="posMetric">State<b>${p.state||'MANAGE'}</b></div>
      </div>
    </div>`;
  }).join('');
  const el=document.getElementById("positions");
  if(el) setHTML(el, html);
}

function renderClosedV2(closed){
  const el=document.getElementById("closed");
  if(!el) return;
  if(!closed || !closed.length){
    setHTML(el, "");
    return;
  }
  const html=closed.slice(0,8).map(t=>{
    const pnl=Number(t.pnl||0);
    const cls=pnl>=0?'win':'loss';
    return `<div class="closedCard ${cls}">
      <div class="posHead"><b>${t.side} ${t.symbol}</b><span>${t.close_reason||'EXIT'}</span></div>
      <div class="posGrid">
        <div class="posMetric">PnL<b class="${pnl>=0?'pnlPos':'pnlNeg'}">${money(pnl)}</b></div>
        <div class="posMetric">Entry<b>${Number(t.entry||0).toFixed(4)}</b></div>
        <div class="posMetric">Exit<b>${Number(t.current||0).toFixed(4)}</b></div>
        <div class="posMetric">Fees<b>${money(t.fees||0)}</b></div>
        <div class="posMetric">Duration<b>${fmtDur(t.duration_sec)}</b></div>
        <div class="posMetric">RR<b>${t.rr||0}</b></div>
      </div>
    </div>`;
  }).join('');
  setHTML(el, html);
}

async function refresh(){
  const s=await api('/api/state');

  window.__lastPrices = s.prices || {};
  const chartLegend=document.getElementById('chartLegend');
  if(chartLegend){chartLegend.innerHTML='<span>🐋 Whale</span><span>◎ Cluster</span><span class="entry">Entry</span><span class="sl">SL</span><span class="tp">TP</span><span>AI</span>';}
  status.textContent=s.running?'RUNNING':'STOPPED'; setButtonState(s.running); modeText.textContent=(s.mode||'paper').toUpperCase();
  renderEngineStatusSafe(s);
  mStream.textContent=s.system?.stream||'OFF'; mPing.textContent=(s.system?.ping_ms||0)+'ms'; mLatency.textContent=(s.system?.latency_ms||0)+'ms'; mFps.textContent=s.system?.fps||60; mApi.textContent=s.system?.api||'PUBLIC';

  balance.textContent=money(s.balance); equity.textContent=money(s.equity); pnl.textContent=money(s.daily_pnl); pnl.className=s.daily_pnl>=0?'win':'loss';
  winrate.textContent=s.winrate.toFixed(1)+'%'; whales.textContent=s.stats.whales_seen; clusters.textContent=s.stats.clusters; open.textContent=s.positions.length;

  if(String(setConfidence.value)!==String(s.config.min_confidence)) setConfidence.value=s.config.min_confidence;
  if(String(setWhale.value)!==String(s.config.whale_usd_min)) setWhale.value=s.config.whale_usd_min;
  if(String(setSize.value)!==String(s.config.position_size_usd)) setSize.value=s.config.position_size_usd;

  renderOrbitCoins(s.prices||{},s.radar||{},s.price_change||{});
  renderAI(s.ai_decisions||{});

  setHTML(radar, Object.entries(s.radar).map(([sym,r])=>`<div class="radarCard"><b>${sym}</b><span class="score">${r.score}%</span><br><span class="${r.side==='LONG'?'long':r.side==='SHORT'?'short':''}">${r.side}</span><div class="bar"><div style="width:${r.score}%"></div></div><small>${r.reason}</small></div>`).join('') || '<div class="radarCard">Noch keine Radar-Daten</div>');

  const priceHtml=Object.entries(s.prices).map(([k,v])=>{
    const t=s.last_price_update?.[k]||'', ch=s.price_change?.[k]||0, prev=prevPrices[k], flash=prev? v>prev?'flashUp':v<prev?'flashDown':'':'';
    prevPrices[k]=v;
    return `<div class="price ${flash}"><b>${k}</b><span>${Number(v).toFixed(4)} <small class="${ch>=0?'positive':'negative'}">${ch>=0?'+':''}${ch.toFixed(3)}%</small> <small>${t}</small></span></div>`;
  }).join('')||'Noch keine Preise';
  setHTML(prices, priceHtml);

  setHTML(timeline, s.timeline.map(t=>`<div class="timeitem"><span class="badge">${t.level}</span>${t.ts} — <b>${t.event}</b> ${t.symbol}<br><small>${t.detail}</small></div>`).join('')||'Noch keine Timeline');

  setHTML(whaleCards, s.whales.slice(0,10).map(w=>`<div class="whaleCard"><b class="${cls(w.side)}">🐋 ${w.side}</b><span class="score">${w.confidence}%</span><br><b>${w.symbol}</b><div class="value">${money(w.value)}</div><small>${w.ts} @ ${Number(w.price).toFixed(4)}</small></div>`).join('')||'Noch keine Whales');

  const sig=s.signals[0];
  if(sig){
    const key=`${sig.ts}-${sig.symbol}-${sig.side}-${sig.score}`;
    if(key!==lastSignalKey){lastSignalKey=key;playPing();showToast('🐋 WhaleBot 2.0 Signal',`${sig.symbol} ${sig.side} ${sig.score}%`)}
    setConfidence(sig.score,sig.side); confBars(sig.detail_scores||{});
    renderTradePlanSafe(sig,s.config);
    renderNextAction(sig,s.config);
    renderConfidenceTrend(sig);
    setHTML(signal,`<b class="${sig.side==='LONG'?'long':'short'}">${sig.side} ${sig.symbol}</b><span class="score">${sig.score}%</span><br>${sig.reason}<br>Risk: <b>${sig.risk||'MEDIUM'}</b><br><br><span class="stars">Whale ${sig.stars?.whale||''}</span><br><span class="stars">Cluster ${sig.stars?.cluster||''}</span><br><span class="stars">Wall ${sig.stars?.wall||''}</span><br><span class="stars">Momentum ${sig.stars?.momentum||''}</span><br><span class="stars">RSI ${sig.stars?.rsi||''}</span><br><span class="stars">MACD ${sig.stars?.macd||''}</span>`);
  }else{
    const bestAI = Object.entries(s.ai_decisions||{}).sort((a,b)=>(b[1].score||0)-(a[1].score||0))[0]?.[1];
    if(bestAI){
      setConfidence(bestAI.score||0,bestAI.side||'WATCH');
      confBars(bestAI.scores||{});
      renderTradePlanSafe(bestAI,s.config);
      renderNextAction(bestAI,s.config);
      renderConfidenceTrend(bestAI);
      setHTML(signal,`<b>${bestAI.side||'WATCH'} ${bestAI.symbol||''}</b><span class="score">${bestAI.score||0}%</span><br>${bestAI.reason||'AI Watch Mode'}<br>Status: <b>${bestAI.status||'WATCH'}</b>`);
    }else{
      setConfidence(0,'WAIT');confBars({});setHTML(signal,'Warte auf AI-Daten...');renderTradePlanSafe(null,s.config);
    }
  }

  setHTML(clusterRows, s.clusters.map(c=>`<div class="row"><b>${c.symbol}</b> <span class="${cls(c.side)}">${c.side}</span><span class="score">${c.score}%</span><br>${c.count} Whales | ${money(c.value)} | Wall ${money(c.wall_value||0)}<br>Risk ${c.risk||''}</div>`).join('')||'Noch keine Cluster');

  setHTML(positions, s.positions.map(p=>{const pct=Math.min(100,Math.abs(p.pnl)/(p.size_usd*0.03)*100);return `<div class="pos"><b>${p.symbol} <span class="${p.side==='LONG'?'long':'short'}">${p.side}</span></b><span class="score">${p.score}%</span><br>Entry ${p.entry.toFixed(4)} | Mark ${p.mark.toFixed(4)}<br>PnL <span class="${p.pnl>=0?'win':'loss'}">${money(p.pnl)}</span><div class="posBar"><div style="width:${pct}%"></div></div>SL ${p.sl.toFixed(4)} | TP ${p.tp.toFixed(4)}<br><button class="actionBtn small" onclick="buttonFlash(this);fetch('/api/close/${p.id}',{method:'POST'}).then(refresh)">Close</button></div>`}).join('')||'Keine offenen Positionen');

  setHTML(closed, s.closed.map(p=>`<div class="row"><b>${p.symbol}</b> ${p.side} | <span class="${p.pnl>=0?'win':'loss'}">${money(p.pnl)}</span> | ${p.close_reason}</div>`).join('')||'Noch keine geschlossenen Trades');
  setHTML(logs, s.logs.map(l=>`<div class="log"><span class="badge">${l.level}</span>${l.ts} — ${l.msg}</div>`).join(''));

  drawPriceChart(s.candles?.[activeChartSymbol]||[], s.chart_markers||[], s.positions||[]);
  drawHeatmap(s.walls||[]);
  renderPositionsV2(s.positions||[]);
  renderClosedV2(s.closed||[]);
  refreshPlatform();
  refreshCore();
}

setInterval(refresh,2000);
refresh();
