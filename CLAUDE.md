# Transcritor Automático de Reuniões (Linux Mint)

Ferramenta pessoal que grava reuniões (microfone + áudio do sistema) com um atalho de teclado,
transcreve com WhisperX (português, com diarização via pyannote) e usa `claude -p` para gerar
notas em Markdown (resumo, decisões, tarefas, pontos técnicos, dúvidas). Roda em segundo plano
como serviço de usuário do systemd, observando `~/Transcricoes/Entrada`.

## Fonte da verdade: `docs/PRD.md`

- **Leia `docs/PRD.md` inteiro no início de toda sessão**, antes de qualquer outra coisa.
- `docs/PRD.md` é a versão de trabalho (convertida de `docs/PRD.pdf`, o original). O status das
  tarefas é marcado no `.md`; o PDF não é editado.
- A próxima tarefa é a primeira da seção 8 sem `✅`.

## Fluxo de trabalho (obrigatório)

1. Trabalhar **uma tarefa do PRD por vez** (T1, T2, ...), na ordem.
2. Antes de executar, **apresentar um plano curto e esperar aprovação** do usuário.
3. Ao terminar, verificar o critério **"Pronto quando"** da tarefa e mostrar ao usuário como testar.
4. **Só avançar depois que o usuário confirmar** que o teste passou.
5. Marcar a tarefa como concluída no PRD (ex.: `### T1 ✅ — Preparar o sistema`) e **sugerir uma
   mensagem de commit**. Commit/push só quando o usuário pedir.
   **Commits e PRs sem atribuição ao Claude:** não adicionar `Co-Authored-By: Claude ...` nem
   linhas "Generated with Claude Code" (decisão do usuário; vale sobre o padrão do Claude Code).
6. **Nunca colocar segredos** (token do Hugging Face etc.) no código nem no Git: usar `.env`
   (versionar só `.env.example`, sem valores).
7. Responder em português.

## Ambiente

- Linux Mint 22.3 (base Ubuntu 24.04 "noble"), PipeWire/PulseAudio.
- GPU NVIDIA GeForce RTX 3060, 12 GB VRAM (12288 MiB), compute capability 8.6.
- Driver NVIDIA 595.99.02; `nvidia-smi` reporta **CUDA 13.2** (versão máxima suportada pelo driver).
  O toolkit CUDA (`nvcc`) não está instalado e não é necessário: as wheels do PyTorch trazem o
  runtime CUDA próprio — escolher na T3 uma build de CUDA ≤ 13.2.
- Stack Python (T3, versões exatas em `requirements.txt`): whisperx 3.8.6, torch 2.8.0+cu128
  (WhisperX exige `torch~=2.8.0`), pyannote-audio 4.0.7, ctranslate2 4.9.0, faster-whisper 1.2.1.
  Instalar com `venv/bin/pip install -r requirements.txt`.
- **Armadilha conhecida:** `av` 19 é incompatível com o `decode_audio` do faster-whisper 1.2.1
  (`TypeError: ... 'metadata_errors'`). Sempre carregar áudio com `whisperx.load_audio()` (usa o
  ffmpeg CLI) e passar o array ao modelo — nunca passar o caminho do arquivo direto ao faster-whisper.
- Claude Code CLI standalone em `~/.local/bin/claude` (instalador oficial; caminho fixo, usar no
  serviço). Não usar o binário do app desktop (`~/.config/Claude/claude-code/<versão>/...`), que muda
  a cada atualização. Login compartilhado via `~/.claude/.credentials.json`.
- **Armadilha conhecida (T7):** `claude -p` rodado com cwd dentro do projeto carrega este CLAUDE.md
  (e lê o PRD). Ao gerar notas, rodar o subprocess com `cwd` fora do repositório (ex.: `~/Transcricoes`)
  e sem as variáveis `CLAUDECODE`/`CLAUDE_CODE_*` herdadas.
- VRAM medida na T6: transcrição large-v3 ~4,8 GB; alinhamento ~0,6 GB; diarização mostra pico de
  ~10 GB no `nvidia-smi`, mas é uso oportunista (com limite de 1,7 GB funciona igual, pico real
  ~1,6 GB). Não é risco de falta de memória.
- **Armadilha conhecida (T9):** a saída de áudio muda (HDMI, fone Bluetooth, Yeti...). Nunca fixar
  nomes de dispositivos: gravar com `-f pulse -i default` (microfone padrão) e
  `-f pulse -i @DEFAULT_MONITOR@` (monitor da saída padrão atual), testado com fone Bluetooth.
- Python 3.12 com venv (`venv/` na raiz do projeto, fora do Git).
- Comandos com `sudo` (ex.: `apt install`) são executados pelo usuário no terminal dele;
  o Claude informa o comando exato e depois verifica o resultado.

## Decisões técnicas fixadas no PRD

- Modelo WhisperX `large-v3`, `compute_type=float16`, idioma `pt`; liberar memória da GPU após cada arquivo.
- Pastas: `~/Transcricoes/{Entrada,Brutas,Notas,Processados,logs}` (criadas automaticamente).
- Transcrição bruta no formato `[00:01:23] Falante 1: ...`.
- Nota: `AAAA-MM-DD_HHMM_nome-do-arquivo.md`, com as seções Resumo executivo; Decisões tomadas;
  Tarefas (com responsáveis, quando identificáveis); Pontos técnicos; Dúvidas em aberto.
- `claude -p` chamado via `subprocess` com timeout e `--allowedTools` mínimo; em falha, registrar
  no log e manter a transcrição bruta.
- Observador com watchdog (sem polling), um arquivo por vez, mover para `Processados` após sucesso.
- Nunca versionar: `.env`, `venv/`, áudios/vídeos, transcrições, notas, logs.
