# Guia Completo de Funcionalidades, Configurações e Utilização — PULSO (PENGEL)

Este documento descreve **todas as funcionalidades, configurações e opções** disponíveis no protótipo **PULSO** (Portal Clínico PC + Aplicação Móvel/Pulseira do Utente), explicando **o que é possível fazer** e **como utilizar passo a passo** em cada plataforma.

---

## 1. Como Executar e Aceder

O projeto funciona em dois modos compatíveis entre si:

1. **Modo Completo (Servidor Local FastAPI + SQLite):**
   - Aceda a `http://127.0.0.1:8000` (Portal PC) e `http://127.0.0.1:8000/mobile.html` (App Telemóvel).
   - Todos os dados, anexos, chaves API e eventos de emergência são persistidos em base de dados SQLite (`server/pulso.db`).
2. **Modo Estático (GitHub Pages):**
   - Aceda a `https://projetopulso.github.io/PULSO-PENGEL/` (Portal PC) e `https://projetopulso.github.io/PULSO-PENGEL/mobile.html` (App Telemóvel).
   - O cliente unificado (`pulso_app.js`) ativa automaticamente o fallback local em `localStorage` para que todas as funcionalidades continuem operacionais sem servidor Python.

### Credenciais de Demonstração
- **Utente (Paciente):** Nº Utente SNS `234891024` · Palavra-passe `pulso1234`
- **Médica/o:** Cédula Profissional `48192` + Código temporário de 8 dígitos gerado na App Móvel do utente (ou botão de leitura QR Code).
- **Novo Utente:** Na janela de entrada, selecione **`+ Registar SNS`** para criar uma nova conta com Nº de Utente SNS (9 dígitos), Data de Nascimento, Nome Completo, Email e Palavra-passe.

---

## 2. Aplicação PC / Portal Clínico (`index.html`)

No topo do portal existem dois controlos sempre visíveis:
- **Seletor de Experiência (`Simples` | `Equilibrado` | `Detalhado`):** adapta a quantidade de informação e abas apresentadas na interface.
- **Alternador de Tema (`Escuro` / `Claro`):** alterna entre tema escuro OLED e tema claro diurno de alto contraste.
- **Botão `App Telemóvel`:** abre a vista móvel (`mobile.html`) numa janela/separador paralelo.

A barra de navegação apresenta **todas as abas visíveis de imediato**:

### 2.1. Aba `Histórico` (Evolução Clínica & Histórico)
- **Gráficos de Tendência de Biomarcadores:** visualize a evolução temporal (ex.: Glicose em Jejum, Creatinina, Colesterol, HbA1c) com faixas de referência clínicas.
- **Carteira de Exames:** consulte todos os exames importados, enviados por email, digitalizados por OCR ou sincronizados via API.
- **Editar Classificação sem Duplicar:** clique em editar num exame para corrigir título, categoria clínica ou entidade emissora mantendo o registo original único.
- **Alertas Clínicos Vitais:** barra de destaque com alergias graves, dispositivos implantados (ex.: Pacemaker) e medicação crítica do utente.

### 2.2. Aba `Email (IA)` *(visível em modo Equilibrado/Detalhado)*
- **Caixa de Ingestão Clínica:** endereço dedicado do utente (ex.: `antonio.silva@inbox.pulso.health`).
- **Simulação de Pipeline SMTP + IA:** simula a receção de um email de laboratório/hospital (validação SPF/DKIM, classificação automática da especialidade, extração LOINC de biomarcadores) e permite clicar em **`Confirmar e Integrar no Histórico`** para guardar o exame na carteira do utente.

### 2.3. Aba `PDF & OCR`
- **Leitura Automática de Documentos:** carregue um PDF clínico ou imagem (ou utilize o PDF de demonstração do sistema).
- **Extração e Revisão Humana:** o sistema extrai título, entidade emissora, data e parâmetros laboratoriais; o utilizador revê/edita os valores antes de guardar no histórico.

