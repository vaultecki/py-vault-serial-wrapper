import os
import sys
import time
import re
import serial
import shutil
import logging
import tempfile
import argparse
from pathlib import Path
from typing import Set, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UploaderException(Exception):
    """Base exception for uploader errors"""
    pass


class SerialConnectionException(UploaderException):
    """Serial connection specific errors"""
    pass


class Uploader:
    """Upload files to MicroPython device via REPL"""

    # Configuration constants
    BAUDRATE = 115200
    TIMEOUT = 0.1
    FILEBLOCKSIZE = 1024
    MAX_BUFFER = 100000  # bytes
    COMMAND_WAIT = 0.05  # seconds between commands
    RECV_TIMEOUT = 5  # seconds for recv operations

    def __init__(
            self,
            port: str,
            file_system_dir: Optional[str] = None,
            excludes: Optional[List[str]] = None,
            includes: Optional[List[str]] = None,
            smash: bool = True,
            smash_level: int = 2,
            temp_dir: Optional[str] = None,
            dry_run: bool = False,
            verbose: bool = False
    ):
        """Initialize uploader with configuration.

        Args:
            port: Serial port (e.g., 'COM3', '/dev/ttyUSB0')
            file_system_dir: Local directory to upload (None = cwd)
            excludes: Basenames to exclude from upload
            includes: If set, only these basenames are uploaded
            smash: Remove comments and blank lines from files
            smash_level: 1=blank lines, 2=full comments, 3=inline comments
            temp_dir: Temporary directory for smashed files
            dry_run: Don't actually upload, just show what would happen
            verbose: Print debug information
        """
        self.port = port
        self.connection = None
        self.rbuffer = ''
        self.dry_run = dry_run
        self.verbose = verbose

        if verbose:
            logger.setLevel(logging.DEBUG)

        # File system setup
        self.file_system_dir = Path(file_system_dir or os.getcwd())
        if not self.file_system_dir.exists():
            raise UploaderException(f"Directory not found: {self.file_system_dir}")

        # Temporary directory
        self.temp_dir = Path(temp_dir or tempfile.gettempdir())
        self.temp_dir.mkdir(exist_ok=True)

        # Exclusions and inclusions
        self.excludes: Set[str] = self._process_list(excludes)
        self.includes: Set[str] = self._process_list(includes)

        # Smashing configuration
        self.smash = smash
        self.smash_level = smash_level

        # Statistics
        self.files_uploaded = 0
        self.dirs_created = 0
        self.bytes_sent = 0

    def _process_list(self, items: Optional[List[str]]) -> Set[str]:
        """Convert list to set of basenames."""
        if not items:
            return set()
        if isinstance(items, str):
            items = items.split()
        return set(os.path.basename(x) for x in items)

    def _validate_port(self) -> bool:
        """Check if serial port is accessible."""
        try:
            test_conn = serial.Serial(
                port=self.port,
                baudrate=self.BAUDRATE,
                timeout=self.TIMEOUT
            )
            test_conn.close()
            return True
        except serial.SerialException as e:
            raise SerialConnectionException(
                f"Cannot access port {self.port}: {e}"
            )

    def _connect(self) -> None:
        """Establish serial connection."""
        if self.dry_run:
            logger.info("DRY RUN: Skipping serial connection")
            return

        logger.info(f"Connecting to {self.port} at {self.BAUDRATE} baud...")
        try:
            self.connection = serial.Serial(
                port=self.port,
                baudrate=self.BAUDRATE,
                timeout=self.TIMEOUT,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS
            )
            self.connection.flush()

            # Clear any pending input
            self.connection.write([3, 3])  # Ctrl-C
            self.recv(done=True)

            logger.info("Connected successfully")
        except serial.SerialException as e:
            raise SerialConnectionException(f"Connection failed: {e}")

    def _disconnect(self) -> None:
        """Close serial connection."""
        if self.connection and not self.dry_run:
            try:
                self.connection.write([3, 3])  # Ctrl-C
                self.recv(done=True)
                self.connection.close()
                logger.info("Disconnected")
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")

    def send(self, line: str = '') -> None:
        """Send command to device.

        Args:
            line: Python command to execute on device
        """
        if self.dry_run:
            logger.debug(f"DRY RUN: Would send: {line}")
            return

        if not self.connection:
            raise SerialConnectionException("Not connected")

        try:
            cmd = line + '\r'
            self.connection.write([ord(x) for x in cmd])
            self.bytes_sent += len(cmd)
            time.sleep(self.COMMAND_WAIT)
            self.recv()
        except serial.SerialException as e:
            raise SerialConnectionException(f"Send failed: {e}")

    def recv(self, done: bool = False) -> None:
        """Receive data from device.

        Args:
            done: If True, print remaining buffer
        """
        if self.dry_run:
            return

        if not self.connection:
            return

        start_time = time.time()
        while time.time() - start_time < self.RECV_TIMEOUT:
            try:
                data = self.connection.read(1024)
                if data:
                    decoded = data.decode(encoding='utf-8', errors='replace')
                    self.rbuffer += decoded
                else:
                    break
            except Exception as e:
                logger.warning(f"Receive error: {e}")
                break

        # Remove carriage returns
        self.rbuffer = self.rbuffer.replace('\r', '')

        # Print complete lines
        while '\n' in self.rbuffer:
            idx = self.rbuffer.index('\n')
            line = self.rbuffer[:idx]
            self.rbuffer = self.rbuffer[idx + 1:]
            if line.strip():
                logger.info(f">> {line}")

        # Print remaining buffer if done
        if done and self.rbuffer.strip():
            logger.info(f">> {self.rbuffer}")

        # Prevent buffer overflow
        if len(self.rbuffer) > self.MAX_BUFFER:
            self.rbuffer = self.rbuffer[-self.MAX_BUFFER:]

    def _smash_file(self, input_path: Path, output_path: Path) -> None:
        """Remove comments and blank lines from file.

        Args:
            input_path: Source file path
            output_path: Destination file path
        """
        try:
            with open(input_path, 'r', encoding='utf-8') as infile:
                with open(output_path, 'w', encoding='utf-8') as outfile:
                    for line in infile:
                        line_stripped = line.strip()

                        # Skip blank lines
                        if not line_stripped:
                            if self.smash_level < 1:
                                outfile.write('\n')
                            continue

                        # Skip full comment lines
                        if line_stripped.startswith('#') and self.smash_level >= 2:
                            continue

                        # Remove inline comments (level 3)
                        if '#' in line_stripped and self.smash_level >= 3:
                            cleaned = line.rstrip().rsplit('#', 1)[0].rstrip()
                            outfile.write(cleaned + '\n')
                        else:
                            outfile.write(line.rstrip() + '\n')

            logger.debug(f"Smashed: {input_path.name}")
        except IOError as e:
            raise UploaderException(f"Cannot smash file {input_path}: {e}")

    def _prepare_file(self, file_path: Path) -> Path:
        """Prepare file for upload (smash if needed).

        Args:
            file_path: Source file path

        Returns:
            Path to file ready for upload
        """
        temp_file = self.temp_dir / f"smash_{file_path.name}"

        # Decide if we should smash
        should_smash = (
                self.smash and
                (file_path.suffix.lower() == '.py')
        )

        if should_smash:
            self._smash_file(file_path, temp_file)
            return temp_file
        else:
            shutil.copy2(file_path, temp_file)
            return temp_file

    def _upload_file(self, local_path: Path, remote_path: str) -> None:
        """Upload single file to device.

        Args:
            local_path: Local file path
            remote_path: Remote path on device (e.g., 'main.py')
        """
        logger.info(f"Uploading: {remote_path}")

        try:
            # Prepare file
            prepared_file = self._prepare_file(local_path)
            file_size = prepared_file.stat().st_size

            if self.dry_run:
                logger.info(f"DRY RUN: Would upload {local_path} to {remote_path}")
                return

            # Open file on device
            self.send(f"outfile=open('{remote_path}',mode='wb')")

            # Send file in chunks
            with open(prepared_file, 'rb') as f:
                chunk_num = 0
                while True:
                    data = f.read(self.FILEBLOCKSIZE)
                    if not data:
                        break
                    self.send(f"outfile.write({data})")
                    chunk_num += 1
                    if self.verbose and chunk_num % 10 == 0:
                        logger.debug(f"  {chunk_num} chunks sent...")

            # Close file
            self.send("outfile.close()")

            self.files_uploaded += 1
            logger.info(f"✓ {remote_path} ({file_size} bytes)")

        except Exception as e:
            logger.error(f"Failed to upload {remote_path}: {e}")
            raise

    def _create_directory(self, dir_path: str) -> None:
        """Create directory on device.

        Args:
            dir_path: Directory path on device
        """
        parent = str(Path(dir_path).parent) if dir_path != '/' else ''
        basename = Path(dir_path).name

        if self.dry_run:
            logger.info(f"DRY RUN: Would create directory {dir_path}")
            return

        try:
            if parent:
                cmd = f"if '{basename}' not in os.listdir('{parent}'): os.mkdir('{parent}/{basename}')"
                logger.debug(f"Creating: {dir_path}")
            else:
                cmd = f"if '{basename}' not in os.listdir(): os.mkdir('{basename}')"
                logger.debug(f"Creating: {basename}")

            self.send(cmd)
            self.dirs_created += 1
        except Exception as e:
            logger.warning(f"Could not create directory {dir_path}: {e}")

    def upload(self) -> bool:
        """Main upload process.

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("=" * 60)
            logger.info("MicroPython File Uploader")
            logger.info("=" * 60)
            logger.info(f"Local root: {self.file_system_dir}")
            logger.info(f"Temp dir: {self.temp_dir}")
            logger.info(f"Excludes: {self.excludes}")
            logger.info(f"Includes: {self.includes}")
            logger.info(f"Smash level: {self.smash_level}")
            logger.info(f"Dry run: {self.dry_run}")
            logger.info("=" * 60)

            # Connect to device
            if not self.dry_run:
                self._validate_port()
                self._connect()
                self.send("import os")

            # Walk file system
            for root, dirs, files in os.walk(self.file_system_dir):
                # Filter directories
                dirs[:] = [
                    d for d in dirs
                    if d not in self.excludes
                ]
                dirs.sort()

                # Filter files
                filtered_files = [
                    f for f in files
                    if f not in self.excludes and
                       (not self.includes or f in self.includes)
                ]
                filtered_files.sort()

                # Create directories
                for d in filtered_files:
                    root_path = Path(root)
                    rel_path = root_path.relative_to(self.file_system_dir)
                    remote_dir = str(rel_path).replace('\\', '/')
                    if remote_dir != '.':
                        self._create_directory(remote_dir)

                # Upload files
                for f in filtered_files:
                    local_file = Path(root) / f
                    rel_path = local_file.relative_to(self.file_system_dir)
                    remote_file = str(rel_path).replace('\\', '/')
                    self._upload_file(local_file, remote_file)

            logger.info("=" * 60)
            logger.info(f"Upload complete!")
            logger.info(f"Files: {self.files_uploaded}, Directories: {self.dirs_created}")
            logger.info(f"Bytes sent: {self.bytes_sent}")
            logger.info("=" * 60)

            return True

        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return False

        finally:
            self._disconnect()
            self._cleanup_temp()

    def _cleanup_temp(self) -> None:
        """Remove temporary files."""
        try:
            for f in self.temp_dir.glob("smash_*"):
                f.unlink()
        except Exception as e:
            logger.warning(f"Could not clean temp files: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Upload files to MicroPython device'
    )
    parser.add_argument(
        'port',
        help='Serial port (e.g., COM3, /dev/ttyUSB0)'
    )
    parser.add_argument(
        '-d', '--directory',
        help='Local directory to upload (default: current directory)'
    )
    parser.add_argument(
        '-e', '--exclude',
        nargs='+',
        default=['REPLace.py', '__pycache__', '.git'],
        help='Basenames to exclude'
    )
    parser.add_argument(
        '-i', '--include',
        nargs='+',
        default=[],
        help='Only upload these basenames (if set)'
    )
    parser.add_argument(
        '--no-smash',
        action='store_true',
        help='Do not remove comments/blank lines'
    )
    parser.add_argument(
        '--smash-level',
        type=int,
        choices=[1, 2, 3],
        default=2,
        help='Smash level (1=blank, 2=comments, 3=inline)'
    )
    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help='Show what would be uploaded without uploading'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )

    args = parser.parse_args()

    try:
        uploader = Uploader(
            port=args.port,
            file_system_dir=args.directory,
            excludes=args.exclude,
            includes=args.include,
            smash=not args.no_smash,
            smash_level=args.smash_level,
            dry_run=args.dry_run,
            verbose=args.verbose
        )
        success = uploader.upload()
        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
