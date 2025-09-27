#!/bin/bash

# MoJoAssistant Installation Script
# This script sets up MoJoAssistant with easy installation and configuration

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check if Python version is compatible
check_python_version() {
    if ! command_exists python3; then
        print_error "Python 3 is not installed. Please install Python 3.8 or higher."
        exit 1
    fi
    
    python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    required_version="3.8"
    
    if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
        print_error "Python 3.8 or higher is required. Found Python $python_version"
        exit 1
    fi
    
    print_success "Python $python_version is compatible"
}

# Function to create virtual environment
create_venv() {
    print_status "Creating virtual environment..."
    
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        print_success "Virtual environment created"
    else
        print_warning "Virtual environment already exists"
    fi
}

# Function to activate virtual environment
activate_venv() {
    print_status "Activating virtual environment..."
    
    # Detect the shell
    if [ -n "$ZSH_VERSION" ]; then
        source venv/bin/activate
    elif [ -n "$BASH_VERSION" ]; then
        source venv/bin/activate
    else
        print_warning "Unknown shell. Please activate manually: source venv/bin/activate"
    fi
    
    print_success "Virtual environment activated"
}

# Function to install dependencies
install_dependencies() {
    print_status "Installing dependencies..."
    
    # Upgrade pip
    pip install --upgrade pip
    
    # Install requirements
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
        print_success "Dependencies installed"
    else
        print_error "requirements.txt not found"
        exit 1
    fi
}

# Function to create environment file
create_env_file() {
    print_status "Creating environment configuration..."
    
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            cp .env.example .env
            print_success "Environment file created from template"
            print_warning "Please edit .env file with your API keys and configuration"
        else
            print_error ".env.example not found"
            exit 1
        fi
    else
        print_warning "Environment file already exists"
    fi
}

# Function to create directories
create_directories() {
    print_status "Creating necessary directories..."
    
    # Create memory directory
    mkdir -p .memory
    mkdir -p .memory/archival_memory
    mkdir -p .memory/knowledge_base
    mkdir -p .memory/embeddings
    
    print_success "Directories created"
}

# Function to download initial models (optional)
download_models() {
    print_status "Checking for embedding models..."
    
    # Try to initialize the embedding system to download models
    if python3 -c "
import sys
sys.path.insert(0, 'app')
from app.memory.simplified_embeddings import SimpleEmbedding
try:
    embeddings = SimpleEmbedding()
    print('Embedding system initialized successfully')
except Exception as e:
    print(f'Warning: Could not initialize embeddings: {e}')
    sys.exit(1)
"; then
        print_success "Embedding system ready"
    else
        print_warning "Could not initialize embedding system. Models will be downloaded on first use."
    fi
}

# Function to run tests
run_tests() {
    print_status "Running installation tests..."
    
    if python3 test_comprehensive.py; then
        print_success "All tests passed"
    else
        print_warning "Some tests failed. Installation may have issues."
    fi
}

# Function to create startup scripts
create_startup_scripts() {
    print_status "Creating startup scripts..."
    
    # Create start script
    cat > start_mojo.sh << 'EOF'
#!/bin/bash
# MoJoAssistant Startup Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Start the MCP server
echo "Starting MoJoAssistant MCP Server..."
python3 start_mcp_service.py
EOF
    
    # Create CLI script
    cat > mojo_cli.sh << 'EOF'
#!/bin/bash
# MoJoAssistant CLI Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Start the interactive CLI
echo "Starting MoJoAssistant Interactive CLI..."
python3 app/interactive-cli.py
EOF
    
    # Make scripts executable
    chmod +x start_mojo.sh
    chmod +x mojo_cli.sh
    
    print_success "Startup scripts created: start_mojo.sh, mojo_cli.sh"
}

# Function to show post-installation message
show_post_install() {
    echo ""
    echo "=========================================="
    echo "🎉 MoJoAssistant Installation Complete!"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "1. Edit .env file with your API keys:"
    echo "   - OPENAI_API_KEY (for OpenAI services)"
    echo "   - ANTHROPIC_API_KEY (for Claude services)"
    echo "   - GOOGLE_API_KEY (for web search)"
    echo ""
    echo "2. Test your installation:"
    echo "   ./start_mojo.sh    # Start MCP server"
    echo "   ./mojo_cli.sh      # Start interactive CLI"
    echo ""
    echo "3. Run tests:"
    echo "   python3 test_comprehensive.py"
    echo ""
    echo "4. View documentation:"
    echo "   cat README.md"
    echo ""
    echo "=========================================="
}

# Main installation process
main() {
    echo "🚀 Starting MoJoAssistant Installation..."
    echo "=========================================="
    
    # Check requirements
    check_python_version
    
    # Setup environment
    create_venv
    activate_venv
    
    # Install dependencies
    install_dependencies
    
    # Configure environment
    create_env_file
    create_directories
    
    # Optional: Download models
    download_models
    
    # Create startup scripts
    create_startup_scripts
    
    # Run tests
    run_tests
    
    # Show completion message
    show_post_install
}

# Run main function
main "$@"