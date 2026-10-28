"""
Callback handlers for LangChain observability and streaming.

This module provides callback handlers for:
- Real-time streaming updates
- Logging and debugging
- Performance monitoring
- Error tracking
- WebSocket integration
"""

import logging
import time
from typing import Any, Dict, List, Optional
from datetime import datetime

from langchain_core.callbacks import BaseCallbackHandler, AsyncCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


# ============================================================================
# STREAMING CALLBACK HANDLER
# ============================================================================

class StreamingCallbackHandler(AsyncCallbackHandler):
    """
    Async callback handler for streaming LLM responses.
    Captures tokens as they're generated for real-time updates.
    """
    
    def __init__(self):
        self.tokens: List[str] = []
        self.current_completion = ""
    
    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """Called when LLM generates a new token."""
        self.tokens.append(token)
        self.current_completion += token
    
    async def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """Called when LLM starts running."""
        self.tokens = []
        self.current_completion = ""
        logger.debug(f"LLM started with {len(prompts)} prompt(s)")
    
    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Called when LLM ends running."""
        logger.debug(f"LLM completed. Generated {len(self.tokens)} tokens")
    
    async def on_llm_error(
        self, error: Exception | KeyboardInterrupt, **kwargs: Any
    ) -> None:
        """Called when LLM errors."""
        logger.error(f"LLM error: {error}")
    
    def get_completion(self) -> str:
        """Get the current completion."""
        return self.current_completion
    
    def reset(self) -> None:
        """Reset the handler state."""
        self.tokens = []
        self.current_completion = ""


# ============================================================================
# LOGGING CALLBACK HANDLER
# ============================================================================

class LoggingCallbackHandler(BaseCallbackHandler):
    """
    Callback handler for detailed logging of LangChain operations.
    Useful for debugging and monitoring.
    """
    
    def __init__(self, log_level: int = logging.INFO):
        self.log_level = log_level
        self.start_times: Dict[str, float] = {}
    
    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """Log when LLM starts."""
        run_id = kwargs.get("run_id", "unknown")
        self.start_times[str(run_id)] = time.time()
        logger.log(
            self.log_level,
            f"[LLM START] Run ID: {run_id}, Prompts: {len(prompts)}"
        )
    
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Log when LLM ends."""
        run_id = kwargs.get("run_id", "unknown")
        duration = time.time() - self.start_times.get(str(run_id), time.time())
        
        total_tokens = sum(
            len(gen.text.split())
            for generations in response.generations
            for gen in generations
        )
        
        logger.log(
            self.log_level,
            f"[LLM END] Run ID: {run_id}, Duration: {duration:.2f}s, "
            f"Tokens: ~{total_tokens}"
        )
    
    def on_llm_error(
        self, error: Exception | KeyboardInterrupt, **kwargs: Any
    ) -> None:
        """Log when LLM errors."""
        run_id = kwargs.get("run_id", "unknown")
        logger.error(f"[LLM ERROR] Run ID: {run_id}, Error: {error}")
    
    def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any
    ) -> None:
        """Log when chain starts."""
        run_id = kwargs.get("run_id", "unknown")
        self.start_times[str(run_id)] = time.time()
        logger.log(
            self.log_level,
            f"[CHAIN START] Run ID: {run_id}, Inputs: {list(inputs.keys())}"
        )
    
    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> None:
        """Log when chain ends."""
        run_id = kwargs.get("run_id", "unknown")
        duration = time.time() - self.start_times.get(str(run_id), time.time())
        logger.log(
            self.log_level,
            f"[CHAIN END] Run ID: {run_id}, Duration: {duration:.2f}s, "
            f"Outputs: {list(outputs.keys())}"
        )
    
    def on_chain_error(
        self, error: Exception | KeyboardInterrupt, **kwargs: Any
    ) -> None:
        """Log when chain errors."""
        run_id = kwargs.get("run_id", "unknown")
        logger.error(f"[CHAIN ERROR] Run ID: {run_id}, Error: {error}")
    
    def on_retriever_start(
        self, serialized: Dict[str, Any], query: str, **kwargs: Any
    ) -> None:
        """Log when retriever starts."""
        run_id = kwargs.get("run_id", "unknown")
        logger.log(
            self.log_level,
            f"[RETRIEVER START] Run ID: {run_id}, Query: {query[:50]}..."
        )
    
    def on_retriever_end(self, documents: List, **kwargs: Any) -> None:
        """Log when retriever ends."""
        run_id = kwargs.get("run_id", "unknown")
        logger.log(
            self.log_level,
            f"[RETRIEVER END] Run ID: {run_id}, Documents: {len(documents)}"
        )


