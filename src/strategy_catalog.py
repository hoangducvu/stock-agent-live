"""Shared strategy IDs used by settings and the supervised engine."""
CATALOG = [
    dict(id='trend_swing', name='Swing Trend Following', side='long', session='swing'),
    dict(id='ema_vwap', name='EMA + VWAP Momentum', side='long', session='intraday'),
    dict(id='orb', name='Opening Range Breakout', side='long', session='intraday'),
    dict(id='rsi', name='RSI Bounce', side='long', session='swing'),
    dict(id='ema_pullback', name='EMA Trend Pullback', side='long', session='intraday'),
    dict(id='donchian', name='20-Bar Channel Breakout', side='long', session='intraday'),
    dict(id='ema_vwap_short', name='EMA + VWAP Breakdown', side='short', session='intraday'),
    dict(id='rsi_fade', name='RSI Fade', side='short', session='swing'),
    dict(id='news', name='News Catalyst Momentum', side='long', session='intraday'),
]
IDS = [s['id'] for s in CATALOG]
NAMES = dict(trend_swing='TREND_SWING', ema_vwap='EMA_VWAP', orb='ORB', rsi='RSI_BOUNCE',
             ema_pullback='EMA_PULLBACK', donchian='DONCHIAN',
             ema_vwap_short='EMA_VWAP_SHORT', rsi_fade='RSI_FADE', news='NEWS_MOMENTUM')
SHORT_IDS = {'ema_vwap_short', 'rsi_fade'}
