(()=>{
  const form=document.getElementById('bookingForm'); if(!form) return;
  const steps=[...document.querySelectorAll('.wizard-step')]; let step=1;
  const state={vehicleType:'',category:'',services:[],extras:[],conditionsList:[],service:null,extraIds:new Set(),conditionIds:new Set(),slot:'',calendarDate:new Date()};
  const $=id=>document.getElementById(id);
  const paymentText=()=>form.querySelector('input[name="payment_method"]:checked')?.dataset.label||'Não selecionada';
  const categoryLabel=()=>state.category==='moto'?'Moto':state.category==='car_large'?'Carro grande':state.category==='car_small'?'Carro pequeno/médio':'—';
  const vehicleCatalog=window.PHVehicleCatalog?.attach({
    vehicleType:'car', brandSearch:'brandSearch', brandValue:'brand', brandId:'brandCatalogId', brandMenu:'brandSuggestions', brandHelp:'brandHelp',
    modelSearch:'modelSearch', modelValue:'model', modelId:'modelCatalogId', modelMenu:'modelSuggestions', modelHelp:'modelHelp',
    manualToggle:'manualVehicleToggle', status:'vehicleCatalogStatus',
    onModelSelected:item=>{
      if(state.vehicleType==='car'&&item.suggested_category&&item.suggested_category!==state.category){
        $('vehicleCatalogStatus').textContent=`Referência do catálogo: este modelo costuma ser classificado como ${item.suggested_category==='car_large'?'carro grande':'carro pequeno/médio'}. Você pode manter a categoria escolhida se ela estiver correta para o veículo.`;
      }
      updateMiniSummary(); updateNextButton();
    }
  });

  function updateMiniSummary(){
    const el=$('bookingMiniSummary'); if(!el) return;
    const vehicle=[($('brand')?.value||'').trim(),($('model')?.value||'').trim()].filter(Boolean).join(' ');
    const items=[];
    if(state.vehicleType) items.push(`<span><small>VEÍCULO</small><strong>${vehicle||categoryLabel()}</strong></span>`);
    if(state.service) items.push(`<span><small>SERVIÇO</small><strong>${state.service.name}</strong></span>`);
    if(state.service) items.push(`<span><small>VALOR</small><strong class="gold-text">${PH.brl(state.service.price)}</strong></span>`);
    if($('appointmentDate')?.value) items.push(`<span><small>DATA</small><strong>${formatDateBR($('appointmentDate').value)}</strong></span>`);
    if(state.slot) items.push(`<span><small>HORÁRIO</small><strong>${state.slot}</strong></span>`);
    el.innerHTML=items.join(''); el.hidden=!items.length;
  }

  function updateNextButton(){
    const btn=$('nextBtn'); if(!btn || step===11) return;
    let enabled=true;
    if(step===1) enabled=!!state.vehicleType;
    if(step===2 && state.vehicleType==='car') enabled=!!state.category;
    if(step===3) enabled=!!(($('brand')?.value||'').trim()&&($('model')?.value||'').trim());
    if(step===4) enabled=!!state.service;
    if(step===8) enabled=!!$('appointmentDate').value;
    if(step===9) enabled=!!state.slot;
    if(step===10) enabled=!!(($('customerName').value||'').trim()&&($('phone').value||'').trim()&&form.querySelector('input[name="payment_method"]:checked'));
    btn.disabled=!enabled;
    btn.setAttribute('aria-disabled',String(!enabled));
  }

  const show=n=>{
    step=Math.max(1,Math.min(11,n));
    steps.forEach(s=>s.classList.toggle('active',Number(s.dataset.step)===step));
    $('progressBar').style.width=`${step/11*100}%`;
    $('stepLabel').textContent=`Etapa ${step} de 11`;
    $('prevBtn').style.visibility=step===1?'hidden':'visible';
    $('nextBtn').style.display=step===11?'none':'inline-flex';
    window.scrollTo({top:0,behavior:'smooth'});
    if(step===8 && !$('calendarPopover').hidden) renderCalendar();
    if(step===9) loadSlots();
    if(step>=10) renderSummary();
    updateMiniSummary(); updateNextButton();
  };

  const next=async()=>{
    if(step===1&&!state.vehicleType)return alert('Escolha carro ou moto.');
    if(step===2&&state.vehicleType==='car'&&!state.category)return alert('Escolha o porte do carro.');
    if(step===3){
      const check=vehicleCatalog?.validate?.()||{ok:!!($('brand').value.trim()&&$('model').value.trim()),message:'Informe marca e modelo.'};
      if(!check.ok)return alert(check.message);
      await loadServices();
    }
    if(step===4&&!state.service)return alert('Escolha um serviço.');
    if(step===8&&!$('appointmentDate').value)return alert('Escolha a data no calendário.');
    if(step===9&&!state.slot)return alert('Escolha um horário disponível.');
    if(step===10){
      if(!$('customerName').value.trim()||!$('phone').value.trim())return alert('Informe nome e WhatsApp.');
      if(!form.querySelector('input[name="payment_method"]:checked'))return alert('Escolha uma forma de pagamento disponível.');
    }
    show(step+1);
  };

  $('nextBtn').addEventListener('click',next);
  $('prevBtn').addEventListener('click',()=>show(step-1));
  ['brandSearch','modelSearch','customerName','phone'].forEach(id=>$(id)?.addEventListener('input',()=>{updateMiniSummary();updateNextButton()}));

  document.querySelectorAll('[data-vehicle]').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('[data-vehicle]').forEach(x=>x.classList.remove('selected'));
    b.classList.add('selected');
    state.vehicleType=b.dataset.vehicle;
    $('vehicleType').value=state.vehicleType;
    vehicleCatalog?.setVehicleType(state.vehicleType);
    state.service=null; state.extraIds.clear(); state.conditionIds.clear(); state.slot='';
    clearAppointmentDate();
    if(state.vehicleType==='moto'){
      state.category='moto'; $('category').value='moto'; $('engineField').style.display='grid'; show(3);
    }else{
      state.category=''; $('category').value=''; $('engineField').style.display='none'; show(2);
    }
  });

  document.querySelectorAll('[data-category]').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('[data-category]').forEach(x=>x.classList.remove('selected'));
    b.classList.add('selected');
    state.category=b.dataset.category; $('category').value=state.category;
    state.service=null; state.extraIds.clear(); state.conditionIds.clear(); state.slot=''; clearAppointmentDate();
    show(3);
  });

  async function loadServices(){
    const r=await fetch(`/api/services?category=${encodeURIComponent(state.category)}`);
    const data=await r.json();
    state.services=data.services||[]; state.extras=data.extras||[]; state.conditionsList=data.conditions||[];
    renderServices(); renderExtras(); renderConditions();
    if(window.BOOKING_PREFILL?.service_id){
      const btn=[...document.querySelectorAll('.service-card')].find(x=>String(x.dataset.serviceId)===String(window.BOOKING_PREFILL.service_id));
      if(btn)btn.click();
    }
  }

  function serviceIcon(name){
    if(/motor/i.test(name)) return '◆';
    if(/completa/i.test(name)) return '✦';
    if(/detalhada/i.test(name)) return '◇';
    return '◈';
  }

  function renderServices(){
    const g=$('servicesGrid'); g.innerHTML=''; state.service=null; $('serviceId').value='';
    state.services.forEach(s=>{
      const d=document.createElement('button'); d.type='button'; d.className='service-card'; d.dataset.serviceId=s.id;
      d.innerHTML=`<span class="service-selected-mark" aria-hidden="true">✓</span><div class="service-card-top"><span class="pill">${state.category==='moto'?'MOTO':state.category==='car_large'?'CARRO GRANDE':'CARRO PEQ./MÉDIO'}</span><span class="service-icon">${serviceIcon(s.name)}</span></div><h3>${s.name}</h3><div class="price">${PH.brl(s.price)}</div><p>${s.description||''}</p><span class="duration-badge">◷ ${s.duration_minutes?`${s.duration_minutes} min`:'Duração a definir'}</span>`;
      d.onclick=()=>{
        state.service=s; $('serviceId').value=s.id; state.slot=''; $('appointmentTime').value=''; clearAppointmentDate();
        [...g.children].forEach(x=>x.classList.remove('selected')); d.classList.add('selected');
        updateTotal(); updateRecommendation(); updateMiniSummary(); updateNextButton();
      };
      g.appendChild(d);
    });
    updateNextButton();
  }

  function renderExtras(){
    const g=$('extrasGrid'); g.innerHTML=''; state.extraIds.clear(); $('extrasInput').value='';
    if(!state.extras.length){g.innerHTML='<div class="notice">Nenhum adicional cadastrado para esta categoria.</div>'; updateTotal(); return;}
    state.extras.forEach(e=>{
      const l=document.createElement('label'); l.className='check';
      l.innerHTML=`<input type="checkbox" value="${e.id}"><span>${e.name}${e.price==null?' · preço a definir':` · + ${PH.brl(e.price)}`}</span>`;
      const cb=l.querySelector('input');
      cb.onchange=()=>{cb.checked?state.extraIds.add(e.id):state.extraIds.delete(e.id);$('extrasInput').value=[...state.extraIds].join(',');updateTotal();};
      g.appendChild(l);
    }); updateTotal();
  }

  function updateTotal(){
    let total=state.service?Number(state.service.price):0,pending=0;
    state.extras.filter(e=>state.extraIds.has(e.id)).forEach(e=>{if(e.price==null)pending++;else total+=Number(e.price)});
    $('liveTotal').textContent=PH.brl(total); $('pendingPrices').textContent=pending?`${pending} adicional(is) com valor ainda a confirmar.`:'';
  }

  function renderConditions(){
    const g=$('conditions'); g.innerHTML=''; state.conditionIds.clear(); $('conditionFlags').value='';
    $('dirtLevel').value='1'; $('dirtLabel').textContent='1 — LEVE'; $('recommendation').textContent='';
    if(!state.conditionsList.length){g.innerHTML='<div class="notice">Nenhuma pergunta/condição ativa para esta categoria.</div>';return;}
    state.conditionsList.forEach(c=>{
      const l=document.createElement('label'); l.className='check'; l.innerHTML=`<input type="checkbox" value="${c.id}"><span>${c.label}</span>`;
      const cb=l.querySelector('input'); cb.onchange=()=>{cb.checked?state.conditionIds.add(Number(c.id)):state.conditionIds.delete(Number(c.id));$('conditionFlags').value=[...state.conditionIds].join(',');updateDirt();};
      g.appendChild(l);
    });
  }

  function updateDirt(){
    const selected=state.conditionsList.filter(c=>state.conditionIds.has(Number(c.id)));
    const score=selected.reduce((n,c)=>n+Math.max(1,Number(c.weight||1)),0);
    const level=Math.min(5,Math.max(1,Math.ceil(score/2))); $('dirtLevel').value=level;
    const labels=['','1 — LEVE','2 — NORMAL','3 — MODERADO','4 — PESADO','5 — EXTREMO']; $('dirtLabel').textContent=labels[level]; updateRecommendation();
  }

  function updateRecommendation(){
    const level=Number($('dirtLevel').value||1); let rec='';
    if(state.service&&/Simples/i.test(state.service.name)&&level>=3){
      const better=state.services.find(s=>/Detalhada/i.test(s.name)); if(better)rec=`Pelo estado informado do seu veículo, ${better.name} pode ser mais indicada. Você continua no controle da escolha.`;
    } $('recommendation').textContent=rec;
  }

  $('photos').addEventListener('change',e=>{
    if(e.target.files.length>5){alert('Envie no máximo 5 fotos.');e.target.value='';return}
    $('photoInfo').textContent=e.target.files.length?`${e.target.files.length} foto(s) selecionada(s).`:'';
  });

  function formatDateBR(value){ if(!value)return '—'; const [y,m,d]=value.split('-'); return `${d}/${m}/${y}`; }
  function clearAppointmentDate(){
    if(!$('appointmentDate')) return;
    $('appointmentDate').value=''; $('selectedDateLabel').textContent='Selecionar data'; state.slot=''; $('appointmentTime').value='';
    if($('calendarPopover')){$('calendarPopover').hidden=true;$('datePickerButton')?.setAttribute('aria-expanded','false');}
    updateMiniSummary();
  }

  const monthNames=['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  async function renderCalendar(){
    if(!state.service){$('calendarMessage').textContent='Escolha um serviço antes de selecionar a data.';return;}
    const y=state.calendarDate.getFullYear(),m=state.calendarDate.getMonth()+1;
    $('calendarMonthLabel').textContent=`${monthNames[m-1]} ${y}`; $('calendarGrid').innerHTML='<div class="calendar-loading">Carregando agenda...</div>'; $('calendarMessage').textContent='';
    try{
      const r=await fetch(`/api/calendar-availability?year=${y}&month=${m}&service_id=${state.service.id}`);
      if(!r.ok) throw new Error('Não foi possível carregar o calendário.');
      const data=await r.json(); const map=new Map(data.days.map(d=>[d.date,d]));
      const first=new Date(y,m-1,1); const totalDays=new Date(y,m,0).getDate(); const frag=document.createDocumentFragment();
      for(let i=0;i<first.getDay();i++){const blank=document.createElement('span');blank.className='calendar-day blank';frag.appendChild(blank)}
      let availableCount=0;
      for(let day=1;day<=totalDays;day++){
        const iso=`${y}-${String(m).padStart(2,'0')}-${String(day).padStart(2,'0')}`; const info=map.get(iso)||{status:'closed',count:0};
        const b=document.createElement('button'); b.type='button'; b.className=`calendar-day ${info.status}`; b.innerHTML=`<strong>${day}</strong>${info.status==='available'?`<small>${info.count} horário${info.count===1?'':'s'}</small>`:''}`;
        if(info.status!=='available'){b.disabled=true;b.title=info.status==='past'?'Data passada':info.status==='closed'?'Sem expediente':'Sem horários disponíveis';}
        else{
          availableCount++; b.setAttribute('aria-label',`${day} de ${monthNames[m-1]}, ${info.count} horários disponíveis`);
          if($('appointmentDate').value===iso)b.classList.add('selected');
          b.onclick=()=>selectDate(iso);
        } frag.appendChild(b);
      }
      $('calendarGrid').innerHTML=''; $('calendarGrid').appendChild(frag);
      if(!availableCount)$('calendarMessage').textContent='Não há datas com horários disponíveis neste mês. Use a seta para consultar o próximo mês.';
    }catch(err){$('calendarGrid').innerHTML='';$('calendarMessage').textContent=err.message||'Erro ao carregar calendário.';}
    const now=new Date(); const minMonth=new Date(now.getFullYear(),now.getMonth(),1);
    $('calendarPrev').disabled=state.calendarDate<=minMonth;
  }

  function selectDate(iso){
    $('appointmentDate').value=iso; $('selectedDateLabel').textContent=formatDateBR(iso); state.slot=''; $('appointmentTime').value='';
    document.querySelectorAll('.calendar-day.selected').forEach(x=>x.classList.remove('selected'));
    const target=[...document.querySelectorAll('.calendar-day.available')].find(x=>x.querySelector('strong')?.textContent===String(Number(iso.slice(-2)))); if(target)target.classList.add('selected');
    $('calendarPopover').hidden=true; $('datePickerButton').setAttribute('aria-expanded','false'); updateMiniSummary(); updateNextButton();
  }

  function openCalendar(toggle=true){
    const pop=$('calendarPopover'); if(!pop)return;
    if(toggle && !pop.hidden){pop.hidden=true;$('datePickerButton').setAttribute('aria-expanded','false');return;}
    if($('appointmentDate').value){const [y,m]= $('appointmentDate').value.split('-').map(Number);state.calendarDate=new Date(y,m-1,1)}
    else{const now=new Date();state.calendarDate=new Date(now.getFullYear(),now.getMonth(),1)}
    pop.hidden=false; $('datePickerButton').setAttribute('aria-expanded','true'); renderCalendar();
  }

  $('datePickerButton')?.addEventListener('click',()=>openCalendar(true));
  $('calendarPrev')?.addEventListener('click',()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()-1,1);renderCalendar()});
  $('calendarNext')?.addEventListener('click',()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+1,1);renderCalendar()});

  async function loadSlots(){
    const date=$('appointmentDate').value;if(!date||!state.service)return;
    $('slots').innerHTML='<span class="loading-text">Carregando horários...</span>';$('slotMessage').textContent='';state.slot='';$('appointmentTime').value='';updateMiniSummary(); updateNextButton();
    const r=await fetch(`/api/availability?date=${date}&service_id=${state.service.id}`);const data=await r.json();$('slots').innerHTML='';
    if(!data.slots.length){$('slotMessage').textContent=data.message||'Nenhum horário disponível.';return}
    data.slots.forEach(t=>{
      const b=document.createElement('button');b.type='button';b.className='slot';b.innerHTML=`<span>◷</span><strong>${t}</strong><small>Disponível</small>`;
      b.onclick=()=>{[...$('slots').children].forEach(x=>x.classList.remove('selected'));b.classList.add('selected');state.slot=t;$('appointmentTime').value=t;updateMiniSummary();updateNextButton()}; $('slots').appendChild(b)
    });
  }

  function renderSummary(){
    const selectedExtras=state.extras.filter(e=>state.extraIds.has(e.id)); const selectedConditions=state.conditionsList.filter(c=>state.conditionIds.has(Number(c.id)));
    let total=state.service?Number(state.service.price):0;selectedExtras.forEach(e=>{if(e.price!=null)total+=Number(e.price)});
    const dateBR=formatDateBR($('appointmentDate').value||'');
    const html=`<div><span>Veículo</span><strong>${$('brand').value} ${$('model').value}</strong></div><div><span>Categoria</span><strong>${categoryLabel()}</strong></div><div><span>Serviço</span><strong>${state.service?.name||'—'}</strong></div><div><span>Adicionais</span><strong>${selectedExtras.length?selectedExtras.map(e=>e.name).join(', '):'Nenhum'}</strong></div><div><span>Condição</span><strong>${selectedConditions.length?selectedConditions.map(c=>c.label).join(', '):'Não informada'}</strong></div><div><span>Data</span><strong>${dateBR}</strong></div><div><span>Horário</span><strong>${state.slot||'—'}</strong></div><div><span>Forma de pagamento</span><strong>${paymentText()}</strong></div><div><span>Total estimado</span><strong>${PH.brl(total)}</strong></div>`;
    $('bookingSummary').innerHTML=html;$('finalSummary').innerHTML=html;
  }

  form.querySelectorAll('input[name="payment_method"]').forEach(r=>r.addEventListener('change',()=>{if(step>=10)renderSummary();updateNextButton()}));

  document.querySelectorAll('.savedVehicle').forEach(b=>b.onclick=()=>{
    const v=JSON.parse(b.dataset.json);state.vehicleType=v.vehicle_type;state.category=v.category_code;$('vehicleType').value=v.vehicle_type;$('category').value=v.category_code;$('savedVehicleId').value=v.id;vehicleCatalog?.setVehicleType(v.vehicle_type);vehicleCatalog?.setSaved(v);$('year').value=v.year||'';$('color').value=v.color||'';$('engineCc').value=v.engine_cc||'';$('plate').value=v.plate||'';document.querySelectorAll('[data-vehicle]').forEach(x=>x.classList.toggle('selected',x.dataset.vehicle===v.vehicle_type));document.querySelectorAll('[data-category]').forEach(x=>x.classList.toggle('selected',x.dataset.category===v.category_code));updateMiniSummary();updateNextButton();
  });

  form.addEventListener('submit',e=>{
    if(!state.slot||!state.service){e.preventDefault();alert('Revise serviço, data e horário.');return;}
    if(!form.querySelector('input[name="payment_method"]:checked')){e.preventDefault();alert('Escolha a forma de pagamento.');}
  });

  if(window.BOOKING_PREFILL?.vehicle_id){const b=[...document.querySelectorAll('.savedVehicle')].find(x=>{try{return String(JSON.parse(x.dataset.json).id)===String(window.BOOKING_PREFILL.vehicle_id)}catch{return false}});if(b){b.click();show(3)}}
  show(step);
})();
