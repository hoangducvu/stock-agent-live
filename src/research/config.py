"""Environment-only AI policy. No credentials are included in prompts or status."""
from dataclasses import dataclass
import math
import os

def flag(name, default=False):
    value=os.getenv(name,str(default)).lower()
    if value not in {'true','false'}:raise ValueError('Invalid boolean '+name)
    return value=='true'
def number(name,default,low,high):
    value=float(os.getenv(name,str(default)))
    if not math.isfinite(value) or not low<=value<=high: raise ValueError('Invalid '+name)
    return value

@dataclass(frozen=True)
class ResearchConfig:
    enabled: bool = False
    premarket: bool = True
    postmarket: bool = True
    validation: bool = True
    provider: str = 'anthropic'
    model: str = 'claude-haiku-4-5-20251001'
    allocation_mode: str = 'percentage'
    buying_power_reserve_pct: float = 5.0
    max_positions: int = 3
    prototype: bool = False
    batch_review: bool = False
    search_reserve_tokens: int = 20000
    company_cache_days: int = 7
    searches_per_company: int = 2
    calls: int = 20
    dollars: float = 1.0
    tokens: int = 12000
    candidates: int = 10
    cooldown_minutes: int = 30
    input_per_million: float = 1.0
    output_per_million: float = 5.0
    min_price: float = 5.0
    min_dollar_volume: float = 20000000.0
    rsi_min: float = 35.0
    rsi_max: float = 75.0
    min_relative_strength: float = 0.0
    min_hold: int = 10
    max_hold: int = 90
    max_spread_bps: float = 30.0
    max_slippage_bps: float = 30.0
    max_exposure: float = .60
    max_sector: float = .30
    max_atr_pct: float = .08
    require_fundamentals: bool = True
    require_earnings: bool = True
    earnings_buffer_days: int = 3
    allow_additional: bool = False
    opening_minutes: int = 30
    premarket_time: str = '08:30'
    postmarket_time: str = '16:15'
    entry_start: str = '10:00'
    timeout: int = 25

    @classmethod
    def from_env(cls, settings=None):
        if os.getenv('MARKET_TIMEZONE','America/New_York')!='America/New_York':
            raise ValueError('US exchange scheduling requires America/New_York')
        enabled=bool(settings.get('ai_enabled') and settings.get('ai_api_key','').strip()) if settings is not None else flag('AI_ENABLED')
        c=cls(enabled=enabled,premarket=flag('PREMARKET_AI_ENABLED',True),postmarket=flag('POSTMARKET_AI_ENABLED',True),
              validation=flag('AI_TRADE_VALIDATION_ENABLED',True),provider=os.getenv('AI_PROVIDER','anthropic'),
              model=os.getenv('AI_MODEL',cls.model),calls=int(number('MAX_AI_CALLS_PER_DAY',20,0,1000)),
              dollars=number('MAX_AI_COST_USD_PER_DAY',1,0,1000),tokens=int(number('MAX_AI_TOKENS_PER_REQUEST',12000,512,32000)),
              candidates=int(number('MAX_AI_CANDIDATES_PER_REQUEST',10,1,15)),
              cooldown_minutes=int(number('AI_SIGNAL_COOLDOWN_MINUTES',30,1,1440)),
              input_per_million=number('AI_INPUT_USD_PER_MILLION',1,.001,1000),output_per_million=number('AI_OUTPUT_USD_PER_MILLION',5,.001,1000),
              min_price=number('AI_MIN_PRICE',5,1,10000),min_dollar_volume=number('AI_MIN_DOLLAR_VOLUME',20000000,0,1e12),
              rsi_min=number('AI_RSI_MIN',35,0,100),rsi_max=number('AI_RSI_MAX',75,0,100),min_relative_strength=number('AI_MIN_RELATIVE_STRENGTH',0,-1,10),
              earnings_buffer_days=int(number('AI_EARNINGS_BUFFER_DAYS',3,0,90)),
              min_hold=int(number('TARGET_MIN_HOLD_DAYS',10,1,90)),max_hold=int(number('TARGET_MAX_HOLD_DAYS',90,1,365)),
              max_spread_bps=number('AI_MAX_SPREAD_BPS',30,1,1000),max_slippage_bps=number('AI_MAX_SLIPPAGE_BPS',30,1,1000),
              max_exposure=number('AI_MAX_PORTFOLIO_EXPOSURE',.60,.01,1),max_sector=number('AI_MAX_SECTOR_EXPOSURE',.30,.01,1),
              max_atr_pct=number('AI_MAX_ATR_PCT',.08,.001,1),require_fundamentals=flag('AI_REQUIRE_FUNDAMENTALS',True),
              require_earnings=flag('AI_REQUIRE_EARNINGS',True),allow_additional=flag('AI_ALLOW_ADDITIONAL_CANDIDATES'),
              opening_minutes=int(number('AI_OPENING_RESTRICTION_MINUTES',30,0,180)),premarket_time=os.getenv('AI_PREMARKET_TIME','08:30'),
              postmarket_time=os.getenv('AI_POSTMARKET_TIME','16:15'),entry_start=os.getenv('ENTRY_EVALUATION_START','10:00'),
              timeout=int(number('AI_TIMEOUT_SECONDS',25,1,120)))
        if settings is not None:
            from dataclasses import replace
            from .models import model_info,DEFAULT_MODEL
            selected=settings.get('ai_model',DEFAULT_MODEL);rates=model_info(selected)
            c=replace(c,model=selected,input_per_million=rates['input_per_million'],output_per_million=rates['output_per_million'])
            if settings.get('allocation_mode')=='fill_slots':
                exposure=float(settings['max_gross_exposure_pct'])/100
                c=replace(c,allocation_mode='fill_slots',max_positions=int(settings['max_positions']),buying_power_reserve_pct=float(settings['buying_power_reserve_pct']),max_exposure=exposure,max_sector=exposure*.30)
        # Managed dashboard defaults to the explicitly requested prototype budget.
        # Standalone/test configurations preserve their existing comparison modes.
        from dataclasses import replace
        prototype=flag('AI_PROTOTYPE_MODE', settings is not None)
        if prototype:
            c=replace(c,prototype=True,batch_review=flag('AI_BATCH_REVIEW_ENABLED', settings is not None),validation=False,candidates=3,
                      calls=min(c.calls,8),dollars=min(c.dollars,.20),
                      search_reserve_tokens=20000,company_cache_days=7,searches_per_company=2)
        from datetime import time
        for t in (c.premarket_time,c.postmarket_time,c.entry_start):time.fromisoformat(t)
        if c.rsi_min>c.rsi_max:raise ValueError('Invalid RSI range')
        if c.min_hold>c.max_hold:raise ValueError('Minimum hold exceeds maximum hold')
        return c


def runtime_policy():
    """Dashboard-managed engines reload opt-in/key presence without restarting exits."""
    if os.getenv('NEXLARA_MANAGED_AI')=='true':
        from pathlib import Path
        from backend.settings_store import SettingsStore
        settings=SettingsStore(Path(__file__).resolve().parents[1]/'data').read()
        return ResearchConfig.from_env(settings=settings)
    return ResearchConfig.from_env()
