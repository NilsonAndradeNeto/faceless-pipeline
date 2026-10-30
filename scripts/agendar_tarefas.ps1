# Cria as tarefas automáticas no Agendador de Tarefas do Windows (usuário atual, sem admin).
# Rodar de novo atualiza. Para remover tudo:
#   Get-ScheduledTask "Faceless*" | Unregister-ScheduledTask -Confirm:$false
#
#   a cada 15 min  → scripts.ciclo: faz o que estiver na hora (horários em config/settings.yaml → agenda)
#   ao ligar o PC  → abre o painel em http://localhost:3200

$raiz = Split-Path -Parent $PSScriptRoot
$py = Join-Path $raiz ".venv\Scripts\pythonw.exe"   # pythonw = sem janela preta
if (-not (Test-Path $py)) { throw "Ambiente Python não encontrado. Rode 'uv sync' em $raiz" }

$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew -Priority 7

# Remove as tarefas da versão anterior (horários fixos), se existirem
Get-ScheduledTask "Faceless - Roteiro*", "Faceless - Produzir*" -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

$cada15 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "Faceless - Ciclo" -Settings $config -Force `
    -Action (New-ScheduledTaskAction -Execute $py -Argument "-m scripts.ciclo" -WorkingDirectory $raiz) `
    -Trigger $cada15 -Description "Gera roteiros, aprova no prazo, produz e publica nos horários" | Out-Null
Write-Host "OK  Faceless - Ciclo (a cada 15 min)"

Register-ScheduledTask -TaskName "Faceless - Painel" -Settings $config -Force `
    -Action (New-ScheduledTaskAction -Execute $py -WorkingDirectory $raiz `
        -Argument "-m streamlit run review_app/app.py --server.port 3200 --server.headless true") `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) `
    -Description "Painel de aprovação em http://localhost:3200" | Out-Null
Write-Host "OK  Faceless - Painel (ao ligar o PC)"
