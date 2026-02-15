# Google Custom Search API Setup

This document explains how to set up Google Custom Search API for the web search functionality in MoJoAssistant.

## Overview

The web search feature uses Google Custom Search API as the primary search engine, with DuckDuckGo as a fallback. Google API provides much higher quality search results compared to DuckDuckGo.

## Prerequisites

1. Google Account
2. Google Cloud Project
3. Credit card (for API usage - free tier available)

## Step-by-Step Setup

### 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Note your Project ID

### 2. Enable Custom Search API

1. In your Google Cloud Project, go to "APIs & Services" > "Library"
2. Search for "Custom Search API"
3. Click "Enable"

### 3. Create API Key

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "API key"
3. Copy the API key
4. **Important**: Click "Edit API Key" to restrict it to only Custom Search API

### 4. Create Custom Search Engine

1. Go to [Programmable Search Engine](https://programmablesearchengine.google.com/)
2. Click "Add" to create a new search engine
3. Configure your search engine:
   - What to search: "Search the entire web"
   - Name: Your preferred name
   - Language: English (or your preferred language)
4. Click "Create"
5. Note your "Search engine ID" (it looks like: `012345678901234567890:abcdef123456`)

### 5. Set Up Environment Variables

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` file with your credentials:
   ```bash
   # Google Custom Search API Configuration
   GOOGLE_API_KEY=your_actual_api_key_here
   GOOGLE_SEARCH_ENGINE_ID=your_actual_search_engine_id_here
   
   # MCP Server Configuration
   MCP_REQUIRE_AUTH=false
   
   # Optional: Logging level
   LOG_LEVEL=INFO
   ```

### 6. Test the Setup

Start the MCP server and test web search:

```bash
# Load environment variables
source .env

# Start the server
python3 unified_mcp_server.py --mode http --port 8000

# Test web search in another terminal
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "web_search", "arguments": {"query": "python programming tutorials", "max_results": 5}}}'
```

## Cost and Usage

### Free Tier
- 100 search queries per day
- No cost for the first 100 queries/day

### Paid Usage
- $5 per 1000 queries after the free tier
- Monitor usage in Google Cloud Console

## Troubleshooting

### Common Issues

1. **"HTTP Error 400: Bad Request"**
   - Check if your API key is correct
   - Ensure Custom Search API is enabled
   - Verify your search engine ID

2. **"No API key found"**
   - Make sure `.env` file exists and has correct values
   - Check environment variables are loaded

3. **Poor search results**
   - Ensure your search engine is configured to search "the entire web"
   - Check if your search engine ID is correct

### Debug Mode

Enable debug logging to troubleshoot issues:

```bash
LOG_LEVEL=DEBUG python3 unified_mcp_server.py --mode http --port 8000
```

## Alternative: DuckDuckGo Only

If you don't want to use Google API, the system will automatically fall back to DuckDuckGo. However, the search quality will be significantly lower.

To use only DuckDuckGo:
1. Leave `GOOGLE_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID` empty in `.env`
2. Or comment them out:
   ```bash
   # GOOGLE_API_KEY=your_google_api_key_here
   # GOOGLE_SEARCH_ENGINE_ID=your_search_engine_id_here
   ```

## Security Notes

- Never commit your actual API keys to version control
- The `.env` file is already ignored in `.gitignore`
- Restrict your API keys to specific services in Google Cloud Console
- Monitor API usage regularly to prevent unexpected charges