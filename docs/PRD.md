# PRD – Transcritor Automático de Reuniões (Linux Mint)

> Versão de trabalho em Markdown, convertida fielmente de `docs/PRD.pdf` (o original).
> O status das tarefas (ex.: `T1 ✅`) é marcado **neste arquivo**.

## 1. Visão geral

Ferramenta pessoal para Linux Mint que grava reuniões em áudio, transcreve automaticamente com WhisperX (com separação de falantes) e usa o Claude Code em modo não interativo (`claude -p`) para gerar anotações organizadas em Markdown. O usuário só aperta um atalho para começar e parar a gravação; todo o resto acontece sozinho.

## 2. Objetivos

- Eliminar o trabalho manual de transcrever e resumir reuniões.
- Gerar notas com resumo, decisões, tarefas, pontos técnicos e dúvidas em aberto.
- Funcionar em segundo plano, iniciando no login, sem intervenção.
- Projeto versionado no GitHub, sem expor dados sensíveis.

## 3. Fora do escopo (por enquanto)

- Suporte a Windows ou macOS.
- Transcrição em tempo real.
- Gravação de tela/vídeo pela ferramenta (vídeos podem ser jogados na pasta manualmente).
- Controle de duplicatas por hash.
- Interface gráfica.

## 4. Fluxo do usuário

1. Usuário aperta o atalho de teclado → começa a gravação (microfone + áudio do sistema).
2. Usuário aperta o atalho de novo → gravação para e o MP3 é salvo em `~/Transcricoes/Entrada`.
3. O serviço detecta o arquivo novo (via inotify/watchdog, sem polling).
4. WhisperX transcreve em português, com diarização.
5. Transcrição bruta é salva em `~/Transcricoes/Brutas`.
6. Script chama `claude -p` com a transcrição e um prompt fixo.
7. Notas em Markdown são salvas em `~/Transcricoes/Notas`.
8. Arquivo original é movido para `~/Transcricoes/Processados`.

## 5. Requisitos técnicos

- **SO:** Linux Mint (PipeWire/PulseAudio).
- **GPU:** NVIDIA (8–12 GB VRAM), drivers e CUDA instalados.
- **Linguagem:** Python 3.10+.
- **Bibliotecas:** watchdog, whisperx (PyTorch com CUDA), python-dotenv.
- **Modelo:** WhisperX `large-v3`, `compute_type=float16`, idioma `pt`.
- **Diarização:** pyannote via token gratuito do Hugging Face (guardado em `.env`).
- **Gravação:** ffmpeg, formato MP3.
- **IA:** Claude Code instalado e logado (usa o plano do usuário).
- **Execução:** serviço de usuário do systemd, iniciando no login, com reinício automático.

## 6. Estrutura de pastas

- `~/Transcricoes/Entrada` – arquivos aguardando processamento
- `~/Transcricoes/Brutas` – transcrições brutas
- `~/Transcricoes/Notas` – notas finais em Markdown
- `~/Transcricoes/Processados` – arquivos originais já tratados
- `~/Transcricoes/logs` – logs do serviço

## 7. Formato da nota gerada

Nome: `AAAA-MM-DD_HHMM_nome-do-arquivo.md`. Seções: Resumo executivo; Decisões tomadas; Tarefas (com responsáveis, quando identificáveis); Pontos técnicos; Dúvidas em aberto. O Claude também deve corrigir termos técnicos mal transcritos.

## 8. Tarefas

São 12 tarefas, cada uma pode ser entregue inteira ao Claude Code. Cada uma tem um critério de pronto.

### T1 ✅ — Preparar o sistema

Rodar `nvidia-smi` para anotar placa, VRAM e versão do CUDA. Instalar `ffmpeg`, `python3-venv` e `git` via apt.
**Pronto quando:** `nvidia-smi` e `ffmpeg -version` funcionam.

### T2 — Criar o repositório

