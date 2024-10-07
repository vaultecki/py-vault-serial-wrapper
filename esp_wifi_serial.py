import serial
import time


class TaEspClient:
    """class to connect to esp via serial connection"""
    def __init__(self, port="/dev/ttyUSB0", baudrate=115200):
        """set up serial connection.

        :param port: tty port for connection to esp
        :type port: str
        :param baudrate: baudrate of serial connection
        :type baudrate: int
        """
        self.rbuffer = ""
        self.timeout = 60
        self.net_data = False
        self.connect_time = False
        self.ip = False
        self.connection = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=0.1,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS
            )
        expr = "machine.reset()"
        data = self.send(data=expr, timeout=5)
        # print(data)
        time.sleep(2)

    def __analyse_data_scan(self, data):
        """reformat data from wifi scanning to be used later

        :param data: data from wifi scan on esp
        :type data: str

        :return: array with networks found in scan
        :rtype: array
        """
        rdata = []
        data_split = data[2:-2].split("), (")
        for network in data_split:
            network_data = network.split(", ")
            if len(network_data) == 6:
                scan_data = ["ssid", "bssid", "channel", "rssi", "authmode", "hidden"]
                for i in range(len(network_data)):
                    scan_data[i] = network_data[i].lstrip().rstrip()
                rdata.append(scan_data)
        return rdata

    def scan(self):
        """Start a wifi scan on esp and return processed scan data

        :return: array with network data from scan, or false if scan could not run
        :rtype: array
        """
        expr = "b.scan()"
        data = self.send(data=expr, timeout=8.0)
        if len(data) == 3 and data[0] == expr:
            rdata = self.__analyse_data_scan(data[1])
        else:
            rdata = [[False]]
        return rdata

    def ping(self, target):
        """ping target

        :return: ping results
        :rtype: str
        """
        count = 4
        interval = 10
        timeout = 5
        expr = "uping.ping('{}', count={}, timeout={}, interval={}, quiet=False, size=64)".format(target, count, timeout * 1000, interval)
        data = self.send(data=expr, timeout=timeout + 1)
        return self.__analyse_ping(data)

    def send(self, data="", timeout=0.1):
        """send data via serial connection to esp, wait for timeout and recv result from esp

        :param data: str to send to esp
        :type data: str
        :param timeout: time to wait in s
        :type timeout: float

        :return: received data from esp
        :rtype: str
        """
        self.connection.write([ord(x) for x in data+'\r'])
        time.sleep(timeout)
        return self.recv()

    def recv(self):
        """receive data from esp via serial connection

        :return: received serial data
        :rtype: str
        """
        data = True
        while data:
            data = self.connection.read(1024)
            self.rbuffer += data.decode("utf-8")

        lines = []
        for line in self.rbuffer.split("\n"):
            lines.append(line.rstrip())

        self.rbuffer = ""
        return lines

    def test_connect(self, ssid="test", password="1234", timeout=60):
        """test connecting to specified wifi network

        :param ssid: ssid of wifi network to connect
        :type ssid: str
        :param password: password of the wifi network to connect
        :type rsi: str

        :return: time needed to connect, data from scan for the network, ip4 from the network
        :rtype: [connect_time, network_data, ip]
        """
        print("scan for network {}".format(ssid))
        networks = self.scan()
        self.net_data = False
        self.connect_time = False
        self.ip = False
        self.timeout = timeout
        for net in networks:
            if ssid in str(net[0]):
                print("SSID {} exists; channel: {}, authmode: {}, hidden: {}".format(net[0], net[2], net[4], net[5]))
                self.net_data = (ssid, int(net[2]), int(net[4]), bool(net[5]))

                if not self.connect(ssid, password, timeout):
                    return [False, False, False]

                # clean up on esp
                self.disconnect()
        return [self.connect_time, self.net_data, self.ip]

    def connect(self, ssid="test", password="1234", timeout=60):
        """send ssid, password and connect to esp

        :return: True
        :rtype: bool
        """
        print("set parameter {} as ssid".format(ssid))
        expr = "b.set_ssid(\"{}\")".format(ssid)
        data = self.send(data=expr, timeout=2)
        print(data)
        if len(data) != 3 or not data[1].split(":")[1] == ssid:
            # print("error setting ssid")
            return False
        print("set parameter {} as password".format(password))
        expr = "b.set_password(\"{}\")".format(password)
        data = self.send(data=expr, timeout=2)
        # print(data)
        if len(data) != 3 or not data[1].split(":")[1] == password:
            # print("error setting password")
            return False

        print("try to connect")
        expr = "b.connect()"
        start_time = time.time()
        data = self.send(data=expr, timeout=5)
        combined_data = "\t".join(data)
        # wait for connection or timeout
        while "connect:" not in combined_data and (time.time() - start_time < timeout):
            time.sleep(2)
            data = self.recv()
            combined_data = "\t".join(data)

        if "connect:" in combined_data:
            for element in data:
                if "connect:" in element:
                    self.connect_time = int(element.split(":")[1])
            expr = "b.status()"
            status = self.send(data=expr, timeout=5)
            for status_element in status:
                if "ip:" in status_element:
                    self.ip = self.__analyse_ip_status(status_element)
        return True

    def disconnect(self):
        """send disconnect to esp

        :return: True
        :rtype: bool
        """
        expr = "b.disconnect()"
        data = self.send(data=expr, timeout=2)
        # TODO add check disconnect
        return True

    def status(self):
        """get status from esp and get local saved stats

        :return: [connection time, net_data, ip]
        :rtype: array of strings
        """
        expr = "b.status()"
        status = self.send(data=expr, timeout=5)
        if "ip:" in status[-1]:
            self.ip = self.__analyse_ip_status(status[-1])
        return [self.connect_time, self.net_data, self.ip]

    def __analyse_ip_status(self, data):
        """convert ip string from esp to array with ip data

        :param data: ip data
        :type data: str

        :return: ipv4 data [own_ipv4, subnet_mask_ipv4, dhcp_server_ipv4, dns_server_ipv4]
        :rtype: array of strings
        """
        ip = ["own_ip", "subnet_mask", "dhcp_server", "dns_server"]
        split_data = data.split("'")
        ip[0] = split_data[1]
        ip[1] = split_data[3]
        ip[2] = split_data[5]
        ip[3] = split_data[7]
        return ip

    def __analyse_ping(self, data):
        """convert ping results

        :param data: ping results
        :type data: str

        :return: ping data [target, ip, success rate, [list of return times]]
        :rtype: array of strings
        """
        # print(data)
        if type(data) != list:
            return False
        if not any("uping" in str(s) for s in data):
            return False
        if any("EHOSTUNREACH" in str(s) for s in data):
            return "error", "connection"
        if any("OSError: -202" in str(s) for s in data):
            return "error", "dns"
        if "uping" in data[0] and "PING " in data[1]:
            split_target_data = data[1].split(" ")
            target = split_target_data[1]
            ip = split_target_data[2].replace(":", "").replace("(", "").replace(")", "")
            time = []
            success = 0
            for i in range(len(data) - 5):
                if len(data[i + 2].split(" ")) > 6 and data[i + 2].split(" ")[6].startswith("time="):
                    time.append(float(data[i+2].split(" ")[6].replace("time=", "")))
                if len(data[-2].split(" ")) == 2:
                    factors = data[-2].replace("(", "").replace(")", "").split(", ")
                    success = int(factors[1]) / int(factors[0]) * 100
            return target, ip, success, time
        return False

    def close(self):
        """close serial connection """
        self.connection.close()


