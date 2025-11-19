import time
import PySignal
import threading
import serial


class SerialConnectionWrapper:
    # class to connect to esp on serial port
    # pysignal recv_data can be used to subscribe to messages from serial connection

    recv_data = PySignal.ClassSignal()

    def __init__(self, port="COM3", baudrate=115200):
        """set up serial connection.

                :param port: tty port for connection to esp
                :type port: str
                :param baudrate: baudrate of serial connection
                :type baudrate: int
                """
        self.timeout = 60
        self.stop_signal = False
        self.connection = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=0.1,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS
        )
        threading.Timer(0.5, self.recv).start()
        # self.recv_data.connect(self.print_recv)
        expr = "import machine"
        self.send(data=expr, timeout=0.5)
        expr = "machine.reset()"
        self.send(data=expr, timeout=2)
        time.sleep(1)

    def send(self, data="", timeout=0.1):
        """send data via serial connection to esp, wait for timeout and recv result from esp

            :param data: str to send to esp
            :type data: str
            :param timeout: time to wait in s
            :type timeout: float

            :return: received data from esp
            :rtype: str
        """
        self.connection.write([ord(x) for x in data + '\r'])
        # time.sleep(timeout)
        return True

    def recv(self):
        """receive data from esp via serial connection

        """
        data = True
        while not self.stop_signal:
            data = self.connection.read(1024)
            data = data.decode("utf-8")
            for line in data.split("\n"):
                if line.strip() != "":
                    self.recv_data.emit(line)

    def print_recv(self, text):
        print("recv: {}".format(text))


if __name__ == "__main__":
    scw = SerialConnectionWrapper(port="COM6")
    scw.recv_data.connect(scw.print_recv)
    while True:
        inp = input()
        scw.send(inp)
    # scw.send("")
    # time.sleep(1)
    # scw.send("print('Hello World')")
    # time.sleep(1)
