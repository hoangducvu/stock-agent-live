"""Supported Anthropic model choices and standard per-million-token budget rates.
Rates verified against official model pages 2026-10-26. No automatic upgrades.
"""
DEFAULT_MODEL='claude-haiku-4-5-20251001'
MODELS={
    DEFAULT_MODEL:dict(name='Claude Haiku 4.5',input_per_million=1.0,output_per_million=5.0),
    'claude-sonnet-4-6':dict(name='Claude Sonnet 4.6',input_per_million=3.0,output_per_million=15.0),
    'claude-opus-4-6':dict(name='Claude Opus 4.6',input_per_million=5.0,output_per_million=25.0),
    'claude-sonnet-5-5':dict(name='Claude Sonnet 5.5',input_per_million=2.0,output_per_million=10.0),
}
def model_info(model):
    if model not in MODELS:raise ValueError('Select a supported AI model')
    return MODELS[model]
def model_choices():return [dict(id=key,**value) for key,value in MODELS.items()]
