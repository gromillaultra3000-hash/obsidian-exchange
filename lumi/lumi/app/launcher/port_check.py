import socket
from lumi.app.schemas.launcher import PortCheckResult
class PortChecker:
    def check_port(self, host='127.0.0.1', port=8000):
        s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(1)
        try:
            s.bind((host, int(port))); s.close(); return PortCheckResult(host=host, port=int(port), available=True, message=f'Port {port} is available')
        except OSError:
            try: s.close()
            except Exception: pass
            return PortCheckResult(host=host, port=int(port), available=False, message=f'Port {port} is already in use')