### 2.4. Aba `Medições` (Medições & Eventos)
- **Registo de Sinais Vitais:** insira medições de Tensão Arterial (sistólica/diastólica), Frequência Cardíaca, SpO₂ (%) ou Glicose (mg/dL) com data/hora e notas.
- **Registo de Eventos Clínicos:** registe ocorrências médicas, alterações terapêuticas, consultas ou episódios urgentes associados a uma data.

### 2.5. Aba `Aprender (23)` (Biblioteca Educativa PULSO)
- **6 Categorias · 23 Fichas Educativas:** explicações claras e baseadas em evidência sobre biomarcadores, exames de imagem, cardiologia e medições diárias.
- **Pesquisa e Filtros:** pesquise por termo ou filtre por categoria e abra qualquer ficha em detalhe.

### 2.6. Aba `Partilha IPS` *(Partilha Segura & Emergência)*
- **Resumo Internacional do Doente (IPS / UE):** estrutura de partilha clínica normalizada para consultas externas e urgências médicas, garantindo que apenas o utente autoriza ou revoga códigos temporários de acesso.

### 2.7. Aba `APIs & Chaves` (Ligações SNS, Hospitais Privados, Laboratórios e API Keys)
Permite interligar a carteira clínica às entidades de saúde em Portugal e gerir credenciais API:
- **Entidades Pré-configuradas (9 conectores HL7 FHIR / LOINC):**
  - **SNS Público:** `SNS 24 / SPMS (RSE)`
  - **Hospitais Privados:** `CUF / MyCUF`, `Hospital da Luz / MY LUZ`, `Lusíadas Saúde / +Lusíadas`, `Trofa Saúde`
  - **Laboratórios Clínicos:** `Unilabs Portugal`, `Germano de Sousa`, `Joaquim Chaves Saúde`, `Synlab Portugal`
- **O que pode fazer em cada entidade:**
  1. **`🔑 Key`:** registar/atualizar o **Endpoint URL**, **Client ID** e **API Key / Secret Token** (a chave guardada é exibida de forma mascarada).
  2. **`Ligar` / `Desligar`:** autorizar ou revogar a ligação da entidade.
  3. **`↻ Sincronizar` (ou `↻ Sincronizar Ligados` no topo):** importar os exames da entidade para o histórico do utente com deduplicação automática e registo de auditoria.
- **Adicionar Novas Ligações API (`+ Nova Ligação API`):**
  - Clique em **`+ Nova Ligação API`** para registar uma nova clínica, hospital ou laboratório personalizado, indicando Nome da Entidade, Grupo, Protocolo, Endpoint URL, Client ID e API Key.

### 2.8. Aba `Configurações`
Dividida em 3 áreas principais:
1. **Dados da Conta & Perfil:**
   - Atualizar **Nome Completo**, **Email / Caixa de Ingestão**, **Data de Nascimento**, **Alertas Clínicos Vitais** (separados por vírgula) e **Nova Palavra-passe**.
2. **Acessibilidade & Interface:**
   - **Tamanho da Letra:** `Normal (100%)`, `Grande (115%)` ou `Muito Grande (130%)`.
   - **Nível de Detalhe:** `Simples`, `Equilibrado` ou `Detalhado`.
   - **Tema Visual:** alternar entre `Escuro OLED` e `Claro`.
   - **Alto Contraste:** **ativado por defeito** para reforçar contornos e legibilidade.
   - **Reduzir Animações:** desativa efeitos de pulso e transições rápidas.
   - **Atalho `🔑 Registar API Keys`:** botão direto para aceder à página de registo de API Keys e novas ligações API.
3. **Privacidade, Exportação RGPD & Registo de Auditoria:**
   - **`⬇ Exportar Carteira (JSON)`:** descarrega uma cópia completa dos dados clínicos do utente.
   - **Registo de Auditoria:** lista cronológica de todos os acessos, sincronizações de API, alterações de perfil e acionamentos de emergência.

