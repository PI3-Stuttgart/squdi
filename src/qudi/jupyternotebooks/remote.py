import sys
import ssl
import rpyc
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QLabel, QMessageBox
import socket # Ensure this is imported at the top
from rpyc.utils.factory import connect_stream # Ensure this is imported
import socket
import ssl
from rpyc.utils.factory import connect_stream
import socket
import ssl
import rpyc
from rpyc.utils.factory import connect_stream
from rpyc.core.stream import SocketStream
class QudiRemoteClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qudi Remote Client")
        self.resize(400, 200)

        # Qudi Connection Details
        self.host = '129.69.46.64'
        self.port = 12345
        # Note: The client usually needs the CA cert or the peer's cert to verify.
        # If Qudi is using self-signed certs, you might need to use the same cert file 
        # or disable verification (see verify_mode below).
        self.certfile = r'C:\Users\yy3\keys\attodry.crt'
        self.keyfile = r'C:\Users\yy3\keys\attodry.key'
        
        self.conn = None
        self.qudi_manager = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        self.status_label = QLabel("Status: Disconnected")
        layout.addWidget(self.status_label)

        self.btn_connect = QPushButton("Connect to Qudi")
        self.btn_connect.clicked.connect(self.connect_to_qudi)
        layout.addWidget(self.btn_connect)

        self.btn_action = QPushButton("Get Active Modules")
        self.btn_action.clicked.connect(self.get_modules)
        self.btn_action.setEnabled(False)
        layout.addWidget(self.btn_action)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)


    def connect_to_qudi(self):
        try:
            # 1. Create a standard TCP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10) # Good to have a timeout
            sock.connect((self.host, self.port))

            # 2. Create the SSL Context for a CLIENT
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            context.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)
            
            # 3. Disable Hostname and Cert Verification
            # (Required for Qudi if using self-signed certs/IP addresses)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            # 4. Wrap the socket
            ssl_sock = context.wrap_socket(sock, server_hostname=self.host)

            # 5. Wrap the SSL socket in an RPyC Stream <--- THE FIX
            # RPyC needs this wrapper to handle buffering and data chunks
            rpyc_stream = SocketStream(ssl_sock)

            # 6. Hand the stream over to RPyC
            self.conn = connect_stream(rpyc_stream, config={'allow_public_attrs': True})

            # Access the root object (The Qudi Manager)
            self.qudi_manager = self.conn.root

            self.status_label.setText(f"Status: Connected to {self.host}")
            self.btn_connect.setEnabled(False)
            self.btn_action.setEnabled(True)
            
            print("Connection successful!")

        except Exception as e:
            self.status_label.setText("Status: Connection Failed")
            QMessageBox.critical(self, "Connection Error", str(e))
            print(f"Error: {e}")

    def get_modules(self):
        if self.qudi_manager:
            try:
                # Example: Accessing the list of loaded hardware modules
                # Qudi's manager usually has 'hardware', 'logic', and 'gui' dictionaries.
                hw_modules = self.qudi_manager.hardware.keys()
                
                module_list = "\n".join(list(hw_modules))
                QMessageBox.information(self, "Loaded Hardware", f"Modules found:\n{module_list}")
                
                # Example: Accessing a specific function in a specific module
                # val = self.qudi_manager.hardware['my_laser'].get_power()
                
            except Exception as e:
                QMessageBox.warning(self, "RPC Error", f"Failed to fetch data: {e}")

    def closeEvent(self, event):
        # Clean up connection on close
        if self.conn:
            self.conn.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = QudiRemoteClient()
    window.show()
    sys.exit(app.exec_())