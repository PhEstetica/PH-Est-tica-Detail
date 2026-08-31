# PH ESTÉTICA & DETAIL — V5

Central digital de cuidados automotivos em FastAPI + SQLite, com experiência de cliente e painel administrativo.

## Rodar no Windows

1. Abra o CMD dentro da pasta do projeto.
2. Na primeira vez:

```bat
python -m pip install -r requirements.txt
```

3. Inicie:

```bat
python -m uvicorn app:app --reload
```

Ou dê dois cliques em `INICIAR_SITE.bat`.

Site: http://127.0.0.1:8000
Painel: http://127.0.0.1:8000/admin/login

O login administrativo de desenvolvimento continua `admin` / `admin123`, porque a V5 não altera o item de segurança/login administrativo solicitado para ficar de fora desta atualização.

## O que a V5 acrescenta

### Formas de pagamento editáveis
- cadastro, edição, ativação/desativação e remoção pelo painel Financeiro;
- apenas formas ativas aparecem para o cliente;
- PIX e Dinheiro começam ativos em instalação nova;
- Cartão começa desativado e pode ser ativado quando houver maquininha.

### Banco e preparação para crescimento
- o uso local continua em SQLite;
- backup automático diário do `ph_estetica.db` na pasta `backups`;
- retenção de backup configurável no painel;
- botão de backup manual;
- utilitário `migrate_to_postgres.py` para copiar o banco para PostgreSQL futuramente;
- dependências opcionais em `requirements-postgres.txt`.

A publicação/hospedagem online NÃO foi feita nesta versão, conforme solicitado.

### Confirmações, avisos e lembretes
- confirmação do agendamento;
- adicionar agendamento ao calendário via arquivo `.ics`;
- avisos internos do cliente;
- avisos de veículo recebido, início, finalização e pronto;
- lembretes de agendamentos de amanhã preparados para envio manual por WhatsApp no painel, sem integração paga/fictícia.

### Cancelamento e remarcação
- prazos mínimos configuráveis no painel;
- cliente pode remarcar sem refazer os dados;
- a remarcação usa a disponibilidade real da agenda;
- cancelamentos fora do prazo são bloqueados e direcionados ao contato da empresa.

### Antes e depois
- upload de fotos ANTES e DEPOIS no atendimento administrativo;
- visualização pelo cliente;
- comparador antes/depois quando existem os dois tipos de foto;
- exclusão de foto pelo painel.

### Avaliações
- cliente avalia após atendimento pronto/finalizado;
- nota, comentário público e feedback privado;
- autorização separada do cliente para aparecer na home;
- painel de avaliações para ocultar/excluir;
- o administrador não consegue forçar a publicação se o cliente não autorizou.

### Home comercial
- serviços e preços vindos do banco;
- imagens de carros e motos;
- galeria de trabalhos reais;
- avaliações autorizadas;
- CTA de agendamento e WhatsApp;
- textos principais editáveis no painel.

### Galeria
- upload de fotos reais de carros/motos;
- título, legenda, categoria, ordem e ativação;
- imagens ativas aparecem automaticamente na página inicial.

### Configurações da empresa
- WhatsApp;
- Instagram opcional;
- textos da home;
- título da galeria;
- prazos de cancelamento/remarcação;
- retenção dos backups;
- upload de logo do cabeçalho.

### Operação diária
- nova tela `Hoje` no painel;
- horário, cliente, veículo, serviço, pagamento e status;
- atualização rápida de status;
- botão para WhatsApp e detalhes.

### Financeiro
- valor estimado e valor final;
- desconto;
- status pago/pendente;
- forma de pagamento;
- recebimentos reais do dia e mês;
- ticket médio recebido;
- valores a receber;
- fechamento do dia;
- totais por forma de pagamento;
- serviço adicional aprovado atualiza o total do atendimento.

### Confiabilidade
- datas passadas são bloqueadas no agendamento do cliente;
- confirmação usa transação SQLite `BEGIN IMMEDIATE` para reduzir conflito de duas pessoas tentando reservar o mesmo último horário;
- suite automatizada em `tests/` cobrindo páginas principais, pagamentos, datas passadas, conflito de horário, privacidade básica de acompanhamento, política de cancelamento e proteção de páginas administrativas.

Para rodar os testes:

```bat
python -m pip install -r requirements-dev.txt
pytest -q
```

## Atualizar sem perder seus dados atuais

1. No CMD do site pressione `CTRL + C`.
2. Faça uma cópia do arquivo `ph_estetica.db`.
3. Extraia a atualização V5.
4. Copie os arquivos por cima da pasta atual do projeto.
5. **NÃO apague nem substitua o seu `ph_estetica.db`.**
6. Rode novamente:

