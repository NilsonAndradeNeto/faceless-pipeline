# Cria as tarefas automáticas no Agendador de Tarefas do Windows (usuário atual, sem admin).
# Rodar de novo atualiza as tarefas. Para remover: Get-ScheduledTask "Faceless*" | Unregister-ScheduledTask -Confirm:$false
#
#   03:00            → escreve 1 roteiro PT e 1 ES (ficam esperando aprovação no painel)
#   21:30 e 13:00    → produz os vídeos aprovados (21:30 = logo após a cota de imagens renovar)
#   ao ligar o PC    → abre o painel em http://localhost:3200

$raiz = Split-Path -Parent $PSScriptRoot
$py = Join-Path $raiz ".venv\Scripts\pythonw.exe"   # pythonw = sem janela preta
if (-not (Test-Path $py)) { throw "Ambiente Python não encontrado. Rode 'uv sync' em $raiz" }

$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew -Priority 7

function Tarefa($nome, $args_, $gatilhos, $descricao) {
    $acao = New-ScheduledTaskAction -Execute $py -Argument $args_ -WorkingDirectory $raiz
    Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilhos -Settings $config `
        -Description $descricao -Force | Out-Null
    Write-Host "OK  $nome"
}

Tarefa "Faceless - Roteiro PT" "-m scripts.novo_roteiro --lang pt" `
    (New-ScheduledTaskTrigger -Daily -At 03:00) "Pesquisa e escreve 1 roteiro em português"
Tarefa "Faceless - Roteiro ES" "-m scripts.novo_roteiro --lang es" `
    (New-ScheduledTaskTrigger -Daily -At 03:20) "Pesquisa e escreve 1 roteiro em espanhol"
Tarefa "Faceless - Produzir videos" "-m pipeline.produzir --todos" `
    @((New-ScheduledTaskTrigger -Daily -At 21:30), (New-ScheduledTaskTrigger -Daily -At 13:00)) `
    "Transforma roteiros aprovados em vídeos (um por vez, prioridade baixa)"
Tarefa "Faceless - Painel" "-m streamlit run review_app/app.py --server.port 3200 --server.headless true" `
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) "Painel de aprovação em http://localhost:3200"
