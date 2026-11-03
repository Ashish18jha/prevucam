from app.services.pipeline import SurveillancePipeline, get_pipeline


def pipeline_dep() -> SurveillancePipeline:
    return get_pipeline()


def media_url(rel: str | None) -> str | None:
    return f"/media/{rel}" if rel else None
