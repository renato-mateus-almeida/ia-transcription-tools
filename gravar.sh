#!/usr/bin/env bash
# Liga/desliga a gravação de reunião (microfone + áudio do sistema). Chamado pelo atalho
# Ctrl+Shift+Alt+F7 no Cinnamon. Cada chamada alterna: se não está gravando, começa; se está, para.
#
# - Grava em Entrada/.reuniao_AAAA-MM-DD_HHMMSS.mp3 (nome oculto: o observador ignora) e, ao
#   parar, renomeia para Entrada/reuniao_...mp3 — é aí que o observador pega o arquivo.
# - Um processo "guardião" acompanha o ffmpeg e é o único que finaliza (renomeia e avisa), seja
#   pelo atalho, pelo limite de duração ou por queda do ffmpeg.
# - Usa sempre o microfone padrão e o monitor da saída padrão atual (HDMI, fone Bluetooth...).
#
# Variáveis opcionais (para testes): TRANSCRICOES_DIR, GRAVACAO_ESTADO, GRAVACAO_MICROFONE,
# GRAVACAO_SISTEMA, GRAVACAO_LIMITE (segundos).
set -u

BASE="${TRANSCRICOES_DIR:-$HOME/Transcricoes}"
ENTRADA="$BASE/Entrada"
LOG="$BASE/logs/gravacao.log"
# "PID_DO_FFMPEG NOME_DO_ARQUIVO". Não mudar XDG_RUNTIME_DIR para testes: o áudio (PipeWire) depende dele.
ESTADO="${GRAVACAO_ESTADO:-${XDG_RUNTIME_DIR:-/tmp}/transcritor-gravacao}"
MICROFONE="${GRAVACAO_MICROFONE:-default}"
SISTEMA="${GRAVACAO_SISTEMA:-@DEFAULT_MONITOR@}"
LIMITE="${GRAVACAO_LIMITE:-14400}"                        # 4 horas
ATALHO="Ctrl+Shift+Alt+F7"

mkdir -p "$ENTRADA" "$(dirname "$LOG")"

registrar() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
avisar() {  # título, ícone, texto
    notify-send -a "Transcritor" -i "$2" "$1" "${3:-}" 2>/dev/null || true
}
duracao() {  # mm:ss (ou h:mm:ss) de um arquivo de áudio
    local s
    s=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null)
    s=${s%.*}; s=${s:-0}
    if (( s >= 3600 )); then printf '%d:%02d:%02d' $((s / 3600)) $((s % 3600 / 60)) $((s % 60))
    else printf '%02d:%02d' $((s / 60)) $((s % 60)); fi
}
ffmpeg_gravando() {  # imprime "PID NOME" de um ffmpeg vivo gravando em Entrada/.reuniao_*
    local pid args nome
    for pid in $(pgrep -x ffmpeg); do
        args=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null) || continue
        if [[ "$args" == *"$ENTRADA/.reuniao_"* ]]; then
            nome="${args##*"$ENTRADA/."}"
            echo "$pid ${nome%% *}"
            return 0
        fi
    done
    return 1
}
gravando() {  # verdadeiro se há gravação em andamento (reconstrói o estado se ele sumiu)
    local pid achado
    if [[ -f "$ESTADO" ]]; then
        read -r pid _ < "$ESTADO"
        [[ -n "$pid" && "$(ps -p "$pid" -o comm= 2>/dev/null)" == "ffmpeg" ]] && return 0
    fi
    achado=$(ffmpeg_gravando) || return 1
    echo "$achado" > "$ESTADO"
    registrar "Estado reconstruído a partir do ffmpeg em execução: $achado"
}

