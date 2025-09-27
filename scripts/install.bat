@echo off
REM MoJoAssistant Windows Installation Script
REM This script sets up MoJoAssistant with easy installation and configuration

setlocal enabledelayedexpansion

REM Colors for output (Windows 10+)
set "RED=[91m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "NC=[0m"

REM Function to print colored output
:print_status
echo %BLUE%[INFO]%NC% %~1
goto :eof

:print_success
echo %GREEN%[SUCCESS]%NC% %~1
goto :eof

:print_warning
echo %YELLOW%[WARNING]%NC% %~1
goto :eof

:print_error
echo %RED%[ERROR]%NC% %~1
goto :eof

REM Function to check if Python is installed
:check_python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    call :print_error "Python is not installed. Please install Python 3.8 or higher from https://python.org"
    exit /b 1
)

REM Check Python version
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set python_version=%%i
call :print_success "Python !python_version! found"
goto :eof

REM Function to create virtual environment
:create_venv
call :print_status "Creating virtual environment..."

if not exist "venv" (
    python -m venv venv
    call :print_success "Virtual environment created"
) else (
    call :print_warning "Virtual environment already exists"
)
goto :eof

REM Function to install dependencies
:install_deps
call :print_status "Installing dependencies..."

REM Upgrade pip
python -m pip install --upgrade pip

REM Install requirements
if exist "requirements.txt" (
    pip install -r requirements.txt
    call :print_success "Dependencies installed"
) else (
    call :print_error "requirements.txt not found"
    exit /b 1
)
goto :eof

REM Function to create environment file
:create_env
call :print_status "Creating environment configuration..."

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env"
        call :print_success "Environment file created from template"
        call :print_warning "Please edit .env file with your API keys and configuration"
    ) else (
        call :print_error ".env.example not found"
        exit /b 1
    )
) else (
    call :print_warning "Environment file already exists"
)
goto :eof

REM Function to create directories
:create_dirs
call :print_status "Creating necessary directories..."

if not exist ".memory" mkdir .memory
if not exist ".memory\archival_memory" mkdir .memory\archival_memory
if not exist ".memory\knowledge_base" mkdir .memory\knowledge_base
if not exist ".memory\embeddings" mkdir .memory\embeddings

call :print_success "Directories created"
goto :eof

REM Function to download initial models (optional)
:download_models
call :print_status "Checking for embedding models..."

REM Try to initialize the embedding system
python -c "import sys; sys.path.insert(0, 'app'); from app.memory.simplified_embeddings import SimpleEmbedding; embeddings = SimpleEmbedding(); print('Embedding system initialized successfully')" 2>nul
if %errorlevel% equ 0 (
    call :print_success "Embedding system ready"
) else (
    call :print_warning "Could not initialize embedding system. Models will be downloaded on first use."
)
goto :eof

REM Function to create startup scripts
:create_scripts
call :print_status "Creating startup scripts..."

REM Create start script
echo @echo off > start_mojo.bat
echo REM MoJoAssistant Windows Startup Script >> start_mojo.bat
echo. >> start_mojo.bat
echo if exist "venv\Scripts\activate.bat" ( >> start_mojo.bat
echo     call "venv\Scripts\activate.bat" >> start_mojo.bat
echo ) >> start_mojo.bat
echo. >> start_mojo.bat
echo echo Starting MoJoAssistant MCP Server... >> start_mojo.bat
echo python start_mcp_service.py >> start_mojo.bat

REM Create CLI script
echo @echo off > mojo_cli.bat
echo REM MoJoAssistant Windows CLI Script >> mojo_cli.bat
echo. >> mojo_cli.bat
echo if exist "venv\Scripts\activate.bat" ( >> mojo_cli.bat
echo     call "venv\Scripts\activate.bat" >> mojo_cli.bat
echo ) >> mojo_cli.bat
echo. >> mojo_cli.bat
echo echo Starting MoJoAssistant Interactive CLI... >> mojo_cli.bat
echo python app\interactive-cli.py >> mojo_cli.bat

call :print_success "Startup scripts created: start_mojo.bat, mojo_cli.bat"
goto :eof

REM Function to show post-installation message
:show_post_install
echo.
echo ==========================================
echo 🎉 MoJoAssistant Installation Complete!
echo ==========================================
echo.
echo Next steps:
echo 1. Edit .env file with your API keys:
echo    - OPENAI_API_KEY (for OpenAI services)
echo    - ANTHROPIC_API_KEY (for Claude services)
echo    - GOOGLE_API_KEY (for web search)
echo.
echo 2. Test your installation:
echo    start_mojo.bat    REM Start MCP server
echo    mojo_cli.bat      REM Start interactive CLI
echo.
echo 3. Run tests:
echo    python test_comprehensive.py
echo.
echo 4. View documentation:
echo    type README.md
echo.
echo ==========================================
goto :eof

REM Main installation process
:main
echo 🚀 Starting MoJoAssistant Installation...
echo ==========================================

REM Check requirements
call :check_python

REM Setup environment
call :create_venv

REM Install dependencies
call :install_deps

REM Configure environment
call :create_env
call :create_dirs

REM Optional: Download models
call :download_models

REM Create startup scripts
call :create_scripts

REM Show completion message
call :show_post_install

echo.
echo Installation complete! Press any key to exit...
pause >nul
exit /b 0

REM Start the main process
call :main