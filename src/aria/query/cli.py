"""CLI interface for Aria."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from aria.common import setup_logging
from aria.config import get_settings


app = typer.Typer(
    name="aria",
    help="Aria - Audio Recognition and Ingestion Architecture CLI",
    add_completion=False,
)
console = Console()


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query text"),
    top_k: int = typer.Option(10, "--top-k", "-k", help="Number of results"),
    min_score: float = typer.Option(0.0, "--min-score", "-s", help="Minimum similarity score"),
    quality: Optional[str] = typer.Option(None, "--quality", "-q", help="Quality tier filter"),
) -> None:
    """Search for similar documents in the vector database."""
    setup_logging()
    settings = get_settings()

    from aria.query.search import VectorSearch

    search_service = VectorSearch(settings)
    results = search_service.search(
        query=query,
        top_k=top_k,
        min_score=min_score,
        filter_quality=quality,
    )

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search Results for: {query[:50]}...")
    table.add_column("Score", style="cyan", width=8)
    table.add_column("File ID", style="magenta", width=20)
    table.add_column("Text Preview", style="white", width=60)
    table.add_column("Quality", style="green", width=8)

    for result in results:
        text_preview = result.get("text", "")[:100] + "..."
        table.add_row(
            f"{result.get('score', 0):.4f}",
            result.get("file_id", "")[:20],
            text_preview,
            f"{result.get('quality_score', 0):.2f}",
        )

    console.print(table)


@app.command()
def validate(
    check: str = typer.Option("all", "--check", "-c", help="Validation type: embeddings, pipeline, all"),
    sample_size: int = typer.Option(1000, "--sample", "-n", help="Sample size for validation"),
) -> None:
    """Validate data quality and pipeline completeness."""
    setup_logging()
    settings = get_settings()

    from aria.query.validate import DataValidator

    validator = DataValidator(settings)

    if check in ("embeddings", "all"):
        console.print("\n[bold]Embedding Validation[/bold]")
        report = validator.validate_embeddings(sample_size)
        _print_validation_report(report)

    if check in ("pipeline", "all"):
        console.print("\n[bold]Pipeline Validation[/bold]")
        report = validator.validate_pipeline_completeness()
        _print_validation_report(report)


def _print_validation_report(report) -> None:
    """Print validation report."""
    status_color = "green" if report.pass_rate > 0.9 else "yellow" if report.pass_rate > 0.7 else "red"

    console.print(f"  Total Checked: {report.total_checked}")
    console.print(f"  Passed: [green]{report.passed}[/green]")
    console.print(f"  Failed: [red]{report.failed}[/red]")
    console.print(f"  Pass Rate: [{status_color}]{report.pass_rate:.1%}[/{status_color}]")

    if report.issues:
        console.print(f"\n  [yellow]Issues ({len(report.issues)}):[/yellow]")
        for issue in report.issues[:5]:
            console.print(f"    - {issue}")


@app.command()
def stats() -> None:
    """Show database and pipeline statistics."""
    setup_logging()
    settings = get_settings()

    from aria.query.validate import DataValidator
    from aria.storage import LanceDBStore

    lancedb = LanceDBStore(settings)
    lancedb.create_table_if_not_exists()
    db_stats = lancedb.get_stats()

    console.print("\n[bold]LanceDB Statistics[/bold]")
    table = Table()
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    for key, value in db_stats.items():
        table.add_row(key, str(value))

    console.print(table)

    try:
        validator = DataValidator(settings)
        pipeline_stats = validator.get_pipeline_stats()

        console.print("\n[bold]Pipeline Statistics[/bold]")
        for stage, counts in pipeline_stats.get("stages", {}).items():
            console.print(f"  {stage}:")
            console.print(f"    Completed: [green]{counts.get('completed', 0)}[/green]")
            console.print(f"    Failed: [red]{counts.get('failed', 0)}[/red]")
            console.print(f"    Processing: [yellow]{counts.get('processing', 0)}[/yellow]")
    except Exception as e:
        console.print(f"\n[yellow]Could not fetch pipeline stats: {e}[/yellow]")


@app.command()
def report() -> None:
    """Generate comprehensive quality report."""
    setup_logging()
    settings = get_settings()

    from aria.query.validate import DataValidator

    console.print("\n[bold]Generating Quality Report...[/bold]\n")

    validator = DataValidator(settings)
    report = validator.generate_quality_report()

    # Overall health
    health_color = "green" if report["overall_health"] == "healthy" else "yellow"
    console.print(f"Overall Health: [{health_color}]{report['overall_health'].upper()}[/{health_color}]\n")

    # Embedding quality
    console.print("[bold]Embedding Quality[/bold]")
    console.print(f"  Pass Rate: {report['embedding_quality']['pass_rate']:.1%}")
    console.print(f"  Issues: {report['embedding_quality']['issues']}")

    # Pipeline completeness
    console.print("\n[bold]Pipeline Completeness[/bold]")
    console.print(f"  Pass Rate: {report['pipeline_completeness']['pass_rate']:.1%}")
    console.print(f"  Total Files: {report['pipeline_completeness']['total_files']}")
    console.print(f"  Incomplete: {report['pipeline_completeness']['incomplete']}")

    # LanceDB health
    console.print("\n[bold]LanceDB Health[/bold]")
    console.print(f"  Total Documents: {report['lancedb_health']['total_documents']}")
    console.print(f"  Issues: {report['lancedb_health']['issues']}")


@app.command()
def browse(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of files to show"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
) -> None:
    """Browse files in the vector database."""
    setup_logging()
    settings = get_settings()

    from aria.storage import LanceDBStore

    lancedb = LanceDBStore(settings)
    lancedb.create_table_if_not_exists()

    # Get file list
    df = lancedb._table.to_pandas()
    file_stats = (
        df.groupby("file_id")
        .agg({
            "chunk_index": "count",
            "quality_score": "mean",
        })
        .reset_index()
        .rename(columns={"chunk_index": "chunk_count"})
    )

    total = len(file_stats)
    files = file_stats.iloc[offset : offset + limit]

    table = Table(title=f"Files in Vector Database ({offset+1}-{offset+len(files)} of {total})")
    table.add_column("File ID", style="magenta", width=30)
    table.add_column("Chunks", style="cyan", justify="right", width=10)
    table.add_column("Avg Quality", style="yellow", justify="right", width=12)

    for _, row in files.iterrows():
        table.add_row(
            str(row["file_id"])[:30],
            str(row["chunk_count"]),
            f"{row['quality_score']:.3f}" if row["quality_score"] else "N/A",
        )

    console.print(table)
    console.print(f"\n[dim]Use --offset {offset + limit} to see more[/dim]")


@app.command()
def show(
    file_id: str = typer.Argument(..., help="File ID to show"),
) -> None:
    """Show all chunks for a specific file."""
    setup_logging()
    settings = get_settings()

    from aria.storage import LanceDBStore

    lancedb = LanceDBStore(settings)
    lancedb.create_table_if_not_exists()

    chunks = lancedb.get_by_file_id(file_id)

    if not chunks:
        console.print(f"[red]No chunks found for file: {file_id}[/red]")
        return

    console.print(f"\n[bold]File: {file_id}[/bold]")
    console.print(f"[dim]Total chunks: {len(chunks)}[/dim]\n")

    for chunk in sorted(chunks, key=lambda x: x.get("chunk_index", 0)):
        console.print(f"[cyan]--- Chunk {chunk.get('chunk_index', '?')} ---[/cyan]")
        console.print(f"[dim]Quality: {chunk.get('quality_score', 'N/A')}[/dim]")
        console.print(chunk.get("text", "")[:500])
        if len(chunk.get("text", "")) > 500:
            console.print("[dim]...(truncated)[/dim]")
        console.print()


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload"),
) -> None:
    """Start the API server with web UI."""
    import uvicorn

    console.print(f"\n[bold]Starting Aria API Server[/bold]")
    console.print(f"  Host: {host}")
    console.print(f"  Port: {port}")
    console.print(f"  Web UI: http://{host}:{port}/")
    console.print(f"  API Docs: http://{host}:{port}/docs\n")

    uvicorn.run(
        "aria.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def version() -> None:
    """Show version information."""
    from aria import __version__

    console.print(f"Aria version: [bold]{__version__}[/bold]")


if __name__ == "__main__":
    app()
