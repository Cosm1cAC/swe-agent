@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title swe-cli 全局安装工具

echo ═══ Installing swe-cli globally ═══
echo.

REM ── 检查 exe 是否存在 ──────────────────────────────────────
if not exist "%~dp0..\dist\swe-cli.exe" (
    echo [X] dist\swe-cli.exe not found!
    echo     Run scripts\build.bat first to build the executable.
    pause
    exit /b 1
)

REM ── 安装目录: %USERPROFILE%\.swe-agent\bin ────────────────
set "INSTALL_DIR=%USERPROFILE%\.swe-agent\bin"
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo [STEP] Copying swe-cli.exe to %INSTALL_DIR%...
copy /Y "%~dp0..\dist\swe-cli.exe" "%INSTALL_DIR%\swe-cli.exe" >nul
if %ERRORLEVEL% neq 0 (
    echo [X] Failed to copy executable!
    pause
    exit /b 1
)

REM ── 同目录放 .env.example 方便用户参考 ────────────────────
if exist "%~dp0..\.env.example" (
    copy /Y "%~dp0..\.env.example" "%USERPROFILE%\.swe-agent\.env.example" >nul
)
echo [OK] Executable installed.
echo.

REM ── 检查 PATH 是否已包含安装目录 ──────────────────────────
echo %PATH% | findstr /i /c:"%INSTALL_DIR%" >nul
if %ERRORLEVEL% equ 0 (
    echo [OK] %INSTALL_DIR% already in PATH.
) else (
    echo [!] %INSTALL_DIR% is NOT in your PATH.
    echo.
    echo 是否立即将 swe-agent 添加到系统 PATH？
    echo (需要管理员权限，或者你可以手动添加)
    echo.
    set /p ADD_PATH="添加到 PATH？(Y/n): "
    if /i "!ADD_PATH!"=="" set ADD_PATH=y
    if /i "!ADD_PATH!"=="y" (
        echo.
        echo 正在将 %INSTALL_DIR% 添加到当前用户的 PATH...

        REM ── 两种方式: 注册表 / setx 二选一 ──────────────
        REM 优先用 setx (不需要管理员, 但新 cmd 窗口生效)
        setx PATH "!INSTALL_DIR!;%PATH%" >nul
        if !ERRORLEVEL! equ 0 (
            echo [OK] PATH 已更新 (下次打开命令行生效)。
        ) else (
            echo [!] setx 失败, 尝试注册表方式...
            for /f "skip=2 tokens=3*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "CUR_PATH=%%a %%b"
            if not defined CUR_PATH set "CUR_PATH="
            reg add "HKCU\Environment" /v PATH /t REG_EXPAND_SZ /d "!INSTALL_DIR!;!CUR_PATH!" /f >nul
            if !ERRORLEVEL! equ 0 (
                echo [OK] 注册表 PATH 已更新 (重启或重新登录后生效)。
            ) else (
                echo [X] 自动添加 PATH 失败。
                echo     请手动将以下路径添加到系统 PATH:
                echo       !INSTALL_DIR!
            )
        )
    ) else (
        echo [INFO] 跳过 PATH 修改。
        echo       请手动将以下路径添加到环境变量 PATH:
        echo         %INSTALL_DIR%
    )
)

echo.
echo ═══ Install Complete ═══
echo.
echo 现在可以在 PowerShell / CMD 中直接运行:
echo   swe-cli
echo   swe-cli --check
echo   swe-cli --task "修复代码中的 bug"
echo.
echo 配置文件需放置 .env 到运行目录:
echo   %USERPROFILE%\.swe-agent\.env.example  (参考)
echo.
pause
