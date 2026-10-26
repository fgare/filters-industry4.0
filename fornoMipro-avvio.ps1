# ================= CONFIGURAZIONE =================
$cartellaComandi      = "C:\GTW-IO_LR01_ARCHIVIO\Comandi\Forno Mipro"
$cartellaCommesseIn   = "C:\Users\Administrator.SRV2019\Documents\FornoMipro\INcommesse"
$scriptPython         = "C:\Users\Administrator.SRV2019\Documents\FornoMipro\forno_mipro.py"
$cartellaCommesseOut  = "C:\Users\Administrator.SRV2019\Documents\FornoMipro\OUTcommesse"
$cartellaArchivioTemp = "C:\GTW-IO_LR01_ARCHIVIO"
$cartellaArchivioPerm = "C:\GTW-IO_LR01_ARCHIVIO_PERMANENTE"

$nomeStatico = "Forno Mipro"  # Modifica con il nome statico desiderato

# Percorso dello script di attivazione venv relativo alla cartella dello script python
$cartellaScriptPython = Split-Path -Path $scriptPython -Parent
$scriptActivate       = Join-Path -Path $cartellaScriptPython -ChildPath "fornoMipro\Scripts\Activate.ps1"
# ==================================================

# 1. Controlla e sposta i file da "comandi" a "commesse in"
$fileComandi = Get-ChildItem -Path $cartellaComandi -File
if ($fileComandi) {
    Move-Item -Path "$cartellaComandi\*" -Destination $cartellaCommesseIn -Force
}

echo "Spostati comandi"

# 2. Attiva il venv, esegue lo script Python e disattiva il venv
if (Test-Path -Path $scriptActivate) {
    & $scriptActivate
}

python $scriptPython

if (Get-Command deactivate -ErrorAction SilentlyContinue) {
    deactivate
}

echo "Script python terminato"

# 3. Controlla i file in "commesse out" e li copia negli archivi
$fileCommesseOut = Get-ChildItem -Path $cartellaCommesseOut -File
if ($fileCommesseOut) {

    # Copia diretta in archivio temp
    Copy-Item -Path "$cartellaCommesseOut\*" -Destination $cartellaArchivioTemp -Force

    # Copia in archivio perm organizzata in <nome>/<anno><mese>
    foreach ($file in $fileCommesseOut) {
        $annoMese = $file.LastWriteTime.ToString("yyyyMM")
        $destinazionePerm = Join-Path -Path $cartellaArchivioPerm -ChildPath "$nomeStatico\$annoMese"

        if (-not (Test-Path -Path $destinazionePerm)) {
            New-Item -ItemType Directory -Path $destinazionePerm -Force | Out-Null
        }

        Copy-Item -Path $file.FullName -Destination $destinazionePerm -Force
    }

    # Eliminazione dei file dalla cartella di origine dopo aver completato le copie
    Remove-Item -Path "$cartellaCommesseOut\*" -Force
}

echo "telemetrie copiate ed eliminate"