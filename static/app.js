// Helpers globais mínimos. Mantido sem dependências externas para facilitar implantação.
window.PH = { brl(v){ return new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(v||0)); } };
