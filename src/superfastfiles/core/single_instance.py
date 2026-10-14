"""Uma janela por pasta de dados: abrir de novo só traz a janela que já está aberta (igual ao Finora)."""
import hashlib

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

_server: QLocalServer | None = None
window = None


def name_for(data_dir) -> str:
    return "superfastfiles-" + hashlib.sha1(str(data_dir).lower().encode()).hexdigest()[:16]


def already_running(name: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(500):
        return False
    sock.write(b"show")
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def listen(name: str) -> None:
    global _server
    QLocalServer.removeServer(name)
    _server = QLocalServer()
    _server.newConnection.connect(_on_connection)
    _server.listen(name)


def stop() -> None:
    """Libera o nome (antes de reabrir o programa, para a nova janela não achar que já está aberto)."""
    global _server
    if _server is not None:
        _server.close()
        _server = None


def _on_connection():
    while _server is not None and _server.hasPendingConnections():
        sock = _server.nextPendingConnection()
        sock.disconnected.connect(sock.deleteLater)
    w = QApplication.activeModalWidget() or window
    if w is None:
        return
    if w.isMinimized() or w.isHidden():
        w.showNormal()
    w.raise_()
    w.activateWindow()
