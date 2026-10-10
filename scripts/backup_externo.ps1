<# ----------------------------------------------------------------------
   backup_externo.ps1  –  Snapshot semanal para discos externos / NAS
   ----------------------------------------------------------------------
   O QUE FAZ
     • Copia a base de dados (cópia consistente, sem parar a aplicação)
     • Compacta o código do projeto (sem a base de dados nem lixo)
     • Inclui o ficheiro .env (segredos) na snapshot
     • (Opcional) exporta a imagem Docker
     • Envia tudo para vários destinos (local + NAS) e mantém N cópias
     • Barra de progresso + log

   COMPLEMENTA o backup DIÁRIO interno (contentor "backup"), que guarda
   cópias em database\backups\auto\ na própria máquina. Este script é a
   camada EXTERNA (fora da máquina).

   Compatível com PowerShell 5.1.
------------------------------------------------------------------------#>

# ====================== CONFIGURAÇÃO (ajuste aqui) ======================
$Projeto    = 'C:\Caminho\Para\ProjetoWeb'          # raiz do projeto novo
$Container  = 'projetoweb-web-1'                          # nome do container web (confirme com: docker ps)
$Imagem     = 'projetoweb-web:latest'                     # tag da imagem (confirme com: docker images)

$Destinos   = @(
    'D:\ProjetoBackup',                       # 2º disco / local
    '\\NAS\Partilha\ProjetoBackup'        # NAS / rede
)
$Retencao        = 6        # quantas snapshots manter em cada destino
$IncluirImagem   = $false   # $true para exportar também a imagem Docker (ficheiro grande)
$LogFile         = 'C:\Scripts\backup_log.txt'
# ========================================================================

# Caminhos derivados
$DB_Ativa   = Join-Path $Projeto 'database\assistencias.db'
$Dir_Auto   = Join-Path $Projeto 'database\backups\auto'
$Env_File   = Join-Path $Projeto '.env'

# ---- consola em UTF-8 (evita acentos trocados) ----
if ([Console]::OutputEncoding.WebName -ne 'utf-8') {
    chcp 65001 > $null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
}

# ---- garantir pasta do log ----
$LogDir = Split-Path $LogFile -Parent
if (-not (Test-Path $LogDir)) { New-Item $LogDir -ItemType Directory -Force | Out-Null }

Start-Transcript -Path $LogFile -Append

function Step ([string]$msg, [int]$pct) {
    Write-Progress -Id 1 -Activity 'Snapshot ProjetoWeb' -Status $msg -PercentComplete $pct
    Write-Host ">> $msg"
}

try {
    $stamp  = Get-Date -Format 'yyyy-MM-dd_HHmm'
    $tmpDir = Join-Path $env:TEMP "snapshot_$stamp"
    Remove-Item $tmpDir -Recurse -Force -EA SilentlyContinue
    New-Item $tmpDir -ItemType Directory | Out-Null

    # 1 -------- BASE DE DADOS (prioridade) --------
    Step '1/5  A obter a base de dados...' 10
    $gzMaisRecente = Get-ChildItem $Dir_Auto -Filter 'assistencias-*.db.gz' -EA SilentlyContinue |
                     Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($gzMaisRecente) {
        # usa a cópia consistente já produzida pelo backup diário (sem downtime)
        Copy-Item $gzMaisRecente.FullName "$tmpDir\database.db.gz" -Force
        Write-Host "   (usada cópia consistente: $($gzMaisRecente.Name))"
    }
    elseif (Test-Path $DB_Ativa) {
        # fallback: parar o container, copiar o ficheiro, reiniciar
        Write-Host "   (sem cópia .gz; a parar o container para copiar em segurança)"
        docker stop $Container | Out-Null
        Copy-Item $DB_Ativa "$tmpDir\assistencias.db" -Force
        docker start $Container | Out-Null
    }
    else {
        throw "Base de dados não encontrada em $DB_Ativa nem em $Dir_Auto"
    }

    # 2 -------- .env (segredos) --------
    Step '2/5  A incluir o .env...' 25
    if (Test-Path $Env_File) {
        Copy-Item $Env_File "$tmpDir\.env" -Force   # contém SECRET_KEY e TUNNEL_TOKEN
    } else {
        Write-Host "   (.env não encontrado — ignorado)"
    }

    # 3 -------- CÓDIGO (sem a base de dados nem lixo) --------
    Step '3/5  A compactar o código...' 45
    $arquivos = Get-ChildItem $Projeto -Recurse -File | Where-Object {
        $_.FullName -notmatch '\\database\\' -and
        $_.FullName -notmatch '\\instance\\' -and
        $_.FullName -notmatch '\\__pycache__\\' -and
        $_.FullName -notmatch '\\.git\\'
    }
    Compress-Archive -Path $arquivos.FullName `
                     -DestinationPath "$tmpDir\ProjetoWeb.zip" `
                     -CompressionLevel Optimal -Force

    # 4 -------- IMAGEM DOCKER (opcional) --------
    if ($IncluirImagem) {
        Step '4/5  A exportar a imagem Docker (pode demorar)...' 65
        docker save -o "$tmpDir\projetoweb_img.tar" $Imagem
    } else {
        Step '4/5  Imagem Docker ignorada (reconstrói-se com docker compose build)' 65
    }

    # 5 -------- COPIAR PARA OS DESTINOS + RETENÇÃO --------
    $i = 0
    foreach ($dest in $Destinos) {
        $i++
        try {
            if (-not (Test-Path $dest)) { New-Item $dest -ItemType Directory -Force | Out-Null }
            $alvo = Join-Path $dest "snapshot_$stamp"
            New-Item $alvo -ItemType Directory -Force | Out-Null
            Copy-Item "$tmpDir\*" $alvo -Recurse -Force
            Step "5/5  Copiado para $dest" (80 + $i*5)

            # retenção: manter só as N snapshots mais recentes
            $pastas = Get-ChildItem $dest -Directory -Filter 'snapshot_*' |
                      Sort-Object Name -Descending
            if ($pastas.Count -gt $Retencao) {
                $pastas | Select-Object -Skip $Retencao | Remove-Item -Recurse -Force
            }
        }
        catch {
            Write-Host "!!! Falha a copiar para $dest : $($_.Exception.Message)" -f Yellow
        }
    }

    Step 'Backup concluído com SUCESSO' 100
    Write-Host "`n*** Backup concluído com sucesso ***" -f Green
}
catch {
    Write-Progress -Id 1 -Activity 'Snapshot ProjetoWeb' -Completed
    Write-Host "!!! Falha no backup: $($_.Exception.Message)" -f Red
}
finally {
    Remove-Item $tmpDir -Recurse -Force -EA SilentlyContinue
    Stop-Transcript
}
