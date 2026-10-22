@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 优先用项目自带的虚拟环境，没有才退回系统 Python
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

echo [1/2] 安装依赖...
rem 必须走官方源：清华源缺 PySide6-Essentials，装到一半会失败
"%PY%" -m pip install -i https://pypi.org/simple -r requirements.txt pyinstaller
if errorlevel 1 goto fail

echo [2/2] 打包 exe...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name WeChatToast ^
  --icon icon.ico ^
  --collect-submodules winrt ^
  --hidden-import winrt.windows.applicationmodel ^
  --hidden-import winrt.windows.ui.notifications.management ^
  --hidden-import winrt.windows.ui.notifications ^
  main.py
if errorlevel 1 goto fail

rem 配置在 %APPDATA%\WeChatToast 下，不用往 dist 里拷 config.json
echo.
echo 打包完成: dist\WeChatToast.exe
pause
exit /b 0

:fail
echo.
echo 打包失败，请检查上面的错误信息。
pause
exit /b 1
