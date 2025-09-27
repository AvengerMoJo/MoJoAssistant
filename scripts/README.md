# MoJoAssistant Deployment Scripts

This directory contains deployment scripts and configurations for MoJoAssistant Beta 1.0.

## Available Scripts

### 1. Installation Scripts

#### `install.sh` (Linux/macOS)
Automated installation script for Unix-based systems.

**Features:**
- Python version checking
- Virtual environment creation
- Dependency installation
- Environment configuration
- Directory creation
- Model initialization
- Startup script generation

**Usage:**
```bash
chmod +x scripts/install.sh
./scripts/install.sh
```

#### `install.bat` (Windows)
Windows batch script for automated installation.

**Features:**
- Python version checking
- Virtual environment creation
- Dependency installation
- Environment configuration
- Directory creation
- Model initialization
- Startup script generation

**Usage:**
```cmd
scripts\install.bat
```

### 2. Docker Deployment

#### `Dockerfile`
Multi-stage Dockerfile for containerized deployment.

**Features:**
- Python 3.9 slim base image
- System dependencies installation
- Python package installation
- Security best practices (non-root user)
- Health checks
- Optimized layer caching

**Usage:**
```bash
# Build the image
docker build -f scripts/Dockerfile -t mojo-assistant .

# Run the container
docker run -d \
  --name mojo-assistant \
  -p 8000:8000 \
  -v $(pwd)/data:/app/.memory \
  -e OPENAI_API_KEY=your-api-key \
  mojo-assistant
```

#### `docker-compose.yml`
Docker Compose configuration for easy deployment.

**Features:**
- Service orchestration
- Environment variable management
- Volume mounting for persistence
- Network configuration
- Health checks
- Optional services (Redis, Nginx)

**Usage:**
```bash
# Copy environment file
cp .env.example .env

# Edit .env with your API keys
# Then start the services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### 3. Quick Start Scripts

#### `start_mojo.sh` / `start_mojo.bat`
Start the MCP server after installation.

**Usage:**
```bash
# Linux/macOS
./start_mojo.sh

# Windows
start_mojo.bat
```

#### `mojo_cli.sh` / `mojo_cli.bat`
Start the interactive CLI after installation.

**Usage:**
```bash
# Linux/macOS
./mojo_cli.sh

# Windows
mojo_cli.bat
```

## Deployment Options

### 1. Local Development
Best for development and testing.

```bash
# Install dependencies
./scripts/install.sh

# Start services
./start_mojo.sh &
./mojo_cli.sh
```

### 2. Production Docker Deployment
Best for consistent production environments.

```bash
# Build and run with Docker
docker build -f scripts/Dockerfile -t mojo-assistant .
docker run -d --name mojo-assistant -p 8000:8000 mojo-assistant

# Or use Docker Compose
docker-compose up -d
```

### 3. Cloud Deployment
For cloud platforms like AWS, GCP, or Azure.

```bash
# Build for cloud
docker build -f scripts/Dockerfile -t mojo-assistant:latest .

# Push to container registry
docker tag mojo-assistant:latest your-registry/mojo-assistant:latest
docker push your-registry/mojo-assistant:latest
```

## Configuration

### Environment Variables
Create a `.env` file from `.env.example`:

```env
# LLM Configuration
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
GOOGLE_API_KEY=your-google-key

# Search Configuration
GOOGLE_SEARCH_ENGINE_ID=your-search-engine-id

# MCP Configuration
MCP_API_KEY=your-mcp-api-key

# Optional: Local model paths
LOCAL_MODEL_PATH=/path/to/local/models
```

### Configuration Files
- `config/embedding_config.json` - Embedding model configuration
- `config/llm_config.json` - LLM backend configuration
- `config/mcp_config.json` - MCP server configuration

## Data Persistence

### Local Installation
- Memory data: `.memory/` directory
- Configuration: `config/` directory
- Logs: `logs/` directory (created automatically)

### Docker Deployment
- Mount volumes for data persistence:
  ```yaml
  volumes:
    - ./data:/app/.memory
    - ./config:/app/config
    - ./logs:/app/logs
  ```

## Monitoring & Logging

### Health Checks
The MCP server includes health check endpoints:
- `GET /system/health` - System health status
- `GET /system/info` - Service information

### Logging
Configure logging in `config/logging_config.py`:
- Log levels (DEBUG, INFO, WARNING, ERROR)
- Log file rotation
- Console and file output

### Monitoring
Optional monitoring with Docker:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/system/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

## Troubleshooting

### Common Issues

1. **Python Version Issues**
   - Ensure Python 3.8+ is installed
   - Use the installation script to set up virtual environment

2. **Permission Issues**
   - Make sure scripts are executable: `chmod +x *.sh`
   - Check directory permissions

3. **Docker Issues**
   - Ensure Docker is running: `docker info`
   - Check port conflicts: `netstat -tulpn | grep 8000`

4. **Memory Issues**
   - Monitor memory usage: `htop` or `docker stats`
   - Consider using smaller embedding models

### Debug Mode
Enable debug logging:
```bash
export DEBUG=true
python start_mcp_service.py
```

### Testing
Run comprehensive tests:
```bash
python test_comprehensive.py
```

## Security Considerations

### API Key Management
- Never commit API keys to version control
- Use environment variables or secret management
- Rotate API keys regularly

### Network Security
- Use HTTPS in production
- Implement firewall rules
- Monitor for suspicious activity

### Data Privacy
- Memory data is stored locally by default
- Consider encryption for sensitive data
- Regular backups of memory data

## Performance Optimization

### System Requirements
- **Minimum**: 4GB RAM, 2 CPU cores
- **Recommended**: 8GB+ RAM, 4+ CPU cores
- **High Performance**: 16GB+ RAM, 8+ CPU cores, GPU

### Optimization Tips
1. Use GPU acceleration if available
2. Choose appropriate embedding models
3. Enable caching for better performance
4. Monitor system resources regularly

## Support

For issues with deployment:
1. Check the troubleshooting section
2. Review logs for error messages
3. Run diagnostic tests
4. Check GitHub issues for similar problems

For additional support:
- Create a GitHub issue
- Join community discussions
- Contact the development team