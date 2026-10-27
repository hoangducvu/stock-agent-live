"""Strict model outputs; text is data and can never invoke tools or change policy."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
class Recommendation(BaseModel):
    model_config=ConfigDict(extra='forbid', strict=True)
    ticker: str=Field(pattern=r'^[A-Z][A-Z0-9.\-]{0,9}$')
    action: Literal['BUY','HOLD','AVOID','REVIEW','CONTINUE HOLDING','REVIEW FOR EXIT','TIGHTEN RISK CONTROLS FOR REVIEW','REMOVE FROM WATCHLIST','ADD TO WATCHLIST','NO ACTION']
    analysis_timestamp: datetime
    data_timestamp: datetime
    summary: str=Field(max_length=700)
    bullish_factors: list[str]=Field(max_length=8)
    bearish_factors: list[str]=Field(max_length=8)
    relevant_catalysts: list[str]=Field(max_length=8)
    identified_risks: list[str]=Field(max_length=8)
    thesis_invalidation_conditions: list[str]=Field(max_length=8)
    relevant_source_references: list[str]=Field(max_length=20)
    model_name: str=Field(max_length=120)
    analysis_version: Literal['1']
class Report(BaseModel):
    model_config=ConfigDict(extra='forbid', strict=True)
    recommendations: list[Recommendation]=Field(max_length=15)
    summary: str=Field(max_length=1500)

def validate_report(raw,task,snapshots,model,now):
    report=Report.model_validate_json(raw)
    seen=set()
    allowed={'BUY','HOLD','AVOID','REVIEW'} if task!='postmarket' else {'CONTINUE HOLDING','REVIEW FOR EXIT','TIGHTEN RISK CONTROLS FOR REVIEW','REMOVE FROM WATCHLIST','ADD TO WATCHLIST','NO ACTION'}
    for item in report.recommendations:
        if item.ticker not in snapshots or item.ticker in seen:raise ValueError('Unknown or duplicate ticker')
        seen.add(item.ticker)
        if item.action not in allowed or item.model_name!=model:raise ValueError('Unsupported action/model')
        if item.analysis_timestamp.tzinfo is None or item.data_timestamp.tzinfo is None:raise ValueError('Timezone required')
        if abs((now-item.analysis_timestamp).total_seconds())>300:raise ValueError('Stale analysis')
        snapshot=snapshots[item.ticker]
        if item.data_timestamp.isoformat()!=datetime.fromisoformat(snapshot['data_timestamp']).isoformat():raise ValueError('Snapshot timestamp mismatch')
        if not set(item.relevant_source_references)<=set(snapshot.get('source_references',[])):raise ValueError('Unsupported source')
        if item.action=='BUY' and (not item.thesis_invalidation_conditions or not item.relevant_source_references):raise ValueError('BUY requires evidence and invalidation conditions')
        # Missing critical evidence cannot be overridden by an optimistic model.
        if item.action=='BUY' and snapshot.get('missing_required_evidence'):raise ValueError('BUY contradicts missing evidence')
    return report