### 2.9. Encerrar Sessão
- Botão **`Encerrar`** na barra de navegação (encerra a consulta médica ou sessão ativa).

### 2.10. Banner de Emergência em Tempo Real (PC)
- Sempre que um alerta SOS de Nível 2 é ativado na App Móvel / Pulseira (`mobile.html`), o portal PC exibe automaticamente um **banner vermelho de emergência** com o motivo do acionamento, coordenadas GPS, número de **socorristas da comunidade** notificados, botão **`Ligar 112`** e botão **`Silenciar / Reconhecer`**.

---

## 3. Aplicação Móvel / Pulseira do Utente (`mobile.html`)

A interface móvel simula o ecrã do telemóvel do utente emparelhado com a sua pulseira/smartwatch e possui **4 abas na barra inferior**:

### 3.1. Aba `Histórico`
- Consulta rápida dos exames do utente no telemóvel.
- Clique em qualquer exame para abrir o detalhe com os valores laboratoriais.
- Suporte para carregar/extrair novos ficheiros diretamente pelo telemóvel.

### 3.2. Aba `Evolução`
- Visualização móvel dos gráficos de evolução clínica e tendências dos biomarcadores.

### 3.3. Aba `Partilha` (Acesso do Médico)
- **QR Code Clínico do Utente:** cartão com o QR Code e Nº de Utente SNS para leitura rápida em consulta.
- **Seleção de Validade:** escolha **`1 Hora`**, **`1 Dia`** ou **`1 Mês`**.
- **Botão `Obter Código de 8 Dígitos`:** gera um código temporário único (com temporizador de expiração e opção de revogar a qualquer momento).

### 3.4. Aba `SOS` (Pulseira / Smartwatch + Socorristas da Comunidade + 112)
Sistema concebido para emergências súbitas (AVC, ataque cardíaco ou queda) com proteção contra falsos alarmes:

1. **Sensor Biométrico do Relógio ("No Pulso"):**
   - Alternador **`Tirar do Pulso` / `Colocar no Pulso`**.
   - Se o relógio estiver **fora do pulso** (ex.: caiu da mesa ou da mão ao chão), o sistema deteta ausência de contacto com a pele e **ignora quedas acidentais**, evitando falsos alarmes para o 112.
2. **Modos de Acionamento:**
   - **Botão `SOS` (Manter 2 segundos):** exige pressão contínua durante 2 segundos (com barra de progresso), evitando toques involuntários.
   - **`🤕 Simular Queda`:** testa a deteção de queda brusca + imobilidade (só dispara se o sensor estiver *No Pulso*).
   - **`⌚ Triplo Clique (Relógio)` *(Botão do smartwatch)*:** atalho rápido no botão lateral do relógio pensado para situações de suspeita de AVC ou hemiparesia em que seja difícil manter o botão pressionado.
3. **Janela de Pré-Alarme Local (15 segundos):**
   - Antes de notificar terceiros, o telemóvel e a pulseira tocam e vibram localmente durante **15 segundos** com duas opções:
     - **`✓ Estou bem / Cancelar`:** cancela o alarme caso tenha sido toque acidental ou de uma criança.
     - **`🚨 Alertar Já`:** salta a contagem decrescente e ativa imediatamente o Nível 2.
4. **Nível 2 Ativo (Emergência Médica):**
   - Ativa **sirene sonora bitonal** (`880 Hz / 660 Hz` via Web Audio API) e **vibração contínua** (`navigator.vibrate`).
   - Notifica a **Rede de Socorristas da Comunidade PULSO** (3 telemóveis num raio de 150 m) para prestação rápida de auxílio enquanto a ambulância não chega.
   - Envia **coordenadas GPS** e **Resumo Clínico IPS** para o **112**.
   - Regista o evento crítico e a auditoria no servidor (`POST /api/emergency/trigger`) e envia alerta em tempo real para o Portal PC (`index.html`).
   - Disponibiliza botão direto **`📞 Ligar 112`** e **`Silenciar Sirene`**.
