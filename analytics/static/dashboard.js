'use strict';
(() => {
  let token = '';
  let sites = [];
  const $ = (id) => document.getElementById(id);
  const status = (message, error = false) => { $('status').textContent = message; $('status').className = error ? 'status error' : 'status'; };
  const compact = (v) => new Intl.NumberFormat(undefined, {notation: 'compact', maximumFractionDigits: 1}).format(v || 0);
  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: {...options.headers, Authorization: `Bearer ${token}`}, cache: 'no-store' });
    if (!response.ok) throw new Error(`${response.status}: ${response.status === 401 ? 'Invalid administrator token' : 'Unable to load analytics data'}`);
    return response.json();
  }
  async function connect(e) {
    e.preventDefault(); token = $('auth-token').value.trim();
    try {
      sites = await api('/api/v1/sites');
      $('auth-token').value = '';
      $('auth-panel').hidden = true; $('workspace').hidden = false;
      setSites(); await refresh(); status('Connected. Analytics data stays in your control.');
    } catch (error) { token = ''; status(error.message, true); }
  }
  function setSites() {
    const picker = $('site-picker');
    const selected = picker.value;
    picker.replaceChildren();
    for (const site of sites) {const o = document.createElement('option');o.value = site.id;o.textContent = site.name;picker.append(o);}
    if (sites.some((s) => s.id === selected)) picker.value = selected;
  }
  function table(target, rows) {
    const root = $(target); root.replaceChildren();
    if (!rows.length) {const p = document.createElement('p');p.className='empty';p.textContent=target === 'goal-list' ? 'No conversion goals saved yet. Use the form to add one.' : 'No activity yet. Connect your tracking snippet to start collecting privacy-friendly insights.';root.append(p);return;}
    const total = Math.max(...rows.map(x => x.count), 1);
    for (const row of rows) {
      const div = document.createElement('div'); div.className='breakdown-row';
      const label = document.createElement('span');label.className='breakdown-label';label.textContent=row.label || '(direct / not set)';label.title=label.textContent;
      const count = document.createElement('strong');count.className='breakdown-count';count.textContent=compact(row.count);
      div.append(label, count); root.append(div);
    }
  }
  function chart(points) {
    const el = $('chart');el.replaceChildren();
    const values = points.map(p => Number(p.pageviews));
    const max = Math.max(...values, 1);
    if (!values.length) {const msg = document.createElement('p');msg.className='empty';msg.textContent='A visual history of your page views will appear here.';el.append(msg);return;}
    const w = 700, h = 180;
    const coords = values.map((v, i) => `${(i/(values.length-1 || 1))*w},${h-10-(v/max)*(h-30)}`).join(' ');
    // Coordinates come from numerical aggregations only. No dynamic HTML or unsafe SVG rendering.
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');svg.setAttribute('viewBox', `0 0 ${w} ${h}`);svg.setAttribute('aria-hidden','true');
    for (let i=0;i<4;i++) {const y = 10+i*(h-20)/3;const line=document.createElementNS(ns,'line');for(const [k,v] of Object.entries({x1:'0',x2:String(w),y1:String(y),y2:String(y),stroke:'#344057','stroke-dasharray':'4 8'}))line.setAttribute(k,v);svg.append(line);}
    const poly=document.createElementNS(ns,'polyline');for(const [k,v] of Object.entries({points:coords,fill:'none',stroke:'#b2a5ff','stroke-width':'4','stroke-linecap':'round','stroke-linejoin':'round'}))poly.setAttribute(k,v);svg.append(poly);el.append(svg);
    el.setAttribute('aria-label', `Daily page views: ${values.join(', ')}`);
  }
  async function refresh() {
    const site = sites.find(s => s.id === $('site-picker').value);
    if (!site) { $('active-site-name').textContent='Create your first website'; ['metric-pageviews','metric-visitors','metric-visits','metric-bounce','metric-live'].forEach(id => $(id).textContent='—');table('top-pages',[]);table('top-events',[]);table('goal-list',[]);chart([]);status('Add a website below to start tracking.');return; }
    $('active-site-name').textContent = site.name;
    status('Loading fresh analytics…');
    try {
      const url = `/api/v1/sites/${encodeURIComponent(site.id)}`;
      const [summary, timeseries, pages, events, live, goals] = await Promise.all([
        api(`${url}/summary`), api(`${url}/timeseries`), api(`${url}/breakdown?dimension=path`),
        api(`${url}/breakdown?dimension=name`), api(`${url}/realtime`), api(`${url}/goals`)]);
      $('metric-pageviews').textContent=compact(summary.pageviews);
      $('metric-visitors').textContent=compact(summary.visitors);
      $('metric-visits').textContent=compact(summary.visits);
      $('metric-bounce').textContent=`${summary.bounce_rate}%`;
      $('metric-live').textContent=compact(live.visitors);
      $('live-chip').innerHTML=''; const dot=document.createElement('i');$('live-chip').append(dot, document.createTextNode(' Live metrics'));
      chart(timeseries);table('top-pages',pages);table('top-events',events);
      table('goal-list', goals.map(g => ({label:`${g.name} · ${g.visit_conversion_rate}% of visits`,count:g.converting_visits})));
      status('Updated just now.');
    } catch (error) {status(error.message,true);}
  }
  async function createSite(e) {
    e.preventDefault();
    try {
      const response=await api('/api/v1/sites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('site-name').value,domains:[$('site-domain').value]})});
      sites=await api('/api/v1/sites');setSites();$('site-picker').value=response.id;
      const snippet=`<script defer src="${location.origin}/assets/tracker.js" data-site-id="${response.id}"></script>`;
      $('snippet-code').textContent=snippet;$('snippet').hidden=false;
      $('site-form').reset();await refresh();status('Website registered. Install the snippet to begin collection.');
    }catch(error){status(error.message,true);}
  }
  async function createGoal(e) {
    e.preventDefault();
    const site = $('site-picker').value;
    if (!site) {status('Register a website before creating a goal.',true);return;}
    try {
      await api(`/api/v1/sites/${encodeURIComponent(site)}/goals`,{
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:$('goal-name').value,kind:$('goal-kind').value,target:$('goal-target').value})
      });
      $('goal-form').reset(); await refresh(); status('Conversion goal saved.');
    } catch(error) {status(error.message,true);}
  }
  $('goal-form').addEventListener('submit',createGoal);
  $('auth-form').addEventListener('submit',connect);
  $('site-form').addEventListener('submit',createSite);
  $('site-picker').addEventListener('change',refresh);
  $('refresh').addEventListener('click',refresh);
  $('logout').addEventListener('click',()=>{token='';sites=[];$('workspace').hidden=true;$('auth-panel').hidden=false;status('Disconnected.');});
  $('copy-snippet').addEventListener('click',()=>{if(navigator.clipboard){navigator.clipboard.writeText($('snippet-code').textContent).then(()=>status('Snippet copied.')).catch(()=>status('Copy unavailable in this browser.',true));}});
  document.querySelectorAll('.nav-item').forEach(link=>link.addEventListener('click',(event)=>{
    if ($('workspace').hidden) {
      event.preventDefault();
      status('Connect to your analytics workspace before opening a report.');
      $('auth-token').focus();
      return;
    }
    document.querySelectorAll('.nav-item').forEach(item=>{
      item.classList.remove('active'); item.removeAttribute('aria-current');
    });
    link.classList.add('active'); link.setAttribute('aria-current','location');
  }));
})();
