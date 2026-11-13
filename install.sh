#!/usr/bin/env bash
# Instalador do Transcritor Automático de Reuniões (Linux Mint / Ubuntu, GPU NVIDIA).
# Pode ser executado quantas vezes quiser: só faz o que ainda falta.
#
# Uso: ./install.sh [opções]
#   --sim          responde "sim" a todas as perguntas (não pede o token)
#   --sem-modelos  não baixa os modelos agora (depois: venv/bin/python baixar_modelos.py)
#   --sem-servico  não instala/ativa o serviço systemd do usuário
#   --sem-atalho   não cria o atalho de teclado no Cinnamon
#   -h, --help     mostra esta ajuda
set -euo pipefail

PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$PROJETO/venv"
PY="$VENV/bin/python"
CLAUDE_BIN="$HOME/.local/bin/claude"
UNIDADE="$HOME/.config/systemd/user/transcritor.service"
TECLAS="<Primary><Shift><Alt>F7"
TECLAS_LEGIVEL="Ctrl+Shift+Alt+F7"
URL_TOKEN="https://huggingface.co/settings/tokens"
URL_TERMOS="https://huggingface.co/pyannote/speaker-diarization-community-1"

SIM=0 SEM_MODELOS=0 SEM_SERVICO=0 SEM_ATALHO=0
PENDENCIAS=()

if [[ -t 1 ]]; then
    AZUL=$'\033[94m' VERDE=$'\033[92m' AMARELO=$'\033[93m' VERMELHO=$'\033[91m' NEGRITO=$'\033[1m' NORMAL=$'\033[0m'
else
    AZUL="" VERDE="" AMARELO="" VERMELHO="" NEGRITO="" NORMAL=""
fi
passo()  { echo; echo "${NEGRITO}${AZUL}==> $*${NORMAL}"; }
ok()     { echo "  ${VERDE}✔${NORMAL} $*"; }
aviso()  { echo "  ${AMARELO}!${NORMAL} $*"; }
erro()   { echo "  ${VERMELHO}✘ $*${NORMAL}" >&2; }
falhar() { erro "$*"; exit 1; }
perguntar() {  # pergunta sim/não (padrão: sim)
    (( SIM )) && return 0
    local resposta
    read -r -p "  $1 [S/n] " resposta
    [[ -z "$resposta" || "$resposta" =~ ^[sSyY] ]]
}

for arg in "$@"; do
    case "$arg" in
        --sim|-y)      SIM=1 ;;
        --sem-modelos) SEM_MODELOS=1 ;;
        --sem-servico) SEM_SERVICO=1 ;;
        --sem-atalho)  SEM_ATALHO=1 ;;
        -h|--help)     sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             falhar "Opção desconhecida: $arg (veja --help)" ;;
    esac
done

cd "$PROJETO"
echo "${NEGRITO}Transcritor Automático de Reuniões — instalação${NORMAL}"
echo "Projeto: $PROJETO"

# --- 1. Sistema --------------------------------------------------------------
passo "1/8 Verificando o sistema"
[[ "$(uname -s)" == "Linux" ]] || falhar "Este instalador é só para Linux."
command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1 \
    || falhar "GPU NVIDIA não encontrada (nvidia-smi falhou). Instale o driver da NVIDIA e tente de novo."
ok "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"

faltando=()
command -v ffmpeg      >/dev/null || faltando+=(ffmpeg)
command -v git         >/dev/null || faltando+=(git)
command -v pactl       >/dev/null || faltando+=(pulseaudio-utils)
command -v notify-send >/dev/null || faltando+=(libnotify-bin)
python3 -c "import ensurepip" 2>/dev/null || faltando+=(python3-venv)
if (( ${#faltando[@]} )); then
    aviso "Pacotes ausentes: ${faltando[*]}"
    perguntar "Instalar com apt (pede a sua senha de administrador)?" \
        || falhar "Instale manualmente: sudo apt install ${faltando[*]}"
    sudo apt-get update && sudo apt-get install -y "${faltando[@]}"
fi
ok "Pacotes do sistema: ffmpeg, git, pactl, notify-send, python3-venv"

versao=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] <= (3, 13)))' \
    || falhar "Python $versao não suportado: o WhisperX exige Python 3.10 a 3.13."
ok "Python $versao"