Criar a pasta do projeto, `git init`, repositório no GitHub e `.gitignore` ignorando `.env`, `venv/`, áudios, transcrições, notas e logs.
**Pronto quando:** primeiro commit enviado e `git status` não mostra esses arquivos.

### T3 — Ambiente Python com GPU

Criar o venv, instalar PyTorch com CUDA compatível, WhisperX, watchdog e python-dotenv; gerar `requirements.txt`.
**Pronto quando:** `torch.cuda.is_available()` retorna `True` e `import whisperx` funciona.

### T4 — Credenciais e Claude

Criar token do Hugging Face, aceitar os termos dos modelos pyannote, salvar no `.env` (com `.env.example` sem valor). Confirmar que `claude -p "diga olá"` responde.
**Pronto quando:** os dois funcionam e o `.env` está fora do Git.

### T5 — Configuração, pastas e logs

Criar `config.py` com caminhos, modelo `large-v3`, float16, idioma pt e extensões aceitas. Criar as cinco pastas automaticamente e logs em `~/Transcricoes/logs`.
**Pronto quando:** rodar duas vezes sem erro e o log registrar mensagens.

### T6 — Módulo de transcrição

Transcrever com WhisperX, alinhar palavras, separar falantes, formatar como `[00:01:23] Falante 1: ...`, salvar em `Brutas` e liberar a memória da GPU ao final.
**Pronto quando:** um áudio de teste vira um `.txt` legível com falantes marcados.

### T7 — Módulo de análise com o Claude

Criar `prompt.md` com as seções da nota, chamar `claude -p` via subprocess com timeout e `--allowedTools` mínimo, salvar a nota em `Notas` como `AAAA-MM-DD_HHMM_nome.md` e, se falhar, registrar no log mantendo a transcrição bruta.
**Pronto quando:** uma transcrição de teste vira uma nota completa.

### T8 — Observador da pasta

Usar watchdog em `Entrada`, filtrar formatos, esperar a cópia terminar, processar um arquivo por vez, tratar pendentes ao iniciar e mover para `Processados` após sucesso.
**Pronto quando:** jogar um MP3 na pasta gera a nota sozinho e o arquivo não é reprocessado.

### T9 — Gravação com atalho

Identificar microfone e monitor com `pactl list short sources`, gravar os dois misturados em MP3 com ffmpeg num arquivo temporário, script bash que inicia/para (via PID), avisa com `notify-send` e move o MP3 para `Entrada` ao parar. Configurar o atalho no Mint.
**Pronto quando:** o atalho inicia e para, e a gravação tem as duas vozes.

### T10 — Serviço systemd

Criar `~/.config/systemd/user/transcritor.service` com o Python do venv e `Restart=on-failure`, ativar com `systemctl --user enable --now transcritor`.
**Pronto quando:** o serviço sobe após reiniciar o computador e volta sozinho se for encerrado.

### T11 — README e instalador

README com instalação, token, atalho e comandos do serviço (status, parar, reiniciar, `journalctl --user -u transcritor`), mais um `install.sh` que faz tudo.
**Pronto quando:** uma instalação limpa funciona seguindo só o README.

### T12 — Teste final e publicação

Gravar uma reunião real de alguns minutos, conferir a nota, adicionar licença MIT, revisar segredos e fazer push.
**Pronto quando:** tudo funciona de ponta a ponta e o repositório está publicado sem `.env` nem áudios.

## 9. Riscos e limitações

- Diarização erra com falas sobrepostas ou vozes parecidas; falantes não têm nome.
- Termos técnicos podem sair errados (mitigado pelo Claude).
- Conflitos de versão entre PyTorch, CUDA e WhisperX na instalação.
- Cada nota consome do limite do plano do Claude.
- Gravações contêm dados sensíveis: nunca versionar.

## 10. Ideias futuras

- Renomear falantes automaticamente pelo contexto.
- Enviar notas para Notion, Obsidian ou Google Drive.
- Suporte a Windows e macOS separando núcleo e adaptadores por sistema.