class TaEspAp:
    """class to connect to esp via serial connection"""
    def __init__(self, port="/dev/ttyUSB0", baudrate=115200):
        """set up serial connection.

        :param port: tty port for connection to esp
        :type port: str
        :param baudrate: baudrate of serial connection
        :type baudrate: int
        """
        self.rbuffer = ""
        self.timeout = 60
        self.connection = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=0.1,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS
            )
        expr = "machine.reset()"
        data = self.send(data=expr, timeout=5)
        # print(data)
        time.sleep(2)

    def send(self, data="", timeout=0.1):
        """send data via serial connection to esp, wait for timeout and recv result from esp

        :param data: str to send to esp
        :type data: str
        :param timeout: time to wait in s
        :type timeout: float

        :return: received data from esp
        :rtype: str
        """
        self.connection.write([ord(x) for x in data+'\r'])
        time.sleep(timeout)
        return self.recv()

    def recv(self):
        """receive data from esp via serial connection

        :return: received serial data
        :rtype: str
        """
        data = True
        while data:
            data = self.connection.read(1024)
            self.rbuffer += data.decode("utf-8")

        lines = []
        for line in self.rbuffer.split("\n"):
            lines.append(line.rstrip())

        self.rbuffer = ""
        return lines
    
    def connected(self):
        expr = "bap.connected()"
        data = self.send(data=expr, timeout=2)
        return data
    
    def time_reset(self):
        expr = "bap.time_reset()"
        data = self.send(data=expr, timeout=2)
        return data
    
    def start(self, ssid="Test_123", password="123456789", channel=12, authmode=3, hidden=0):
        # ssid, password, channel, authmode, hidden
        expr = "bap.set_parameters(\"{}\", \"{}\", \"{}\", \"{}\", \"{}\")".format(ssid, password, channel, authmode, hidden)
        data = self.send(data=expr, timeout=2)
        expr = "bap.start()"
        data = self.send(data=expr, timeout=2)
        return data
    
    def stop(self):
        expr = "bap.stop()"
        data = self.send(data=expr, timeout=2)
        return data

    def close(self):
        """close serial connection """
        self.stop()
        time.sleep(1)
        self.connection.close()


if __name__ == '__main__':
    pass
    serial_ok = True
    try:
        esp_client = TaEspClient()#port="COM3")
    except serial.serialutil.SerialException:
        print("exception connecting to serial device")
        serial_ok = False
    # if serial_ok:
    #     print(time.time())
    #     print(esp_client.scan())
    #     esp_client.close()
    #
    # time.sleep(1)
    # serial_ok = True
    # try:
    #     esp_ap = TaEspAp()#port="COM3")
    # except serial.serialutil.SerialException:
    #     print("exception connecting to serial device")
    #     serial_ok = False
    # if serial_ok:
    #     print(time.time())
    #     esp_ap.start()
    #     print(esp_ap.connected())
    #     time.sleep(60)
    #     print("a")
    #     print(esp_ap.connected())
    #     time.sleep(60)
    #     esp_ap.close()
