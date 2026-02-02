"""Web UI route."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

WEB_UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aria - Vector Database Browser</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <style>
        [x-cloak] { display: none !important; }
    </style>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
    <div x-data="app()" x-init="init()" class="container mx-auto px-4 py-8">
        <!-- Header -->
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-purple-400 mb-2">Aria Vector Database</h1>
            <p class="text-gray-400">Browse and search your training data embeddings</p>
        </header>

        <!-- Stats Cards -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
                <div class="text-sm text-gray-400">Total Documents</div>
                <div class="text-2xl font-bold text-purple-400" x-text="stats.lancedb?.total_documents?.toLocaleString() || '-'"></div>
            </div>
            <div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
                <div class="text-sm text-gray-400">Unique Files</div>
                <div class="text-2xl font-bold text-green-400" x-text="stats.summary?.unique_files?.toLocaleString() || '-'"></div>
            </div>
            <div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
                <div class="text-sm text-gray-400">Embedding Dimension</div>
                <div class="text-2xl font-bold text-blue-400" x-text="stats.lancedb?.embedding_dim || '-'"></div>
            </div>
            <div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
                <div class="text-sm text-gray-400">Avg Quality Score</div>
                <div class="text-2xl font-bold text-yellow-400" x-text="stats.summary?.avg_quality_score?.toFixed(3) || '-'"></div>
            </div>
        </div>

        <!-- Tabs -->
        <div class="mb-6">
            <nav class="flex space-x-4">
                <button @click="activeTab = 'search'"
                    :class="activeTab === 'search' ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'"
                    class="px-4 py-2 rounded-lg transition-colors">
                    Search
                </button>
                <button @click="activeTab = 'browse'; loadFiles()"
                    :class="activeTab === 'browse' ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'"
                    class="px-4 py-2 rounded-lg transition-colors">
                    Browse Files
                </button>
                <button @click="activeTab = 'stats'"
                    :class="activeTab === 'stats' ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'"
                    class="px-4 py-2 rounded-lg transition-colors">
                    Statistics
                </button>
            </nav>
        </div>

        <!-- Search Tab -->
        <div x-show="activeTab === 'search'" x-cloak>
            <div class="bg-gray-800 rounded-lg p-6 mb-6 border border-gray-700">
                <form @submit.prevent="performSearch()">
                    <div class="flex gap-4">
                        <input type="text" x-model="searchQuery" placeholder="Enter search query..."
                            class="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-3 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500">
                        <select x-model="topK" class="bg-gray-700 border border-gray-600 rounded-lg px-4 py-3 text-white">
                            <option value="5">5 results</option>
                            <option value="10" selected>10 results</option>
                            <option value="25">25 results</option>
                            <option value="50">50 results</option>
                        </select>
                        <button type="submit" :disabled="searching"
                            class="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 px-6 py-3 rounded-lg font-medium transition-colors">
                            <span x-show="!searching">Search</span>
                            <span x-show="searching">Searching...</span>
                        </button>
                    </div>
                </form>
            </div>

            <!-- Search Results -->
            <div x-show="searchResults.length > 0" class="space-y-4">
                <h3 class="text-lg font-semibold text-gray-300">
                    Found <span x-text="searchResults.length"></span> results
                </h3>
                <template x-for="(result, index) in searchResults" :key="result.id">
                    <div class="bg-gray-800 rounded-lg p-4 border border-gray-700 hover:border-purple-500 transition-colors">
                        <div class="flex justify-between items-start mb-2">
                            <div>
                                <span class="text-purple-400 font-mono text-sm" x-text="result.file_id"></span>
                                <span class="text-gray-500 text-sm ml-2">chunk #<span x-text="result.chunk_index"></span></span>
                            </div>
                            <div class="flex items-center gap-3">
                                <span class="text-sm">
                                    <span class="text-gray-500">Score:</span>
                                    <span class="text-green-400 font-mono" x-text="result.score.toFixed(4)"></span>
                                </span>
                                <span class="text-sm">
                                    <span class="text-gray-500">Quality:</span>
                                    <span class="text-yellow-400 font-mono" x-text="result.quality_score?.toFixed(2) || 'N/A'"></span>
                                </span>
                            </div>
                        </div>
                        <p class="text-gray-300 text-sm leading-relaxed" x-text="result.text"></p>
                    </div>
                </template>
            </div>

            <div x-show="searchResults.length === 0 && searched && !searching" class="text-center py-12">
                <p class="text-gray-400">No results found for your query.</p>
            </div>
        </div>

        <!-- Browse Tab -->
        <div x-show="activeTab === 'browse'" x-cloak>
            <div class="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
                <table class="w-full">
                    <thead class="bg-gray-700">
                        <tr>
                            <th class="px-4 py-3 text-left text-sm font-medium text-gray-300">File ID</th>
                            <th class="px-4 py-3 text-left text-sm font-medium text-gray-300">Chunks</th>
                            <th class="px-4 py-3 text-left text-sm font-medium text-gray-300">Avg Quality</th>
                            <th class="px-4 py-3 text-left text-sm font-medium text-gray-300">Preview</th>
                            <th class="px-4 py-3 text-left text-sm font-medium text-gray-300">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-700">
                        <template x-for="file in files" :key="file.file_id">
                            <tr class="hover:bg-gray-750">
                                <td class="px-4 py-3 font-mono text-sm text-purple-400" x-text="file.file_id"></td>
                                <td class="px-4 py-3 text-sm text-gray-300" x-text="file.chunk_count"></td>
                                <td class="px-4 py-3 text-sm">
                                    <span class="text-yellow-400 font-mono" x-text="file.quality_score?.toFixed(2) || 'N/A'"></span>
                                </td>
                                <td class="px-4 py-3 text-sm text-gray-400 max-w-md truncate" x-text="file.preview"></td>
                                <td class="px-4 py-3">
                                    <button @click="viewFile(file.file_id)"
                                        class="text-purple-400 hover:text-purple-300 text-sm">
                                        View
                                    </button>
                                </td>
                            </tr>
                        </template>
                    </tbody>
                </table>
            </div>

            <!-- Pagination -->
            <div class="mt-4 flex justify-between items-center">
                <span class="text-gray-400 text-sm">
                    Showing <span x-text="fileOffset + 1"></span>-<span x-text="Math.min(fileOffset + files.length, fileTotal)"></span>
                    of <span x-text="fileTotal"></span> files
                </span>
                <div class="flex gap-2">
                    <button @click="prevPage()" :disabled="fileOffset === 0"
                        class="px-4 py-2 bg-gray-700 rounded disabled:opacity-50 hover:bg-gray-600">
                        Previous
                    </button>
                    <button @click="nextPage()" :disabled="fileOffset + 50 >= fileTotal"
                        class="px-4 py-2 bg-gray-700 rounded disabled:opacity-50 hover:bg-gray-600">
                        Next
                    </button>
                </div>
            </div>
        </div>

        <!-- Stats Tab -->
        <div x-show="activeTab === 'stats'" x-cloak>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- LanceDB Stats -->
                <div class="bg-gray-800 rounded-lg p-6 border border-gray-700">
                    <h3 class="text-lg font-semibold text-purple-400 mb-4">LanceDB Statistics</h3>
                    <dl class="space-y-3">
                        <div class="flex justify-between">
                            <dt class="text-gray-400">Table Name</dt>
                            <dd class="text-white font-mono" x-text="stats.lancedb?.table_name || '-'"></dd>
                        </div>
                        <div class="flex justify-between">
                            <dt class="text-gray-400">Total Documents</dt>
                            <dd class="text-white font-mono" x-text="stats.lancedb?.total_documents?.toLocaleString() || '-'"></dd>
                        </div>
                        <div class="flex justify-between">
                            <dt class="text-gray-400">Embedding Dimension</dt>
                            <dd class="text-white font-mono" x-text="stats.lancedb?.embedding_dim || '-'"></dd>
                        </div>
                        <div class="flex justify-between">
                            <dt class="text-gray-400">URI</dt>
                            <dd class="text-white font-mono text-sm truncate max-w-xs" x-text="stats.lancedb?.uri || '-'"></dd>
                        </div>
                    </dl>
                </div>

                <!-- Summary Stats -->
                <div class="bg-gray-800 rounded-lg p-6 border border-gray-700">
                    <h3 class="text-lg font-semibold text-green-400 mb-4">Summary</h3>
                    <dl class="space-y-3">
                        <div class="flex justify-between">
                            <dt class="text-gray-400">Unique Files</dt>
                            <dd class="text-white font-mono" x-text="stats.summary?.unique_files?.toLocaleString() || '-'"></dd>
                        </div>
                        <div class="flex justify-between">
                            <dt class="text-gray-400">Avg Quality Score</dt>
                            <dd class="text-white font-mono" x-text="stats.summary?.avg_quality_score?.toFixed(4) || '-'"></dd>
                        </div>
                        <div class="flex justify-between">
                            <dt class="text-gray-400">Avg Chunks/File</dt>
                            <dd class="text-white font-mono" x-text="stats.summary?.avg_chunks_per_file?.toFixed(1) || '-'"></dd>
                        </div>
                    </dl>
                </div>
            </div>
        </div>

        <!-- File Detail Modal -->
        <div x-show="showFileModal" x-cloak
            class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
            @click.self="showFileModal = false">
            <div class="bg-gray-800 rounded-lg max-w-4xl w-full max-h-[80vh] overflow-hidden">
                <div class="p-4 border-b border-gray-700 flex justify-between items-center">
                    <h3 class="text-lg font-semibold text-purple-400">
                        File: <span x-text="selectedFile"></span>
                    </h3>
                    <button @click="showFileModal = false" class="text-gray-400 hover:text-white">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>
                <div class="p-4 overflow-y-auto max-h-[60vh]">
                    <div class="space-y-4">
                        <template x-for="chunk in fileChunks" :key="chunk.id">
                            <div class="bg-gray-700 rounded p-3">
                                <div class="flex justify-between mb-2 text-sm">
                                    <span class="text-gray-400">Chunk #<span x-text="chunk.chunk_index"></span></span>
                                    <span class="text-yellow-400">Quality: <span x-text="chunk.quality_score?.toFixed(2) || 'N/A'"></span></span>
                                </div>
                                <p class="text-gray-200 text-sm" x-text="chunk.text"></p>
                            </div>
                        </template>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function app() {
            return {
                activeTab: 'search',
                searchQuery: '',
                topK: '10',
                searching: false,
                searched: false,
                searchResults: [],
                files: [],
                fileOffset: 0,
                fileTotal: 0,
                stats: {},
                showFileModal: false,
                selectedFile: '',
                fileChunks: [],

                async init() {
                    await this.loadStats();
                },

                async loadStats() {
                    try {
                        const response = await fetch('/api/stats');
                        this.stats = await response.json();
                    } catch (e) {
                        console.error('Failed to load stats:', e);
                    }
                },

                async loadFiles() {
                    try {
                        const response = await fetch(`/api/files?limit=50&offset=${this.fileOffset}`);
                        const data = await response.json();
                        this.files = data.files;
                        this.fileTotal = data.total;
                    } catch (e) {
                        console.error('Failed to load files:', e);
                    }
                },

                async performSearch() {
                    if (!this.searchQuery.trim()) return;

                    this.searching = true;
                    this.searched = true;
                    try {
                        const response = await fetch('/api/search', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                query: this.searchQuery,
                                top_k: parseInt(this.topK)
                            })
                        });
                        const data = await response.json();
                        this.searchResults = data.results;
                    } catch (e) {
                        console.error('Search failed:', e);
                    } finally {
                        this.searching = false;
                    }
                },

                async viewFile(fileId) {
                    this.selectedFile = fileId;
                    this.showFileModal = true;
                    try {
                        const response = await fetch(`/api/files/${fileId}`);
                        this.fileChunks = await response.json();
                    } catch (e) {
                        console.error('Failed to load file chunks:', e);
                    }
                },

                prevPage() {
                    this.fileOffset = Math.max(0, this.fileOffset - 50);
                    this.loadFiles();
                },

                nextPage() {
                    this.fileOffset += 50;
                    this.loadFiles();
                }
            };
        }
    </script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
async def web_ui() -> HTMLResponse:
    """Serve the web UI for browsing the vector database."""
    return HTMLResponse(content=WEB_UI_HTML)


@router.get("/ui", response_class=HTMLResponse)
async def web_ui_alias() -> HTMLResponse:
    """Alias for web UI."""
    return HTMLResponse(content=WEB_UI_HTML)
