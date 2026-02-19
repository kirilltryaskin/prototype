"""HTTP channel for nanobot — receives messages via POST /message endpoint."""

import asyncio
import uuid
from typing import Optional
from datetime import datetime

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class HTTPChannel(BaseChannel):
    """HTTP channel that receives messages via REST API."""
    
    name = "http"
    
    def __init__(self, config: dict, bus: MessageBus):
        super().__init__(config, bus)
        self.pending_responses = {}  # message_id -> response future
        self._task = None
    
    async def start(self) -> None:
        """Start listening for outbound messages from the bus."""
        self._running = True
        self._task = asyncio.create_task(self._listen_outbound())
        logger.info("HTTP channel started")
    
    async def stop(self) -> None:
        """Stop the channel."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("HTTP channel stopped")
    
    async def _listen_outbound(self) -> None:
        """Listen for outbound messages from the agent."""
        while self._running:
            try:
                msg = await self.bus.get_outbound_message()
                
                # Find pending request and complete it
                if msg.thread_id in self.pending_responses:
                    future = self.pending_responses.pop(msg.thread_id)
                    if not future.done():
                        future.set_result(msg.text)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in HTTP outbound listener: {e}")
    
    async def send_message(self, text: str, user_id: str, timeout: float = 120.0) -> str:
        """
        Send a message to the agent and wait for response.
        
        Args:
            text: User message text
            user_id: User ID
            timeout: Max wait time for response
            
        Returns:
            Agent's response text
        """
        # Generate unique message/thread ID
        message_id = str(uuid.uuid4())
        thread_id = f"http-{user_id}"
        
        # Create response future
        response_future = asyncio.Future()
        self.pending_responses[thread_id] = response_future
        
        # Create inbound message and send to bus
        inbound = InboundMessage(
            id=message_id,
            channel=self.name,
            thread_id=thread_id,
            sender_id=user_id,
            sender_name=user_id,
            text=text,
            timestamp=datetime.utcnow().isoformat(),
            attachments=[],
            metadata={
                "user_id": user_id,
            }
        )
        
        await self.bus.put_inbound_message(inbound)
        logger.info(f"HTTP message sent to bus: {text[:50]}...")
        
        # Wait for response
        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            self.pending_responses.pop(thread_id, None)
            logger.warning(f"HTTP message timeout for user {user_id}")
            return "⏰ Запрос занял слишком много времени. Попробуй упростить задачу."
    
    async def _send_message(self, message: OutboundMessage) -> None:
        """Not used in HTTP channel — messages are delivered via send_message()."""
        pass