```bat
python -m uvicorn app:app --reload
```

Na primeira inicialização a V5 cria/migra automaticamente as novas tabelas e colunas necessárias.

## Importante

Antes de uma futura publicação para clientes reais, ainda será necessário configurar hospedagem/domínio e, no momento apropriado, apontar a aplicação para a infraestrutura de produção. Esses itens foram deixados fora desta atualização conforme solicitado.

## Atualização V6 — catálogo pesquisável de marcas e modelos

A V6 adiciona um catálogo de veículos para reduzir erros de digitação no agendamento e na Minha Garagem.

### Como funciona para o cliente

- escolhe **Carro** ou **Moto**;
- começa a digitar a marca e recebe sugestões em tempo real;
- depois de selecionar a marca, começa a digitar o modelo;
- os resultados mostram modelos genéricos, evitando duplicar versões apenas por motor, câmbio ou acabamento;
- se o veículo não estiver no catálogo, existe **“Não encontrou seu veículo? Digitar manualmente”**.

Exemplos da normalização:

- Volkswagen Voyage 1.0 / 1.6 / versões de acabamento → **Voyage**;
- Honda Biz 110i / Biz 125 ES / EX / KS → **Biz**;
- Honda CB 300F Twister → **CB 300F**;
- Honda CB 500F e CB 500X permanecem **separadas**, pois são modelos/formato diferentes;
- Chevrolet Onix e Onix Plus permanecem separados;
- Toyota Corolla e Corolla Cross permanecem separados.

### Fonte

O catálogo usa a hierarquia de marcas e modelos da FIPE através da API Parallelum. O snapshot inicial de marcas foi revisado em agosto/2026. A API permite atualizar marcas/modelos no futuro sem depender de uma nova versão do site.

### Banco de dados

Foram adicionadas tabelas próprias para:

- marcas genéricas;
- códigos/fontes FIPE das marcas;
- aliases de marcas (ex.: `VW` → Volkswagen);
- modelos genéricos;
- aliases/modelos brutos da FIPE usados na pesquisa.

Os veículos já existentes continuam funcionando normalmente. Novos veículos selecionados pelo catálogo passam a guardar também o vínculo com a marca/modelo cadastrado.

### Sincronização

O painel ganhou **Marcas e modelos**. Nele é possível:

- pesquisar marcas;
- ativar/desativar marca;
- editar nome;
- atualizar os modelos de uma marca;
- editar o nome genérico de um modelo;
- alterar categoria sugerida;
- ativar/desativar modelo;
- sincronizar o catálogo completo.

Para pré-carregar todos os modelos sem entrar no painel, também existe `SINCRONIZAR_CATALOGO.bat`.


## Atualização V7 — agendamento mais profissional

A V7 mantém tudo da V6 e refina a experiência de agendamento:

- nomes dos serviços em branco e descrições em cinza-claro para melhorar contraste;
- seleção de serviço com borda dourada e indicador visual de selecionado;
- duração exibida em badge;
- pequenos ícones visuais nos cards;
- calendário próprio em pop-up para escolher a data;
- datas passadas, dias sem expediente e dias sem vagas ficam indisponíveis;
- o calendário mostra quantos horários ainda existem no dia;
- horários com visual de chips/cards, destaque dourado na seleção;
- botão Continuar fica desabilitado enquanto falta uma escolha obrigatória;
- resumo compacto acompanha veículo, serviço, valor, data e horário conforme o cliente avança;
- textos curtos de confiança explicam a disponibilidade real da agenda.

### Atualização sem perder dados

Pare o servidor com `CTRL + C`, faça backup do `ph_estetica.db`, substitua os arquivos do projeto pelos da V7 e mantenha o seu banco atual. Depois execute:

```bat
python -m uvicorn app:app --reload
```


## Atualização V8 — home fotográfica temporária

A V8 mantém tudo da V7 e acrescenta uma home mais fotográfica usando imagens ilustrativas temporárias de estética automotiva. Elas são identificadas como imagens ilustrativas e não são apresentadas como serviços realizados pela PH.

No painel **Admin → Configurações**, o administrador pode substituir individualmente o banner principal, a imagem de carros, a imagem de motos e os dois detalhes visuais. Quando houver fotos reais, basta fazer upload sem alterar código.

A área **Admin → Galeria** continua destinada aos trabalhos reais. Enquanto não existir nenhuma foto ativa nela, a home mostra uma pequena vitrine ilustrativa. Ao cadastrar a primeira foto real ativa, a galeria da home passa automaticamente a usar as fotos da PH.

As imagens ilustrativas padrão são carregadas do Unsplash e dependem de conexão com a internet. Fotos reais enviadas pelo painel ficam armazenadas localmente em `uploads`.


