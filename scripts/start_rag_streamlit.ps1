# 启动产业链知识库 Streamlit（供 Hub「知识库问答」iframe 嵌入）
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$rag = Join-Path $root "rag\langchain-agent"
$python = Join-Path $root "metaforge-test-env\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "未找到虚拟环境: $python"
    Write-Host "请先在项目根目录创建 metaforge-test-env"
    exit 1
}

Set-Location $rag
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
Write-Host "启动 Streamlit: http://127.0.0.1:8501"
Write-Host "Hub 嵌入页: http://127.0.0.1:8008/new-ui/home/knowledge"
& $python -m streamlit run app.py --server.headless true --browser.gatherUsageStats false
