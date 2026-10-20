@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] 安装依赖...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail

echo [2/2] 打包 exe...
python -m PyInstaller --noconfirm --onefile --noconsole ^
  --name WeChatToast ^
  --icon icon.ico ^
  --collect-submodules winrt ^
  --hidden-import winrt.windows.ui.notifications.management ^
  --hidden-import winrt.windows.ui.notifications ^
  main.py
if errorlevel 1 goto fail

copy /y config.json dist\config.json >nul
echo.
echo 打包完成: dist\WeChatToast.exe
pause
exit /b 0

:fail
echo.
echo 打包失败，请检查上面的错误信息。
pause
exit /b 1
