import axios, { AxiosInstance } from 'axios';
import * as fs from 'fs';
import * as readline from 'readline';

// --- MCPClient Class for Backend Integration ---
class MCPClient {
    private client: AxiosInstance;

    constructor(private baseUrl: string, private apiKey: string) {
        this.baseUrl = baseUrl.replace(/\$/, '');
        this.client = axios.create({
            baseURL: this.baseUrl,
            headers: { 'X-API-Key': this.apiKey },
            timeout: 30000,
        });
    }

    private async makeRequest(method: 'get' | 'post', endpoint: string, data?: any): Promise<any> {
        try {
            const response = await this.client[method](endpoint, data);
            return response.data;
        } catch (error) {
            if (axios.isAxiosError(error)) {
                throw new Error(`HTTP Request failed: ${error.message}`);
            }
            throw error;
        }
    }

    async getMemoryContext(query: string, maxItems: number = 10): Promise<any> {
        return this.makeRequest('post', '/api/v1/memory/context', { query, max_items: maxItems });
    }

    async searchKnowledgeBase(query: string): Promise<any> {
        return this.getMemoryContext(query); // Simulate
    }

    async searchConversations(query: string): Promise<any> {
        return this.getMemoryContext(query); // Simulate
    }

    async addDocuments(documents: any[]): Promise<any> {
        return this.makeRequest('post', '/api/v1/knowledge/documents', { documents });
    }

    async getCurrentConversation(): Promise<any> {
        return this.makeRequest('get', '/api/v1/conversation/current');
    }

    async endConversation(): Promise<any> {
        return this.makeRequest('post', '/api/v1/conversation/end');
    }

    async getMemoryStats(): Promise<any> {
        return this.makeRequest('get', '/api/v1/memory/stats');
    }

    async listEmbeddingModels(): Promise<any> {
        return this.makeRequest('get', '/api/v1/embeddings/models');
    }

    async switchEmbeddingModel(model_name: string): Promise<any> {
        return this.makeRequest('post', '/api/v1/embeddings/switch', { model_name });
    }
}

// --- Main Stdio Handling Logic ---
async function main() {
    const apiKey = process.env.MCP_API_KEY;
    const baseUrl = 'https://ai.avengergear.com';

    if (!apiKey) {
        console.error(JSON.stringify({ error: 'MCP_API_KEY environment variable not set' }));
        process.exit(1);
    }

    const client = new MCPClient(baseUrl, apiKey);

    let apiDescription: any;
    try {
        const configPath = process.env.MCP_CONFIG_PATH || `${process.env.HOME}/.config/mcp/mojo-assistant`;
        apiDescription = JSON.parse(fs.readFileSync(`${configPath}/mcp_api_description.json`, 'utf-8'));
    } catch (error) {
        console.error(JSON.stringify({ error: `mcp_api_description.json not found: ${error}` }));
        process.exit(1);
    }

    const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout,
        terminal: false,
    });

    for await (const line of rl) {
        try {
            const request = JSON.parse(line);
            let response: any;
            const requestId = request.id;

            switch (request.method) {
                case 'initialize':
                    response = { jsonrpc: '2.0', id: requestId, result: { capabilities: { tool_provider: true } } };
                    break;

                case 'ListTools':
                    response = { jsonrpc: '2.0', id: requestId, result: { tools: apiDescription } };
                    break;

                case 'CallTool':
                    const { name, arguments: args } = request.params;
                    try {
                        let result;
                        switch (name) {
                            case 'get_memory_context': result = await client.getMemoryContext(args.query, args.max_items); break;
                            case 'search_knowledge_base': result = await client.searchKnowledgeBase(args.query); break;
                            case 'search_conversations': result = await client.searchConversations(args.query); break;
                            case 'add_documents': result = await client.addDocuments(args.documents); break;
                            case 'get_current_conversation': result = await client.getCurrentConversation(); break;
                            case 'end_conversation': result = await client.endConversation(); break;
                            case 'get_memory_stats': result = await client.getMemoryStats(); break;
                            case 'list_embedding_models': result = await client.listEmbeddingModels(); break;
                            case 'switch_embedding_model': result = await client.switchEmbeddingModel(args.model_name); break;
                            default: throw new Error(`Unknown tool: ${name}`);
                        }
                        response = { jsonrpc: '2.0', id: requestId, result: { content: [{ type: 'text', text: JSON.stringify(result) }] } };
                    } catch (e) {
                        response = { jsonrpc: '2.0', id: requestId, error: { code: -32000, message: (e as Error).message } };
                    }
                    break;
            }

            if (response) {
                process.stdout.write(JSON.stringify(response) + '\n');
            }
        } catch (e) {
            console.error(JSON.stringify({ error: `Unhandled error in main loop: ${e}` }));
        }
    }
}

main().catch(err => {
    console.error(JSON.stringify({ error: `Fatal error: ${err}` }));
    process.exit(1);
});
