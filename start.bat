@echo off
@chcp 65001
if exist "_HasNotBeenConfigured" (
    echo 第一次执行警告: 请先打开 config.yaml 配置文件和 ./apis/dglab/config.yaml 配置文件配置
    timeout /t 5
    del _HasNotBeenConfigured
)
pip install uv
uv sync
uv run .\main.py
pause