# ============================================================================
# PERFORMANCE MONITORING CALLBACK
# ============================================================================

class PerformanceCallbackHandler(BaseCallbackHandler):
    """
    Callback handler for performance monitoring and metrics collection.
    Tracks timing, token counts, and operation statistics.
    """
    
    def __init__(self):
        self.metrics: Dict[str, Any] = {
            "llm_calls": 0,
            "chain_calls": 0,
            "retriever_calls": 0,
            "total_duration": 0.0,
            "llm_duration": 0.0,
            "retriever_duration": 0.0,
            "tokens_generated": 0,
            "errors": 0
        }
        self.start_times: Dict[str, float] = {}
    
    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """Track LLM start."""
        run_id = kwargs.get("run_id", "unknown")
        self.start_times[f"llm_{run_id}"] = time.time()
        self.metrics["llm_calls"] += 1
    
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Track LLM end and calculate duration."""
        run_id = kwargs.get("run_id", "unknown")
        start_time = self.start_times.get(f"llm_{run_id}", time.time())
        duration = time.time() - start_time
        self.metrics["llm_duration"] += duration
        
        # Estimate tokens
        total_tokens = sum(
            len(gen.text.split())
            for generations in response.generations
            for gen in generations
        )
        self.metrics["tokens_generated"] += total_tokens
    
    def on_llm_error(
        self, error: Exception | KeyboardInterrupt, **kwargs: Any
    ) -> None:
        """Track LLM errors."""
        self.metrics["errors"] += 1
    
    def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any
    ) -> None:
        """Track chain start."""
        run_id = kwargs.get("run_id", "unknown")
        self.start_times[f"chain_{run_id}"] = time.time()
        self.metrics["chain_calls"] += 1
    
    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> None:
        """Track chain end and calculate duration."""
        run_id = kwargs.get("run_id", "unknown")
        start_time = self.start_times.get(f"chain_{run_id}", time.time())
        duration = time.time() - start_time
        self.metrics["total_duration"] += duration
    
    def on_chain_error(
        self, error: Exception | KeyboardInterrupt, **kwargs: Any
    ) -> None:
        """Track chain errors."""
        self.metrics["errors"] += 1
    
    def on_retriever_start(
        self, serialized: Dict[str, Any], query: str, **kwargs: Any
    ) -> None:
        """Track retriever start."""
        run_id = kwargs.get("run_id", "unknown")
        self.start_times[f"retriever_{run_id}"] = time.time()
        self.metrics["retriever_calls"] += 1
    
    def on_retriever_end(self, documents: List, **kwargs: Any) -> None:
        """Track retriever end and calculate duration."""
        run_id = kwargs.get("run_id", "unknown")
        start_time = self.start_times.get(f"retriever_{run_id}", time.time())
        duration = time.time() - start_time
        self.metrics["retriever_duration"] += duration
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get collected metrics."""
        return self.metrics.copy()
    
    def reset(self) -> None:
        """Reset all metrics."""
        self.metrics = {
            "llm_calls": 0,
            "chain_calls": 0,
            "retriever_calls": 0,
            "total_duration": 0.0,
            "llm_duration": 0.0,
            "retriever_duration": 0.0,
            "tokens_generated": 0,
            "errors": 0
        }
        self.start_times = {}


# ============================================================================
# WEBSOCKET CALLBACK HANDLER
# ============================================================================