# Renomeia uma gravação oculta para o nome visível (o observador a pega nesse instante).
finalizar() {  # caminho_oculto, código_de_saída_do_ffmpeg
    local oculto="$1" codigo="$2" nome final d
    nome="${oculto##*/.}"
    final="$ENTRADA/$nome"
    if [[ ! -s "$oculto" ]]; then
        rm -f "$oculto"
        registrar "ERRO: gravação $nome vazia (código do ffmpeg: $codigo)"
        avisar "❌ Gravação falhou" dialog-error "Nada foi gravado. Veja $LOG"
        return 1
    fi
    d=$(duracao "$oculto")
    mv "$oculto" "$final"
    if [[ "$codigo" == 0 ]]; then
        registrar "Gravação $nome encerrada pelo limite de $LIMITE s ($d)"
        avisar "⏹ Limite de gravação atingido ($d)" media-playback-stop "$nome será transcrita"
    else
        registrar "Gravação salva: $nome ($d)"
        avisar "✅ Gravação salva ($d)" emblem-ok-symbolic "$nome será transcrita"
    fi
}

# Gravações ocultas que ficaram para trás (desligamento no meio, processo morto à força).
recuperar_orfas() {
    local f em_uso
    em_uso=$(ps -eo args=)
    for f in "$ENTRADA"/.reuniao_*.mp3; do
        [[ -e "$f" ]] || continue
        [[ "$em_uso" == *"$f"* ]] && continue  # ainda sendo gravado por algum processo
        registrar "Recuperando gravação órfã: ${f##*/}"
        finalizar "$f" "recuperada"
    done
}

# Processo guardião: roda o ffmpeg, espera ele terminar e finaliza.
guardiao() {  # nome_do_arquivo
    local nome="$1" oculto="$ENTRADA/.$1" pid codigo
    ffmpeg -nostdin -hide_banner -loglevel error -y \
        -f pulse -i "$MICROFONE" -f pulse -i "$SISTEMA" \
        -filter_complex "amix=inputs=2:duration=longest" -t "$LIMITE" \
        -ac 1 -ar 16000 -c:a libmp3lame -b:a 64k "$oculto" >> "$LOG" 2>&1 < /dev/null &
    pid=$!
    echo "$pid $nome" > "$ESTADO"
    wait "$pid"
    codigo=$?
    finalizar "$oculto" "$codigo"
    rm -f "$ESTADO"  # só depois de finalizar: ninguém mexe no arquivo enquanto ele é renomeado
}

iniciar() {
    recuperar_orfas
    local nome="reuniao_$(date +%Y-%m-%d_%H%M%S).mp3"
    registrar "Iniciando gravação $nome | microfone: $MICROFONE ($(pactl get-default-source 2>/dev/null)) | sistema: $SISTEMA ($(pactl get-default-sink 2>/dev/null).monitor)"
    setsid "$0" --guardiao "$nome" < /dev/null > /dev/null 2>&1 &
    sleep 1.5
    if gravando; then
        avisar "🔴 Gravando..." media-record "Aperte $ATALHO de novo para parar"
    else
        registrar "ERRO: o ffmpeg não iniciou (veja as linhas acima)"   # o guardião já avisou
    fi
}

parar() {
    local pid nome i
    read -r pid nome < "$ESTADO"
    registrar "Parando gravação $nome"
    kill -INT "$pid" 2>/dev/null
    for i in $(seq 1 150); do  # espera até 15 s o guardião finalizar
        [[ -f "$ESTADO" ]] || return 0
        sleep 0.1
    done
    registrar "AVISO: ffmpeg não parou com SIGINT; enviando SIGTERM"
    kill -TERM "$pid" 2>/dev/null
}

case "${1:-}" in
    --guardiao) guardiao "$2" ;;
    "")
        if gravando; then
            parar
        elif [[ -f "$ESTADO" ]]; then
            # Estado sem ffmpeg vivo: o guardião foi morto à força. Recupera e não inicia outra.
            rm -f "$ESTADO"
            recuperar_orfas
        else
            iniciar
        fi
        ;;
    *) echo "Uso: $0   (sem argumentos: liga/desliga a gravação)" >&2; exit 2 ;;
esac
