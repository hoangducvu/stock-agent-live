const SVG_NS='http://www.w3.org/2000/svg';
const usd=value=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(value);

export function equityGeometry(raw,width=900,height=250){
  const byTime=new Map();
  for(const point of raw||[]){
    if(point.timestamp==null||point.equity==null||typeof point.timestamp==='boolean'||typeof point.equity==='boolean')continue;
    const timestamp=Number(point.timestamp),equity=Number(point.equity);
    if(Number.isFinite(timestamp)&&timestamp>0&&Number.isFinite(equity))byTime.set(timestamp,{timestamp,equity});
  }
  const points=[...byTime.values()].sort((a,b)=>a.timestamp-b.timestamp);
  if(!points.length)return {points:[],path:'',ticks:[]};
  const left=82,right=22,top=18,bottom=34;
  const values=points.map(p=>p.equity),minimum=Math.min(...values),maximum=Math.max(...values);
  const padding=Math.max((maximum-minimum)*.15,Math.abs(maximum)*.0002,.5);
  const low=minimum-padding,high=maximum+padding;
  const first=points[0].timestamp,last=points.at(-1).timestamp;
  const plotWidth=width-left-right,plotHeight=height-top-bottom;
  const mapped=points.map(p=>({...p,x:first===last?left+plotWidth/2:left+(p.timestamp-first)/(last-first)*plotWidth,
    y:top+(high-p.equity)/(high-low)*plotHeight}));
  const path=mapped.map((p,i)=>(i?'L':'M')+p.x.toFixed(2)+','+p.y.toFixed(2)).join(' ');
  return {points:mapped,path,width,height,left,right,top,bottom,
    area:path+` L${mapped.at(-1).x.toFixed(2)},${height-bottom} L${mapped[0].x.toFixed(2)},${height-bottom} Z`,
    ticks:[high,(high+low)/2,low].map(value=>({value,y:top+(high-value)/(high-low)*plotHeight}))};
}

export function drawEquityChart(svg,tooltip,raw,period='1M'){
  svg.replaceChildren();
  svg.removeAttribute('hidden');
  const geometry=equityGeometry(raw,Math.max(420,Math.min(1000,svg.clientWidth||900)),250);
  if(!geometry.points.length){svg.setAttribute('hidden','');tooltip.textContent='No account history is available yet.';return geometry;}
  const {points,width,height,left,right,bottom}=geometry;
  svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  svg.setAttribute('aria-label',`Account equity, ${period}. ${points.length} observations. Use left and right arrow keys to inspect values.`);
  const element=(tag,attributes={},text)=>{
    const node=document.createElementNS(SVG_NS,tag);
    for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));
    if(text!=null)node.textContent=text;
    svg.append(node);return node;
  };
  for(const tick of geometry.ticks){
    element('line',{x1:left,y1:tick.y,x2:width-right,y2:tick.y,class:'equity-grid'});
    element('text',{x:left-12,y:tick.y+4,'text-anchor':'end',class:'equity-axis'},usd(tick.value));
  }
  element('path',{d:geometry.area,class:'equity-area'});
  element('path',{d:geometry.path,class:'equity-line','vector-effect':'non-scaling-stroke'});
  const date=value=>new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',...(period==='1D'?{hour:'2-digit',minute:'2-digit'}:{})}).format(new Date(value*1000));
  const labels=points.length>1?[points[0],points.at(-1)]:[points[0]];
  for(let i=0;i<labels.length;i++)element('text',{x:labels[i].x,y:height-8,'text-anchor':labels.length===1?'middle':i?'end':'start',class:'equity-axis'},date(labels[i].timestamp));
  const guide=element('line',{x1:0,y1:geometry.top,x2:0,y2:height-bottom,class:'equity-guide'});
  const dot=element('circle',{r:4.5,cx:0,cy:0,class:'equity-point'});
  let selected=points.length-1;
  function select(index){
    selected=Math.max(0,Math.min(points.length-1,index));const point=points[selected];
    guide.setAttribute('x1',point.x);guide.setAttribute('x2',point.x);
    dot.setAttribute('cx',point.x);dot.setAttribute('cy',point.y);
    tooltip.textContent=usd(point.equity)+' · '+new Date(point.timestamp*1000).toLocaleString();
  }
  svg.onpointermove=event=>{
    const bounds=svg.getBoundingClientRect();if(!bounds.width)return;
    const x=(event.clientX-bounds.left)/bounds.width*width;
    let nearest=0;for(let i=1;i<points.length;i++)if(Math.abs(points[i].x-x)<Math.abs(points[nearest].x-x))nearest=i;
    select(nearest);
  };
  svg.onpointerleave=()=>select(points.length-1);
  svg.onkeydown=event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();select(event.key==='Home'?0:event.key==='End'?points.length-1:selected+(event.key==='ArrowLeft'?-1:1));
  };
  select(selected);return geometry;
}