## Atualização V9 — WhatsApp rápido e identificação melhor na gestão

- O telefone na lista de agendamentos agora é exibido no padrão brasileiro, por exemplo `(62) 99901-5048`, sem alterar o número salvo no banco.
- O veículo passa a ser exibido como `CHEVROLET - CELTA`, deixando marca e modelo visualmente separados.
- Foi adicionado o botão **WhatsApp** na coluna de ações. Ele abre a conversa do cliente com uma mensagem pronta de acordo com o status atual do atendimento.
- O envio continua manual: o sistema abre o WhatsApp e o usuário confirma o envio, portanto não exige API paga do WhatsApp.
- A tela detalhada do agendamento também ganhou o botão **Enviar WhatsApp**.
- Todo o restante da tela de gestão foi mantido.


## Atualização V10 — mensagens editáveis do WhatsApp

A V10 mantém tudo da V9 e adiciona **Admin → Configurações → Mensagens do WhatsApp**.

Agora é possível editar os textos usados nos botões de WhatsApp para: agendamento confirmado, veículo recebido, preparação, lavagem iniciada, detalhamento, finalização, inspeção, pronto para retirada, atendimento finalizado e cancelamento.

Campos automáticos aceitos: `{cliente}`, `{veiculo}`, `{servico}`, `{agendamento}`, `{valor}`, `{data}`, `{horario}` e `{empresa}`.

O envio continua gratuito/manual: o sistema abre a conversa com a mensagem preenchida, mas não envia sozinho.


## Atualização V11 — cobrança de pagamentos pendentes

A V11 mantém tudo da V10 e adiciona:

- mensagem de cobrança/lembrete de pagamento editável no painel;
- funciona com PIX, dinheiro, cartão e qualquer outra forma cadastrada;
- novos campos de mensagem: `{forma_pagamento}` e `{status_pagamento}`;
- botão **Cobrar no WhatsApp** no atendimento quando o pagamento estiver pendente;
- seção **Pagamentos pendentes** no Financeiro, com telefone formatado, veículo, forma, valor e botão de cobrança;
- contador de quantas vezes a cobrança foi aberta e registro da última tentativa;
- mensagens padrão de status corrigidas para usar “o veículo”, funcionando naturalmente para carro e moto;
- a V11 preserva mensagens personalizadas: a migração só troca os modelos antigos se ainda estiverem exatamente no padrão da V10.

A cobrança não é enviada automaticamente. O botão abre o WhatsApp com a mensagem pronta e você confirma o envio, evitando custo de API.


## Atualização V12 — módulo financeiro completo

A V12 preserva as funções anteriores e adiciona um financeiro integrado aos atendimentos. Receitas são sincronizadas quando o pagamento do atendimento é marcado como pago, sem duplicidade por agendamento. Inclui despesas pagas/pendentes, água e energia mensais, investimentos, aportes do proprietário, ajudantes com valor gerado x pago, fluxo de caixa, payback, fechamento mensal, análise de serviços e indicadores por período.

### Atualizar sem perder dados
1. Pare o servidor com CTRL + C.
2. Faça backup do `ph_estetica.db`.
3. Copie os arquivos da V12 por cima dos atuais.
4. Não substitua nem apague o seu `ph_estetica.db`.
5. Execute `python -m uvicorn app:app --reload`.

Na primeira inicialização, as tabelas V12 são criadas automaticamente e atendimentos já marcados como pagos são sincronizados para o financeiro.


## Atualização V13 — catálogo de marcas/modelos no atendimento retroativo

Na tela **Admin → Agendamentos → Registrar atendimento já realizado**, marca e modelo agora usam o mesmo catálogo pesquisável do agendamento normal.

- digite parte da marca para receber sugestões;
- após selecionar a marca, digite parte do modelo;
- motos pesquisam apenas marcas/modelos de moto;
- carros pesquisam o catálogo de carros;
- veículos já cadastrados continuam podendo ser selecionados normalmente;
- existe modo manual caso um veículo não esteja no catálogo;
- quando marca/modelo vêm do catálogo, os IDs são gravados no veículo para manter o cadastro padronizado.


## V13 — complemento: calendário pop-up no Financeiro

Esta edição consolidada da V13 adiciona abertura facilitada do calendário em todos os campos de data do módulo Financeiro. Basta clicar no campo de data para abrir o seletor de calendário do navegador. Isso vale para filtros de período, despesas, vencimentos, pagamentos, investimentos, aportes, pagamentos de ajudantes e demais datas financeiras. Campos de competência mensal também recebem o seletor de mês.

A alteração é apenas de interface: não muda regras financeiras nem exige migração do banco.
