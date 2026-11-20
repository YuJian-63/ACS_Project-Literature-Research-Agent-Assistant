from app.db.models import Paper


def resource_error(resource: Paper) -> dict | None:
    if resource.error_code is None:
        return None
    return {
        "code": resource.error_code,
        "message": resource.error_message,
        "details": resource.error_details or {},
    }


def paper_view(paper: Paper) -> dict:
    fields = (
        "id", "title", "original_filename", "content_type", "size_bytes", "sha256",
        "status", "page_count", "parser_version", "created_at", "updated_at",
    )
    from app.sources.arxiv import ArxivPaper

    source = paper.source
    provenance = ArxivPaper(
        **source.source_metadata, provider=source.provider, external_id=source.external_id,
    ).source_view() if source is not None else None
    return {**{name: getattr(paper, name) for name in fields}, "error": resource_error(paper), "source": provenance}
