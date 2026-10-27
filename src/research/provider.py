"""Official-SDK adapter: bounded hosted web search, no broker or executable tools."""
from dataclasses import dataclass, field
from typing import Protocol
@dataclass
class ModelReply:
    text: str
    input_tokens: int
    output_tokens: int
    searches: int = 0
    sources: list[str] = field(default_factory=list)
    complete: bool = True
    stop_reason: str | None = None
class Provider(Protocol):
    def complete(self,system:str,payload:str,max_output:int)->ModelReply:...
    def research_company(self,system:str,payload:str,max_output:int)->ModelReply:...
    def shortlist(self,system:str,payload:str,max_output:int,schema:dict)->ModelReply:...
class AnthropicProvider:
    def __init__(self,config,api_key=None,managed=False):self.config=config;self.api_key=api_key;self.managed=managed
    def complete(self,system,payload,max_output):
        return self._request(system,payload,max_output)
    def research_company(self,system,payload,max_output):
        return self._request(system,payload,max_output,search=True)
    def shortlist(self,system,payload,max_output,schema):
        return self._request(system,payload,max_output,schema=schema)
    def _request(self,system,payload,max_output,search=False,schema=None):
        import anthropic
        key=self.api_key
        if self.managed:
            from pathlib import Path
            from backend.settings_store import SettingsStore
            saved=SettingsStore(Path(__file__).resolve().parents[1]/'data').read()
            if not saved.get('ai_enabled') or not saved.get('ai_api_key'):raise RuntimeError('AI is disabled or its key was removed')
            if saved.get('ai_model',self.config.model)!=self.config.model:raise RuntimeError('AI model changed; discard old request configuration')
            key=saved['ai_api_key']
        # Explicit retries=0: ambiguous calls remain charged/reserved and never fan out.
        client=anthropic.Anthropic(api_key=key,timeout=max(60,self.config.timeout) if search else self.config.timeout,max_retries=0)
        options={"tools":[{"type":"web_search_20250305","name":"web_search","max_uses":self.config.searches_per_company}]} if search else {}
        if schema is not None:options['output_config']={'format':{'type':'json_schema','schema':schema}}
        response=client.messages.create(model=self.config.model,max_tokens=max_output,
            system=system,messages=[{'role':'user','content':payload}],**options)
        texts=[part.text for part in response.content if part.type=='text']
        # Search turns may include a preamble before tool use; only final text is JSON.
        text=texts[-1] if search and texts else ''.join(texts)
        sources=[]
        for part in response.content:
            if part.type=='web_search_tool_result' and isinstance(part.content,list):
                sources.extend(r.url for r in part.content if getattr(r,'type',None)=='web_search_result')
            for citation in getattr(part,'citations',None) or []:
                if getattr(citation,'type',None)=='web_search_result_location':sources.append(citation.url)
        usage=response.usage
        tool_usage=getattr(usage,'server_tool_use',None)
        searches=getattr(tool_usage,'web_search_requests',None) if tool_usage is not None else None
        if search and searches is None:searches=self.config.searches_per_company # conservative if usage missing
        # Include cache-write/read usage at full input price when present; this
        # overestimates cache reads rather than silently undercharging the budget.
        input_tokens=int(usage.input_tokens)+int(getattr(usage,'cache_creation_input_tokens',0) or 0)+int(getattr(usage,'cache_read_input_tokens',0) or 0)
        return ModelReply(text,input_tokens,int(usage.output_tokens),int(searches or 0),list(dict.fromkeys(sources)),response.stop_reason=='end_turn',response.stop_reason)

def build_provider(config,api_key=None,managed=False):
    if config.provider!='anthropic':raise ValueError('AI_PROVIDER needs a configured adapter; only anthropic is bundled')
    return AnthropicProvider(config,api_key,managed)
