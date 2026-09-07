(()=>{
  function debounce(fn,ms=220){let t;return(...args)=>{clearTimeout(t);t=setTimeout(()=>fn(...args),ms)}}
  function attach(opts){
    const get=id=>typeof id==='string'?document.getElementById(id):id;
    const brandSearch=get(opts.brandSearch),modelSearch=get(opts.modelSearch),brandValue=get(opts.brandValue),modelValue=get(opts.modelValue);
    const brandId=get(opts.brandId),modelId=get(opts.modelId),brandMenu=get(opts.brandMenu),modelMenu=get(opts.modelMenu),toggle=get(opts.manualToggle),status=get(opts.status);
    const brandHelp=get(opts.brandHelp),modelHelp=get(opts.modelHelp);
    if(!brandSearch||!modelSearch||!brandValue||!modelValue)return null;
    let vehicleType=(opts.vehicleType||'car'),selectedBrand=null,manual=false,brandReq=0,modelReq=0;

    function hide(menu){if(menu){menu.innerHTML='';menu.classList.remove('open')}}
    function show(menu,items,onPick,emptyText){
      if(!menu)return;
      menu.innerHTML='';
      if(!items.length){const d=document.createElement('div');d.className='autocomplete-empty';d.textContent=emptyText||'Nenhuma opção encontrada.';menu.appendChild(d)}
      else items.forEach(item=>{const b=document.createElement('button');b.type='button';b.className='autocomplete-option';b.textContent=item.name;b.addEventListener('click',()=>onPick(item));menu.appendChild(b)});
      menu.classList.add('open');
    }
    function setStatus(message,error=false){if(!status)return;status.textContent=message||'';status.classList.toggle('error',!!error)}
    function clearModel(){modelSearch.value='';modelValue.value='';if(modelId)modelId.value='';hide(modelMenu);if(!manual)modelSearch.disabled=!selectedBrand;if(modelHelp)modelHelp.textContent=selectedBrand?'Digite parte do modelo e selecione na lista.':'Primeiro selecione a marca.'}
    function clearBrand(){selectedBrand=null;brandValue.value='';if(brandId)brandId.value='';hide(brandMenu);clearModel()}
    function setVehicleType(type){
      if(!['car','moto'].includes(type))type='car';
      if(vehicleType!==type){vehicleType=type;brandSearch.value='';clearBrand();manual=false;applyManualState()}
    }
    function pickBrand(item){selectedBrand=item;brandSearch.value=item.name;brandValue.value=item.name;if(brandId)brandId.value=item.id;hide(brandMenu);clearModel();modelSearch.disabled=false;modelSearch.focus();setStatus('')}
    function pickModel(item){modelSearch.value=item.name;modelValue.value=item.name;if(modelId)modelId.value=item.id;hide(modelMenu);if(opts.onModelSelected)opts.onModelSelected(item)}
    async function searchBrands(q=''){
      if(manual)return;const token=++brandReq;
      try{const r=await fetch(`/api/vehicle-brands?vehicle_type=${encodeURIComponent(vehicleType)}&q=${encodeURIComponent(q)}&limit=12`);const data=await r.json();if(token!==brandReq)return;show(brandMenu,data.items||[],pickBrand,'Nenhuma marca encontrada. Você pode usar o cadastro manual.')}catch(e){if(token===brandReq)setStatus('Não foi possível consultar o catálogo agora. Use o cadastro manual.',true)}
    }
    async function searchModels(q=''){
      if(manual||!selectedBrand)return;const token=++modelReq;
      if(modelHelp)modelHelp.textContent='Buscando modelos...';
      try{const r=await fetch(`/api/vehicle-models?brand_id=${selectedBrand.id}&q=${encodeURIComponent(q)}&limit=18`);const data=await r.json();if(token!==modelReq)return;show(modelMenu,data.items||[],pickModel,data.sync_error?'Não foi possível sincronizar os modelos. Use o cadastro manual.':'Nenhum modelo encontrado.');if(data.sync_error)setStatus('Catálogo online indisponível para esta marca. Você pode digitar manualmente.',true);if(modelHelp)modelHelp.textContent='Digite parte do modelo e selecione na lista.'}catch(e){if(token===modelReq){setStatus('Não foi possível consultar os modelos. Use o cadastro manual.',true);if(modelHelp)modelHelp.textContent='Você pode usar o cadastro manual.'}}
    }
    const doBrandSearch=debounce(()=>{if(!manual){clearBrand();searchBrands(brandSearch.value.trim())}},180);
    const doModelSearch=debounce(()=>{if(!manual){modelValue.value='';if(modelId)modelId.value='';searchModels(modelSearch.value.trim())}},180);
    brandSearch.addEventListener('input',()=>{if(manual){brandValue.value=brandSearch.value;return}doBrandSearch()});
    brandSearch.addEventListener('focus',()=>{if(!manual)searchBrands(brandSearch.value.trim())});
    modelSearch.addEventListener('input',()=>{if(manual){modelValue.value=modelSearch.value;return}doModelSearch()});
    modelSearch.addEventListener('focus',()=>{if(!manual&&selectedBrand)searchModels(modelSearch.value.trim())});
    document.addEventListener('click',e=>{if(brandMenu&&!brandMenu.contains(e.target)&&e.target!==brandSearch)hide(brandMenu);if(modelMenu&&!modelMenu.contains(e.target)&&e.target!==modelSearch)hide(modelMenu)});

    function applyManualState(){
      brandSearch.placeholder=manual?'Digite a marca':'Ex.: Chev, Volks, Honda...';
      modelSearch.placeholder=manual?'Digite o modelo':'Ex.: Onix, Voyage, Biz...';
      modelSearch.disabled=manual?false:!selectedBrand;
      if(toggle)toggle.textContent=manual?'Voltar para pesquisa no catálogo':'Não encontrou seu veículo? Digitar manualmente';
      if(brandHelp)brandHelp.textContent=manual?'Modo manual: escreva a marca exatamente como desejar.':'Digite parte da marca e selecione na lista.';
      if(modelHelp)modelHelp.textContent=manual?'Modo manual: escreva o modelo exatamente como desejar.':(selectedBrand?'Digite parte do modelo e selecione na lista.':'Primeiro selecione a marca.');
      hide(brandMenu);hide(modelMenu);setStatus(manual?'Modo manual ativado. O agendamento não será bloqueado se o veículo não estiver no catálogo.':'');
      if(manual){if(brandId)brandId.value='';if(modelId)modelId.value='';selectedBrand=null;brandValue.value=brandSearch.value;modelValue.value=modelSearch.value}
      else{brandSearch.value='';modelSearch.value='';clearBrand()}
    }
    if(toggle)toggle.addEventListener('click',()=>{manual=!manual;applyManualState();brandSearch.focus()});

    function setSaved(v){
      vehicleType=v.vehicle_type||vehicleType;manual=false;selectedBrand=v.brand_catalog_id?{id:v.brand_catalog_id,name:v.brand}:null;
      brandSearch.value=v.brand||'';brandValue.value=v.brand||'';if(brandId)brandId.value=v.brand_catalog_id||'';
      modelSearch.value=v.model||'';modelValue.value=v.model||'';if(modelId)modelId.value=v.model_catalog_id||'';
      modelSearch.disabled=false;
      if(brandHelp)brandHelp.textContent=v.brand_catalog_id?'Marca vinculada ao catálogo.':'Veículo salvo anteriormente.';
      if(modelHelp)modelHelp.textContent=v.model_catalog_id?'Modelo vinculado ao catálogo.':'Veículo salvo anteriormente.';
      hide(brandMenu);hide(modelMenu);setStatus('');
    }
    function validate(){
      if(manual){brandValue.value=brandSearch.value.trim();modelValue.value=modelSearch.value.trim()}
      if(!brandValue.value.trim())return {ok:false,message:manual?'Informe a marca.':'Selecione uma marca da lista ou ative o modo manual.'};
      if(!modelValue.value.trim())return {ok:false,message:manual?'Informe o modelo.':'Selecione um modelo da lista ou ative o modo manual.'};
      return {ok:true};
    }
    applyManualState();
    return {setVehicleType,setSaved,validate,isManual:()=>manual,selectedBrand:()=>selectedBrand};
  }
  window.PHVehicleCatalog={attach};
})();
