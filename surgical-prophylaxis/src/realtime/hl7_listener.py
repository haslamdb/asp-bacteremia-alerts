"""
HL7 MLLP (Minimal Lower Layer Protocol) listener for real-time messages.

Receives ADT (patient tracking) and ORM/SIU (scheduling) messages
via TCP socket using MLLP framing.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Awaitable, Any

from .hl7_parser import HL7Message, parse_hl7_message, build_ack_message

logger = logging.getLogger(__name__)

# MLLP framing characters
MLLP_START = b"\x0b"  # VT (vertical tab)
MLLP_END = b"\x1c\r"  # FS CR (file separator + carriage return)


@dataclass
class HL7ListenerConfig:
    """Configuration for HL7 MLLP listener."""

    host: str = "0.0.0.0"
    port: int = 2575
    enabled: bool = True
    max_connections: int = 10
    receive_timeout: float = 30.0
    send_ack: bool = True

    @classmethod
    def from_env(cls) -> "HL7ListenerConfig":
        """Create config from environment variables."""
        import os

        return cls(
            host=os.getenv("HL7_LISTENER_HOST", "0.0.0.0"),
            port=int(os.getenv("HL7_LISTENER_PORT", "2575")),
            enabled=os.getenv("HL7_ENABLED", "true").lower() == "true",
            max_connections=int(os.getenv("HL7_MAX_CONNECTIONS", "10")),
            receive_timeout=float(os.getenv("HL7_RECEIVE_TIMEOUT", "30.0")),
            send_ack=os.getenv("HL7_SEND_ACK", "true").lower() == "true",
        )


# Type alias for message handler callback
MessageHandlerCallback = Callable[[HL7Message], Awaitable[None]]


class MessageHandler:
    """
    Routes HL7 messages to appropriate handlers based on message type.

    Usage:
        handler = MessageHandler()
        handler.on_adt = handle_adt_message
        handler.on_orm = handle_orm_message
        await handler.handle(message)
    """

    def __init__(self):
        # Message type handlers
        self.on_adt: Optional[MessageHandlerCallback] = None
        self.on_orm: Optional[MessageHandlerCallback] = None
        self.on_siu: Optional[MessageHandlerCallback] = None
        self.on_unknown: Optional[MessageHandlerCallback] = None

        # Statistics
        self.messages_received = 0
        self.messages_by_type: dict[str, int] = {}
        self.errors = 0

    async def handle(self, message: HL7Message) -> bool:
        """
        Route a message to the appropriate handler.

        Args:
            message: Parsed HL7 message

        Returns:
            True if handled successfully, False otherwise
        """
        self.messages_received += 1
        msg_type = message.message_type

        # Track by type
        key = f"{msg_type}^{message.message_event}"
        self.messages_by_type[key] = self.messages_by_type.get(key, 0) + 1

        try:
            if msg_type == "ADT" and self.on_adt:
                await self.on_adt(message)
                return True
            elif msg_type == "ORM" and self.on_orm:
                await self.on_orm(message)
                return True
            elif msg_type == "SIU" and self.on_siu:
                await self.on_siu(message)
                return True
            elif self.on_unknown:
                await self.on_unknown(message)
                return True
            else:
                logger.debug(f"No handler for message type {msg_type}")
                return True  # Not an error, just unhandled

        except Exception as e:
            self.errors += 1
            logger.error(f"Error handling {msg_type} message: {e}")
            return False

    def get_stats(self) -> dict:
        """Get handler statistics."""
        return {
            "messages_received": self.messages_received,
            "messages_by_type": self.messages_by_type.copy(),
            "errors": self.errors,
        }


class HL7MLLPServer:
    """
    Async MLLP server for receiving HL7 messages.

    Usage:
        handler = MessageHandler()
        handler.on_adt = my_adt_handler

        server = HL7MLLPServer(handler=handler)
        await server.start()

        # Later...
        await server.stop()
    """

    def __init__(
        self,
        handler: Optional[MessageHandler] = None,
        config: Optional[HL7ListenerConfig] = None,
    ):
        self.handler = handler or MessageHandler()
        self.config = config or HL7ListenerConfig.from_env()

        self._server: Optional[asyncio.AbstractServer] = None
        self._running = False
        self._connections: set[asyncio.Task] = set()

        # Statistics
        self.connections_total = 0
        self.connections_active = 0

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    async def start(self) -> None:
        """Start the MLLP server."""
        if not self.config.enabled:
            logger.info("HL7 listener disabled by configuration")
            return

        if self._running:
            logger.warning("HL7 server already running")
            return

        self._server = await asyncio.start_server(
            self._handle_client,
            self.config.host,
            self.config.port,
            limit=64 * 1024,  # 64KB buffer
        )

        self._running = True

        addr = self._server.sockets[0].getsockname()
        logger.info(f"HL7 MLLP server listening on {addr[0]}:{addr[1]}")

        # Start serving in background
        asyncio.create_task(self._serve())

    async def _serve(self) -> None:
        """Background task to serve connections."""
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop the MLLP server."""
        if not self._running:
            return

        self._running = False

        # Cancel all active connections
        for task in self._connections:
            task.cancel()

        # Wait for connections to close
        if self._connections:
            await asyncio.gather(*self._connections, return_exceptions=True)

        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        logger.info("HL7 MLLP server stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        self.connections_total += 1
        self.connections_active += 1

        peer = writer.get_extra_info("peername")
        logger.debug(f"HL7 connection from {peer}")

        # Track this connection
        task = asyncio.current_task()
        self._connections.add(task)

        try:
            while self._running:
                # Read message with MLLP framing
                message_bytes = await self._read_mllp_message(reader)

                if not message_bytes:
                    break  # Connection closed

                # Parse message
                try:
                    message_str = message_bytes.decode("utf-8", errors="replace")
                    message = parse_hl7_message(message_str)

                    logger.debug(
                        f"Received {message.message_type}^{message.message_event} "
                        f"from {peer}"
                    )

                    # Handle message
                    success = await self.handler.handle(message)

                    # Send ACK if configured
                    if self.config.send_ack:
                        ack_code = "AA" if success else "AE"
                        ack = build_ack_message(message, ack_code)
                        await self._send_mllp_message(writer, ack)

                except Exception as e:
                    logger.error(f"Error processing message from {peer}: {e}")

                    # Send error ACK
                    if self.config.send_ack:
                        try:
                            message = parse_hl7_message(message_bytes.decode("utf-8", errors="replace"))
                            ack = build_ack_message(message, "AE", str(e))
                            await self._send_mllp_message(writer, ack)
                        except Exception:
                            pass

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Connection error from {peer}: {e}")
        finally:
            self.connections_active -= 1
            self._connections.discard(task)

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

            logger.debug(f"HL7 connection closed from {peer}")

    async def _read_mllp_message(
        self,
        reader: asyncio.StreamReader,
    ) -> Optional[bytes]:
        """Read a single MLLP-framed message."""
        try:
            # Read until we find the start byte
            while True:
                byte = await asyncio.wait_for(
                    reader.read(1),
                    timeout=self.config.receive_timeout,
                )

                if not byte:
                    return None  # Connection closed

                if byte == MLLP_START:
                    break

            # Read until end frame
            data = b""
            while True:
                chunk = await asyncio.wait_for(
                    reader.read(4096),
                    timeout=self.config.receive_timeout,
                )

                if not chunk:
                    return None

                data += chunk

                # Check for end frame
                if MLLP_END in data:
                    # Extract message (remove end frame)
                    end_pos = data.index(MLLP_END)
                    return data[:end_pos]

                # Prevent unbounded growth
                if len(data) > 1024 * 1024:  # 1MB limit
                    logger.error("Message too large, discarding")
                    return None

        except asyncio.TimeoutError:
            return None

    async def _send_mllp_message(
        self,
        writer: asyncio.StreamWriter,
        message: str,
    ) -> None:
        """Send an MLLP-framed message."""
        framed = MLLP_START + message.encode("utf-8") + MLLP_END
        writer.write(framed)
        await writer.drain()

    def get_stats(self) -> dict:
        """Get server statistics."""
        return {
            "running": self._running,
            "host": self.config.host,
            "port": self.config.port,
            "connections_total": self.connections_total,
            "connections_active": self.connections_active,
            "handler_stats": self.handler.get_stats(),
        }


async def create_hl7_listener(
    on_adt: Optional[MessageHandlerCallback] = None,
    on_orm: Optional[MessageHandlerCallback] = None,
    on_siu: Optional[MessageHandlerCallback] = None,
    config: Optional[HL7ListenerConfig] = None,
) -> HL7MLLPServer:
    """
    Factory function to create and configure an HL7 listener.

    Args:
        on_adt: Handler for ADT messages
        on_orm: Handler for ORM messages
        on_siu: Handler for SIU messages
        config: Optional configuration

    Returns:
        Configured HL7MLLPServer (not started)
    """
    handler = MessageHandler()
    handler.on_adt = on_adt
    handler.on_orm = on_orm
    handler.on_siu = on_siu

    return HL7MLLPServer(handler=handler, config=config)


class HL7TestClient:
    """
    Simple client for testing HL7 MLLP server.

    Usage:
        client = HL7TestClient("localhost", 2575)
        ack = await client.send_message(hl7_message_string)
    """

    def __init__(self, host: str = "localhost", port: int = 2575):
        self.host = host
        self.port = port

    async def send_message(self, message: str) -> Optional[str]:
        """
        Send an HL7 message and receive the ACK.

        Args:
            message: Raw HL7 message string

        Returns:
            ACK message string or None if failed
        """
        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)

            # Send MLLP-framed message
            framed = MLLP_START + message.encode("utf-8") + MLLP_END
            writer.write(framed)
            await writer.drain()

            # Read ACK
            data = b""
            while MLLP_END not in data:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=10.0)
                if not chunk:
                    break
                data += chunk

            writer.close()
            await writer.wait_closed()

            # Parse response
            if MLLP_START in data and MLLP_END in data:
                start = data.index(MLLP_START) + 1
                end = data.index(MLLP_END)
                return data[start:end].decode("utf-8")

            return None

        except Exception as e:
            logger.error(f"Error sending HL7 message: {e}")
            return None

    async def send_adt_a02(
        self,
        patient_mrn: str,
        patient_name: str,
        current_location: str,
        prior_location: str = "",
    ) -> Optional[str]:
        """
        Send a test ADT^A02 (transfer) message.

        Args:
            patient_mrn: Patient MRN
            patient_name: Patient name (Last^First format)
            current_location: Current location code
            prior_location: Prior location code

        Returns:
            ACK message or None
        """
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        msg_id = f"TEST{timestamp}"

        message = (
            f"MSH|^~\\&|AEGIS|AEGIS|TEST|TEST|{timestamp}||ADT^A02|{msg_id}|P|2.5\r"
            f"EVN|A02|{timestamp}\r"
            f"PID|||{patient_mrn}^^^HOSPITAL^MR||{patient_name}|||||||||||\r"
            f"PV1||I|{current_location}||||||||||||||||V001|||||||||||||||||||||||||||{prior_location}\r"
        )

        return await self.send_message(message)