# --- 2. Ambiente Python --------------------------------------------------------
passo "2/8 Ambiente Python (venv + dependências; a primeira vez baixa alguns GB)"
if [[ ! -x "$PY" ]]; then
    python3 -m venv "$VENV"
    ok "venv criado em $VENV"
fi
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet --progress-bar off -r requirements.txt
"$PY" -c "import torch, whisperx; assert torch.cuda.is_available()" 2>/dev/null \
    || falhar "As dependências instalaram, mas o PyTorch não enxerga a GPU (torch.cuda.is_available() = False)."
ok "Dependências instaladas; PyTorch enxerga a GPU"

# --- 3. Credenciais ------------------------------------------------------------
passo "3/8 Token do Hugging Face (para a separação de falantes)"
if [[ ! -f .env ]]; then
    cp .env.example .env
    ok ".env criado a partir do .env.example"
fi
chmod 600 .env
token=$(sed -n 's/^HF_TOKEN=//p' .env | tr -d '[:space:]')
if [[ -n "$token" ]]; then
    ok "HF_TOKEN presente no .env (valor não exibido)"
else
    echo "  1) Crie um token do tipo 'Read' em: $URL_TOKEN"
    echo "  2) Aceite os termos do modelo em:   $URL_TERMOS"
    if (( ! SIM )) && [[ -t 0 ]]; then
        read -r -s -p "  Cole o token (Enter para pular): " token
        echo
    fi
    if [[ "$token" =~ ^hf_[A-Za-z0-9]+$ ]]; then
        # Grava via variável de ambiente (o token não aparece na linha de comando de nenhum processo).
        NOVO_TOKEN="$token" "$PY" - <<'EOF'
import os, re
from pathlib import Path
env = Path(".env")
env.write_text(re.sub(r"(?m)^HF_TOKEN=.*$", "HF_TOKEN=" + os.environ["NOVO_TOKEN"], env.read_text()))
EOF
        ok "Token salvo no .env"
    else
        [[ -n "$token" ]] && erro "Formato de token inválido (deveria começar com hf_)."
        token=""
        aviso "Sem token: a separação de falantes não vai funcionar até ele ser configurado."
        PENDENCIAS+=("Colocar o token em $PROJETO/.env (linha HF_TOKEN=...) e rodar: $PY baixar_modelos.py")
    fi
fi

# --- 4. Claude Code --------------------------------------------------------------
passo "4/8 Claude Code (gera as notas)"
if [[ ! -x "$CLAUDE_BIN" ]]; then
    aviso "Claude Code não encontrado em $CLAUDE_BIN"
    if perguntar "Instalar com o instalador oficial (https://claude.ai/install.sh)?"; then
        curl -fsSL https://claude.ai/install.sh | bash
    fi
