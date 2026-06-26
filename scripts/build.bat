@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Build swe-cli.exe
echo ═══ Building swe-cli.exe ═══
echo.

REM ── 检查 PyInstaller ──────────────────────────────────────
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found on PATH.
    exit /b 1
)

python -c "import PyInstaller" 2>nul
if %ERRORLEVEL% neq 0 (
    echo [INFO] PyInstaller not found. Installing...
    pip install "pyinstaller>=6.0"
    echo.
)

REM ── 检查 UPX 压缩器 ──────────────────────────────────────
where upx >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [INFO] UPX found — exe will be compressed.
) else (
    echo [INFO] UPX not found — exe will be larger.
    echo       Recommend installing UPX: https://upx.github.io/
)
echo.

REM ── 清理之前构建 ──────────────────────────────────────────
echo [STEP] Cleaning previous builds...
if exist dist rmdir /s /q dist >nul
if exist build rmdir /s /q build >nul

REM ── 安装项目依赖 ──────────────────────────────────────────
echo [STEP] Ensuring project dependencies...
pip install -e ".[build]" >nul

REM ── 执行打包 ──────────────────────────────────────────────
echo [STEP] Running PyInstaller...
python -m PyInstaller swe-cli.spec --clean --noconfirm
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Build failed!
    exit /b %ERRORLEVEL%
)

REM ── 验证结果 ──────────────────────────────────────────────
echo.
echo ═══ Build Complete ═══
if exist dist\swe-cli.exe (
    for %%I in (dist\swe-cli.exe) do (
        set FILESIZE=%%~zI
        set /a FILESIZE_MB=%%~zI / (1024*1024)
        echo [OK] dist\swe-cli.exe  (%%~zI bytes / !FILESIZE_MB! MB)
    )
    echo.
    echo To install globally, run:
    echo   scripts\install.bat
    echo.
    echo Usage:
    echo   swe-cli.exe                  REPL 交互模式
    echo   swe-cli.exe --check          检查配置
    echo   swe-cli.exe --task "修复 bug"  直接执行任务
) else (
    echo [WARN] Output not found at dist\swe-cli.exe
)

echo.
pause
