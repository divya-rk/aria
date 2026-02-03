"""Tests for API routes."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_lancedb():
    """Mock LanceDB store."""
    with patch("aria.api.routes.search.get_search") as mock_search, \
         patch("aria.api.routes.files.get_lancedb") as mock_files, \
         patch("aria.api.routes.stats.get_lancedb") as mock_stats:

        # Create mock search service
        search_mock = MagicMock()
        search_mock.search.return_value = [
            {
                "id": "test-001_chunk_0",
                "file_id": "test-001",
                "text": "Sample result text",
                "score": 0.95,
                "quality_score": 0.85,
                "chunk_index": 0,
            }
        ]
        mock_search.return_value = search_mock

        # Create mock lancedb for files
        import pandas as pd
        lancedb_mock = MagicMock()
        lancedb_mock._table.to_pandas.return_value = pd.DataFrame({
            "file_id": ["test-001", "test-001", "test-002"],
            "chunk_index": [0, 1, 0],
            "quality_score": [0.85, 0.82, 0.90],
            "text": ["chunk 1", "chunk 2", "chunk 3"],
        })
        lancedb_mock.get_by_file_id.return_value = [
            {"id": "test-001_chunk_0", "file_id": "test-001", "chunk_index": 0, "text": "chunk 1"},
            {"id": "test-001_chunk_1", "file_id": "test-001", "chunk_index": 1, "text": "chunk 2"},
        ]
        lancedb_mock.get_stats.return_value = {
            "table_name": "embeddings",
            "total_documents": 100,
            "uri": "/tmp/lancedb",
            "embedding_dim": 384,
        }
        mock_files.return_value = lancedb_mock
        mock_stats.return_value = lancedb_mock

        yield {
            "search": search_mock,
            "lancedb": lancedb_mock,
        }


@pytest.fixture
def client(mock_lancedb) -> TestClient:
    """Create test client with mocked dependencies."""
    from aria.api.app import create_app
    app = create_app()
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, client: TestClient) -> None:
        """Test health check returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestSearchEndpoints:
    """Tests for search endpoints."""

    def test_search_post(self, client: TestClient, mock_lancedb) -> None:
        """Test POST search endpoint."""
        response = client.post(
            "/api/search",
            json={"query": "machine learning", "top_k": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "query" in data
        assert data["query"] == "machine learning"

    def test_search_get(self, client: TestClient, mock_lancedb) -> None:
        """Test GET search endpoint."""
        response = client.get("/api/search?q=machine+learning&top_k=5")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_search_empty_query_rejected(self, client: TestClient) -> None:
        """Test that empty query is rejected."""
        response = client.post("/api/search", json={"query": "", "top_k": 10})
        assert response.status_code == 422  # Validation error

    def test_search_top_k_limits(self, client: TestClient) -> None:
        """Test top_k parameter limits."""
        # Too high
        response = client.post("/api/search", json={"query": "test", "top_k": 200})
        assert response.status_code == 422

        # Too low
        response = client.post("/api/search", json={"query": "test", "top_k": 0})
        assert response.status_code == 422


class TestFilesEndpoints:
    """Tests for files endpoints."""

    def test_list_files(self, client: TestClient, mock_lancedb) -> None:
        """Test listing files."""
        response = client.get("/api/files")
        assert response.status_code == 200
        data = response.json()
        assert "files" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_list_files_pagination(self, client: TestClient, mock_lancedb) -> None:
        """Test files pagination."""
        response = client.get("/api/files?limit=10&offset=5")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 5

    def test_get_file_chunks(self, client: TestClient, mock_lancedb) -> None:
        """Test getting chunks for a file."""
        response = client.get("/api/files/test-001")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestStatsEndpoints:
    """Tests for stats endpoints."""

    def test_get_stats(self, client: TestClient, mock_lancedb) -> None:
        """Test getting statistics."""
        with patch("aria.api.routes.stats.get_validator") as mock_validator:
            mock_validator.return_value.get_pipeline_stats.return_value = None

            response = client.get("/api/stats")
            assert response.status_code == 200
            data = response.json()
            assert "lancedb" in data
            assert "summary" in data


class TestWebUI:
    """Tests for web UI endpoint."""

    def test_web_ui_returns_html(self, client: TestClient) -> None:
        """Test that web UI returns HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Aria Vector Database" in response.text

    def test_web_ui_alias(self, client: TestClient) -> None:
        """Test /ui alias for web UI."""
        response = client.get("/ui")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