fi
if [[ -x "$CLAUDE_BIN" ]]; then
    ok "Claude Code $("$CLAUDE_BIN" --version 2>/dev/null | head -1)"
    if [[ ! -f "$HOME/.claude/.credentials.json" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
        aviso "Claude Code ainda sem login."
        PENDENCIAS+=("Fazer login no Claude Code: rode 'claude' uma vez e siga as instruções")
    fi
else
    PENDENCIAS+=("Instalar o Claude Code: curl -fsSL https://claude.ai/install.sh | bash")
fi

# --- 5. Modelos ------------------------------------------------------------------
passo "5/8 Modelos de IA (~5 GB na primeira vez, ficam em ~/.cache/huggingface)"
if (( SEM_MODELOS )); then
    aviso "Pulado (--sem-modelos). Depois: $PY baixar_modelos.py"
elif [[ -z "$token" ]]; then
    aviso "Pulado: falta o token do Hugging Face."
elif "$PY" baixar_modelos.py; then
    ok "Modelos prontos"
else
    erro "Não foi possível baixar/conferir os modelos (veja as mensagens acima)."
    PENDENCIAS+=("Resolver o erro acima e rodar: $PY baixar_modelos.py")
fi

# --- 6. Pastas de trabalho -------------------------------------------------------
passo "6/8 Pastas de trabalho"
"$PY" config.py >/dev/null 2>&1 || falhar "Falha ao criar as pastas (rode '$PY config.py' para ver o erro)."
chmod +x gravar.sh
ok "Pastas prontas: Entrada, Brutas, Notas, Processados e logs em ${TRANSCRICOES_DIR:-~/Transcricoes}"

# --- 7. Serviço systemd ----------------------------------------------------------
passo "7/8 Serviço em segundo plano (systemd do usuário)"
if (( SEM_SERVICO )); then
    aviso "Pulado (--sem-servico). Para testar à mão: $PY observador.py"
else
    mkdir -p "$(dirname "$UNIDADE")"
    cat > "$UNIDADE" <<EOF
[Unit]
Description=Transcritor automático de reuniões (observa ~/Transcricoes/Entrada)
Documentation=https://github.com/renato-mateus-almeida/ia-transcription-tools
# Se falhar 5 vezes em 5 minutos, desiste (evita reiniciar sem parar quando algo está quebrado).
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=$PROJETO
ExecStart="$PY" "$PROJETO/observador.py"
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
# Prioridade de CPU um pouco menor, para o desktop seguir responsivo durante a transcrição.
Nice=5

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable transcritor >/dev/null 2>&1
    systemctl --user restart transcritor
    sleep 2
    if [[ "$(systemctl --user is-active transcritor)" == "active" ]]; then
        ok "Serviço 'transcritor' ativo e habilitado no login"
    else
        erro "O serviço não ficou ativo. Veja: journalctl --user -u transcritor -n 30"
        PENDENCIAS+=("Verificar o serviço: journalctl --user -u transcritor -n 30")
    fi
fi

# --- 8. Atalho de teclado --------------------------------------------------------
passo "8/8 Atalho de teclado para gravar ($TECLAS_LEGIVEL)"
configurar_atalho() {
    local base="org.cinnamon.desktop.keybindings"
    local caminho="/org/cinnamon/desktop/keybindings/custom-keybindings"
    local nomes=() n p
    mapfile -t nomes < <(gsettings get "$base" custom-list | grep -oE "custom[0-9]+" || true)
    for n in "${nomes[@]}"; do
        p="$base.custom-keybinding:$caminho/$n/"
        if [[ "$(gsettings get "$p" command)" == "'$PROJETO/gravar.sh'" ]]; then
            ok "Atalho já configurado: $(gsettings get "$p" binding)"
            return
        fi
        if gsettings get "$p" binding | grep -qF "'$TECLAS'"; then
            aviso "$TECLAS_LEGIVEL já é usado pelo atalho $(gsettings get "$p" name)."
            PENDENCIAS+=("Criar um atalho para $PROJETO/gravar.sh com outra tecla (Configurações > Teclado > Atalhos)")
            return
        fi
    done
    perguntar "Criar o atalho $TECLAS_LEGIVEL para iniciar/parar a gravação?" || { aviso "Atalho não criado."; return; }
    n=0
    while printf '%s\n' "${nomes[@]}" | grep -qx "custom$n"; do n=$((n + 1)); done
    p="$base.custom-keybinding:$caminho/custom$n/"
    gsettings set "$p" name "Transcritor: iniciar/parar gravação"
    gsettings set "$p" command "$PROJETO/gravar.sh"
    gsettings set "$p" binding "['$TECLAS']"
    nomes+=("custom$n")
    gsettings set "$base" custom-list "[$(printf "'%s', " "${nomes[@]}" | sed 's/, $//')]"
    ok "Atalho $TECLAS_LEGIVEL criado (Configurações > Teclado > Atalhos > Atalhos personalizados)"
}
if (( SEM_ATALHO )); then
    aviso "Pulado (--sem-atalho)."
elif [[ "${XDG_CURRENT_DESKTOP:-}" == *Cinnamon* ]] && command -v gsettings >/dev/null; then
    configurar_atalho
else
    aviso "Desktop não é Cinnamon: crie o atalho manualmente."
    PENDENCIAS+=("Criar um atalho de teclado que execute: $PROJETO/gravar.sh")
fi

# --- Resumo ----------------------------------------------------------------------
echo
if (( ${#PENDENCIAS[@]} )); then
    echo "${NEGRITO}${AMARELO}Instalação concluída, com pendências:${NORMAL}"
    for item in "${PENDENCIAS[@]}"; do echo "  • $item"; done
else
    echo "${NEGRITO}${VERDE}Instalação concluída!${NORMAL}"
fi
cat <<EOF

Como usar:
  • Gravar uma reunião: ${TECLAS_LEGIVEL} para começar e de novo para parar.
  • Ou copie um áudio/vídeo para ~/Transcricoes/Entrada.
  • As notas aparecem em ~/Transcricoes/Notas.
  • Acompanhar o serviço: journalctl --user -u transcritor -f
EOF
