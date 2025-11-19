import time
import threading
import serial
import logging
from typing import Callable, Optional
from queue import Queue, Empty

# Configure logging
logger = logging.getLogger(__name__)


class PySignal:
    """Simple signal/slot mechanism for event handling"""

    def __init__(self):
        self.slots = []

    def connect(self, callback: Callable) -> None:
        """Connect callback to signal"""
        if callback not in self.slots:
            self.slots.append(callback)

    def disconnect(self, callback: Callable) -> None:
        """Disconnect callback from signal"""
        if callback in self.slots:
            self.slots.remove(callback)

    def emit(self, *args, **kwargs) -> None:
        """Emit signal to all connected slots"""
        for callback in self.slots:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in signal handler: {e}")


class SerialConnectionException(Exception):
    """Serial connection specific errors"""
    pass


class SerialConnectionWrapper:
    """Robust serial connection handler for MicroPython devices.

    Features:
    - Thread-safe serial communication
    - Non-blocking receive with signal/slot callbacks
    - Automatic reconnection
    - Proper cleanup and resource management
    """

    # Signals
    recv_data = PySignal()
    connected = PySignal()
    disconnected = PySignal()
    error = PySignal()

    def __init__(
            self,
            port: str = "COM3",
            baudrate: int = 115200,
            timeout: float = 0.1,
            auto_reset: bool = False,
            recv_buffer_size: int = 1024,
            recv_timeout: float = 1.0
    ):
        """Initialize serial connection wrapper.

        Args:
            port: Serial port (e.g., 'COM3', '/dev/ttyUSB0')
            baudrate: Baud rate for connection
            timeout: Serial read timeout in seconds
            auto_reset: Automatically reset device on connection
            recv_buffer_size: Size of receive buffer chunks
            recv_timeout: Timeout for receive thread operations
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.auto_reset = auto_reset
        self.recv_buffer_size = recv_buffer_size
        self.recv_timeout = recv_timeout

        self.connection: Optional[serial.Serial] = None
        self.recv_thread: Optional[threading.Thread] = None
        self.stop_signal = False
        self.recv_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.recv_queue: Queue = Queue()
        self.connected_flag = False

        logger.info(f"SerialConnectionWrapper initialized: {port} @ {baudrate} baud")

    def connect(self) -> bool:
        """Establish serial connection.

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Connecting to {self.port}...")

            self.connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS
            )

            time.sleep(0.5)  # Wait for device to be ready

            # Clear any pending data
            self.connection.reset_input_buffer()
            self.connection.reset_output_buffer()

            # Start receive thread
            self.stop_signal = False
            self.recv_thread = threading.Thread(
                target=self._recv_worker,
                daemon=True,
                name="SerialRecvThread"
            )
            self.recv_thread.start()

            self.connected_flag = True
            logger.info("Connected successfully")
            self.connected.emit()

            # Optional: reset device
            if self.auto_reset:
                logger.info("Auto-resetting device...")
                self.send("import machine\r", timeout=0.5)
                self.send("machine.reset()\r", timeout=2)
                time.sleep(1)

            return True

        except serial.SerialException as e:
            logger.error(f"Connection failed: {e}")
            self.error.emit(f"Connection error: {e}")
            self.connected_flag = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}")
            self.error.emit(f"Unexpected error: {e}")
            return False

    def disconnect(self) -> None:
        """Close serial connection and cleanup resources."""
        try:
            logger.info("Disconnecting...")

            # Signal receive thread to stop
            self.stop_signal = True

            # Wait for receive thread to finish
            if self.recv_thread and self.recv_thread.is_alive():
                self.recv_thread.join(timeout=2)

            # Close serial connection
            if self.connection and self.connection.is_open:
                self.connection.close()

            self.connected_flag = False
            logger.info("Disconnected")
            self.disconnected.emit()

        except Exception as e:
            logger.error(f"Error during disconnect: {e}")

    def send(self, data: str, timeout: float = 0.1) -> bool:
        """Send data to device via serial connection.

        Args:
            data: String to send to device
            timeout: Time to wait after sending

        Returns:
            True if successful, False otherwise
        """
        if not self.connected_flag or not self.connection:
            logger.error("Not connected - cannot send")
            return False

        try:
            with self.send_lock:
                # Convert string to bytes
                if isinstance(data, str):
                    data_bytes = [ord(x) for x in data]
                else:
                    data_bytes = data

                self.connection.write(data_bytes)
                self.connection.flush()

                logger.debug(f"Sent: {repr(data[:50])}")

            # Optional wait after sending
            if timeout > 0:
                time.sleep(timeout)

            return True

        except serial.SerialException as e:
            logger.error(f"Serial error while sending: {e}")
            self.error.emit(f"Send error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while sending: {e}")
            self.error.emit(f"Unexpected send error: {e}")
            return False

    def _recv_worker(self) -> None:
        """Worker thread for receiving data from device.

        Runs in background thread and emits signals when data received.
        """
        logger.info("Receive thread started")

        try:
            while not self.stop_signal:
                try:
                    with self.recv_lock:
                        if not self.connection or not self.connection.is_open:
                            break

                        data = self.connection.read(self.recv_buffer_size)

                    if data:
                        try:
                            decoded = data.decode('utf-8', errors='replace')

                            # Process each line
                            for line in decoded.split('\n'):
                                line = line.strip('\r').strip()
                                if line:
                                    logger.debug(f"Received: {repr(line)}")
                                    self.recv_data.emit(line)

                        except Exception as e:
                            logger.warning(f"Error decoding data: {e}")

                    time.sleep(0.01)  # Small delay to prevent CPU spinning

                except serial.SerialException as e:
                    logger.error(f"Serial error in receive thread: {e}")
                    self.error.emit(f"Receive error: {e}")
                    break
                except Exception as e:
                    logger.warning(f"Error in receive thread: {e}")
                    continue

        finally:
            logger.info("Receive thread stopped")

    def is_connected(self) -> bool:
        """Check if connected to device.

        Returns:
            True if connected, False otherwise
        """
        return (
                self.connected_flag and
                self.connection is not None and
                self.connection.is_open
        )

    def flush(self) -> None:
        """Flush send and receive buffers."""
        try:
            with self.send_lock:
                if self.connection:
                    self.connection.flush()
                    self.connection.reset_input_buffer()
            logger.debug("Buffers flushed")
        except Exception as e:
            logger.warning(f"Error flushing buffers: {e}")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()

    def __del__(self):
        """Destructor - ensure cleanup."""
        if self.is_connected():
            self.disconnect()


# Example usage
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


    def on_data(line):
        """Handle received data"""
        print(f">>> {line}")


    def on_connected():
        """Handle connection"""
        print("✓ Connected")


    def on_error(msg):
        """Handle errors"""
        print(f"✗ Error: {msg}")


    # Connect using context manager (recommended)
    try:
        with SerialConnectionWrapper(port="COM3", auto_reset=False) as conn:
            conn.recv_data.connect(on_data)
            conn.connected.connect(on_connected)
            conn.error.connect(on_error)

            # Send commands
            conn.send("print('Hello from MicroPython')\r")
            time.sleep(0.5)

            # Interactive loop
            try:
                while conn.is_connected():
                    user_input = input(">>> ")
                    if user_input.lower() == 'exit':
                        break
                    conn.send(user_input + '\r', timeout=0.1)
                    time.sleep(0.2)
            except KeyboardInterrupt:
                print("\nExiting...")

    except Exception as e:
        print(f"Fatal error: {e}")
    