class WebSocketCallbackHandler(AsyncCallbackHandler):
    """
    Async callback handler for WebSocket streaming.
    Sends real-time updates to connected WebSocket clients.
    """
    
    def __init__(self, websocket_send_func=None):
        """
        Initialize WebSocket callback handler.
        
        Args:
            websocket_send_func: Async function to send messages to WebSocket.
                                Should accept a dict with message data.
        """
        self.websocket_send = websocket_send_func
        self.tokens: List[str] = []
    
    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """Send new token to WebSocket."""
        if self.websocket_send:
            await self.websocket_send({
                "type": "token",
                "token": token,
                "timestamp": datetime.now().isoformat()
            })
        self.tokens.append(token)
    
    async def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """Notify WebSocket that generation started."""
        if self.websocket_send:
            await self.websocket_send({
                "type": "start",
                "message": "Generating response...",
                "timestamp": datetime.now().isoformat()
            })
        self.tokens = []
    
    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Notify WebSocket that generation completed."""
        if self.websocket_send:
            await self.websocket_send({
                "type": "end",
                "message": "Response complete",
                "token_count": len(self.tokens),
                "timestamp": datetime.now().isoformat()
            })
    
    async def on_llm_error(
        self, error: Exception | KeyboardInterrupt, **kwargs: Any
    ) -> None:
        """Send error to WebSocket."""
        if self.websocket_send:
            await self.websocket_send({
                "type": "error",
                "error": str(error),
                "timestamp": datetime.now().isoformat()
            })
    
    async def on_retriever_start(
        self, serialized: Dict[str, Any], query: str, **kwargs: Any
    ) -> None:
        """Notify WebSocket that retrieval started."""
        if self.websocket_send:
            await self.websocket_send({
                "type": "retrieval_start",
                "message": "Searching documents...",
                "query": query[:50] + "..." if len(query) > 50 else query,
                "timestamp": datetime.now().isoformat()
            })
    
    async def on_retriever_end(self, documents: List, **kwargs: Any) -> None:
        """Notify WebSocket that retrieval completed."""
        if self.websocket_send:
            await self.websocket_send({
                "type": "retrieval_end",
                "message": f"Found {len(documents)} relevant document(s)",
                "document_count": len(documents),
                "timestamp": datetime.now().isoformat()
            })


# ============================================================================
# DEBUG CALLBACK HANDLER
# ============================================================================

class DebugCallbackHandler(BaseCallbackHandler):
    """
    Verbose debug callback handler.
    Logs everything for debugging purposes.
    """
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
    
    def _log(self, event: str, data: Any) -> None:
        """Log debug information."""
        if self.verbose:
            logger.debug(f"[DEBUG] {event}: {data}")
    
    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """Debug LLM start."""
        self._log("LLM_START", {
            "prompts": [p[:100] + "..." if len(p) > 100 else p for p in prompts],
            "model": serialized.get("id", ["unknown"])[-1] if "id" in serialized else "unknown"
        })
    
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Debug LLM end."""
        self._log("LLM_END", {
            "generations": len(response.generations),
            "llm_output": response.llm_output
        })
    
    def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any
    ) -> None:
        """Debug chain start."""
        self._log("CHAIN_START", {
            "chain": serialized.get("id", ["unknown"])[-1] if "id" in serialized else "unknown",
            "inputs": {k: str(v)[:100] for k, v in inputs.items()}
        })
    
    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> None:
        """Debug chain end."""
        self._log("CHAIN_END", {
            "outputs": {k: str(v)[:100] for k, v in outputs.items()}
        })
    
    def on_retriever_start(
        self, serialized: Dict[str, Any], query: str, **kwargs: Any
    ) -> None:
        """Debug retriever start."""
        self._log("RETRIEVER_START", {"query": query})
    
    def on_retriever_end(self, documents: List, **kwargs: Any) -> None:
        """Debug retriever end."""
        self._log("RETRIEVER_END", {
            "document_count": len(documents),
            "documents": [
                {
                    "content": doc.page_content[:100] + "..." if hasattr(doc, "page_content") else str(doc)[:100],
                    "metadata": doc.metadata if hasattr(doc, "metadata") else {}
                }
                for doc in documents[:3]  # Only first 3 for brevity
            ]
        })


# ============================================================================
# CALLBACK MANAGER FACTORY
# ============================================================================

def create_callback_manager(
    enable_logging: bool = True,
    enable_performance: bool = True,
    enable_debug: bool = False,
    enable_websocket: bool = False,
    websocket_send_func=None,
    log_level: int = logging.INFO
) -> List[BaseCallbackHandler]:
    """
    Factory function to create a list of callback handlers.
    
    Args:
        enable_logging: Enable logging callback
        enable_performance: Enable performance monitoring callback
        enable_debug: Enable debug callback
        enable_websocket: Enable WebSocket callback
        websocket_send_func: Function for WebSocket sends (required if enable_websocket=True)
        log_level: Logging level for LoggingCallbackHandler
    
    Returns:
        List of callback handlers
    """
    callbacks = []
    
    if enable_logging:
        callbacks.append(LoggingCallbackHandler(log_level=log_level))
    
    if enable_performance:
        callbacks.append(PerformanceCallbackHandler())
    
    if enable_debug:
        callbacks.append(DebugCallbackHandler(verbose=True))
    
    if enable_websocket and websocket_send_func:
        callbacks.append(WebSocketCallbackHandler(websocket_send_func))
    
    return callbacks


logger.info("callbacks.py loaded with LangChain callback handlers")
