# Lanceur de demarrage ATLAS. Attache a la tache "ATLAS Dashboard" qui se
# declenche de facon FIABLE a chaque ouverture de session (contrairement aux
# reveils programmes ou aux declencheurs horaires qui ratent souvent).
#
# 1. Lance le rattrapage EN ARRIERE-PLAN (idempotent: ne fait rien si le run
#    du jour a deja reussi). Ne retarde donc pas l'affichage du dashboard.
# 2. Lance le dashboard au PREMIER PLAN (processus principal, tourne en continu).
#
# Resultat: des que le PC demarre, un run manque est rattrape automatiquement.

$py = "C:\bot trading\atlas\.venv\Scripts\python.exe"
Set-Location "C:\bot trading\atlas"

Start-Process -FilePath $py -ArgumentList "-m", "atlas.pipelines.catchup" `
    -WorkingDirectory "C:\bot trading\atlas" -WindowStyle Hidden

& $py -m streamlit run "atlas\dashboard\app.py" --server.headless true --server.port 8501
