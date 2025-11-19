# MicroPython Upload Tools - Production Ready

Improved versions of `REPLace.py` and `SerialConnectionWrapper` with production-quality error handling, logging, and threading.

## Installation

```bash
pip install -r requirements.txt
```

**Requirements:**
- Python 3.6+
- PySerial >= 3.5

## REPLace.py - File Upload Tool

Upload entire directory trees to MicroPython devices via REPL connection.

### Usage

**Basic usage:**
```bash
python replace.py COM3
```

**With options:**
```bash
# Dry-run to preview what would be uploaded
python replace.py COM3 --dry-run

# Upload specific directory
python replace.py COM3 -d /path/to/files

# Exclude specific files/directories
python replace.py COM3 -e boot.py config.json __pycache__

# Only upload specific files
python replace.py COM3 -i main.py boot.py

# Remove inline comments during upload (level 3)
python replace.py COM3 --smash-level 3

# Verbose output for debugging
python replace.py COM3 -v
```

### Full CLI Options

```
positional arguments:
  port                  Serial port (e.g., COM3, /dev/ttyUSB0)

optional arguments:
  -h, --help            Show help message
  -d, --directory DIR   Local directory to upload (default: current)
  -e, --exclude ITEMS   Basenames to exclude (default: REPLace.py, __pycache__, .git)
  -i, --include ITEMS   Only upload these basenames (if set)
  --no-smash            Do not remove comments/blank lines
  --smash-level LEVEL   1=blank lines, 2=full comments, 3=inline comments (default: 2)
  -n, --dry-run         Preview without uploading
  -v, --verbose         Verbose debug output
```

### Smashing Levels

**Level 1:** Remove blank lines only
```python
# Before
def hello():
    
    print("world")

# After
def hello():
    print("world")
```

**Level 2:** Remove blank lines and full-line comments (default)
```python
# Before
def hello():
    # This is a comment
    print("world")  # Inline comment kept

# After
def hello():
    print("world")  # Inline comment kept
```

**Level 3:** Remove blank lines, comments, and inline comments
```python
# Before
def hello():
    # This is a comment
    print("world")  # Inline comment

# After
def hello():
    print("world")
```

### Usage in Python Code

```python
from replace import Uploader

# Create uploader instance
uploader = Uploader(
    port="COM3",
    file_system_dir="/path/to/micropython/files",
    excludes=["test.py", "config"],
    includes=[],  # Empty = upload all (except excludes)
    smash=True,
    smash_level=2,
    dry_run=False,
    verbose=True
)

# Run upload
success = uploader.upload()
if success:
    print(f"Uploaded {uploader.files_uploaded} files")
```

### Statistics

After upload, the uploader provides statistics:
```
Files: 12, Directories: 4
Bytes sent: 45,320
```

## SerialConnectionWrapper - Connection Handler

Robust serial connection with threading, signal/slot callbacks, and automatic cleanup.

### Basic Usage

**Simple example:**
```python
from serial_wrapper import SerialConnectionWrapper

# Create connection
conn = SerialConnectionWrapper(port="COM3")

# Connect
conn.connect()

# Send command
conn.send("print('Hello')\r")

# Receive callback
def on_data(line):
    print(f">>> {line}")

conn.recv_data.connect(on_data)

# Cleanup
conn.disconnect()
```

**Using context manager (recommended):**
```python
from serial_wrapper import SerialConnectionWrapper

with SerialConnectionWrapper(port="COM3") as conn:
    conn.recv_data.connect(lambda line: print(f">>> {line}"))
    
    conn.send("print('Hello')\r")
    
    # Connection automatically closed on exit
```

### Signal/Slot System

Connect callbacks to events:

```python
def on_data_received(line):
    print(f"Received: {line}")

def on_connected():
    print("Device connected!")

def on_disconnected():
    print("Device disconnected!")

def on_error(message):
    print(f"Error: {message}")

conn = SerialConnectionWrapper(port="COM3")
conn.recv_data.connect(on_data_received)
conn.connected.connect(on_connected)
conn.disconnected.connect(on_disconnected)
conn.error.connect(on_error)

conn.connect()
```

### Constructor Options

```python
SerialConnectionWrapper(
    port="COM3",              # Serial port
    baudrate=115200,          # Baud rate
    timeout=0.1,              # Read timeout
    auto_reset=False,         # Reset device on connection
    recv_buffer_size=1024,    # Receive buffer size
    recv_timeout=1.0          # Timeout for recv operations
)
```

### Methods

- `connect()` - Establish connection, returns True/False
- `disconnect()` - Close connection and cleanup
- `send(data, timeout=0.1)` - Send data to device
- `is_connected()` - Check connection status
- `flush()` - Flush input/output buffers

## Advanced Examples

### Interactive Shell

```python
from serial_wrapper import SerialConnectionWrapper
import time

with SerialConnectionWrapper(port="COM3") as conn:
    conn.recv_data.connect(lambda line: print(f">>> {line}"))
    
    while conn.is_connected():
        try:
            user_input = input("MicroPython> ")
            if user_input.lower() == 'exit':
                break
            conn.send(user_input + '\r', timeout=0.1)
            time.sleep(0.2)
        except KeyboardInterrupt:
            print("\nExiting...")
            break
```

### File Transfer with Verification

```python
from replace import Uploader
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

uploader = Uploader(
    port="COM3",
    file_system_dir="./micropython_code",
    excludes=["test.py", "secrets.py"],
    dry_run=False,
    verbose=True
)

try:
    if uploader.upload():
        print(f"✓ Successfully uploaded {uploader.files_uploaded} files")
    else:
        print("✗ Upload failed")
except Exception as e:
    print(f"✗ Error: {e}")
```

### Logging Configuration

Control logging verbosity:

```python
import logging

# Quiet mode (errors only)
logging.getLogger().setLevel(logging.ERROR)

# Info mode (default)
logging.getLogger().setLevel(logging.INFO)

# Debug mode (verbose)
logging.getLogger().setLevel(logging.DEBUG)
```

## Improvements Over Original

### REPLace.py
✓ Exception handling with custom exception classes
✓ Configurable via CLI arguments (no code editing needed)
✓ Dry-run mode to preview uploads
✓ Proper logging instead of print statements
✓ Thread-safe buffer management with overflow protection
✓ Path handling works on Windows/Linux/macOS
✓ Smash level control (1, 2, or 3)
✓ Upload statistics tracking
✓ Better timeout and error handling
✓ Type hints for better IDE support

### SerialConnectionWrapper
✓ Proper threading with daemon threads
✓ Thread-safe locks for send/receive
✓ Signal/slot mechanism built-in (no external PySignal dependency)
✓ Context manager support for automatic cleanup
✓ Better error handling and reporting
✓ Connection status tracking
✓ Comprehensive logging
✓ Configurable reset behavior
✓ Proper resource cleanup on disconnect

## Troubleshooting

### Port Not Found
```
SerialConnectionException: Cannot access port COM3
```
- Check port name (use Device Manager on Windows)
- Ensure device is connected
- On Linux: `sudo adduser $USER dialout && reboot`

### Slow Uploads
- Reduce file size with `--smash-level 3`
- Use `--includes` to upload only needed files
- Increase `fileblocksize` if experiencing timeout errors

### Connection Drops During Upload
- Increase timeouts in constructor
- Reduce `fileblocksize` from 1024 to 512
- Check USB cable quality

### "Not Connected" Error
- Call `connect()` before `send()`
- Check serial port is correct
- Verify device is turned on

## Platform Notes

### Windows
- Ports: `COM1`, `COM3`, `COM4` (check Device Manager)
- May need administrator privileges

### Linux
```bash
# List available ports
ls /dev/ttyUSB*
ls /dev/ttyACM*

# Add user to dialout group
sudo adduser $USER dialout
# Log out and back in
```

### macOS
```bash
# List available ports
ls /dev/tty.usbserial*
ls /dev/tty.wchusbserial*
```

## Performance Tips

1. **Minimize file size** - Use `--smash-level 3` for production
2. **Selective upload** - Use `--includes` if updating only a few files
3. **Disable logging in production** - Set logging level to ERROR
4. **Use appropriate chunk size** - Default 1024 bytes is usually optimal

## License

Original concept: Clayton Darwin (claytondarwin.com)
Improvements: Production hardening, error handling, threading

## See Also

- Adafruit ampy (alternative upload tool)
- WebREPL (browser-based REPL)
- MicroPython official documentation: https://micropython.org
