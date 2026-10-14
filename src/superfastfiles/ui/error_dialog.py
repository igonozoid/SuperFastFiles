"""Janela amigável para erros inesperados (o detalhe técnico fica no log)."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from superfastfiles.core import logs


def show_error(summary: str, details: str) -> None:
    app = QApplication.instance()
    if app is None:
        return
    box = QMessageBox(app.activeWindow())
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Algo deu errado")
    box.setText("O SuperFastFiles encontrou um problema inesperado.")
    box.setInformativeText(
        "Os arquivos já copiados continuam no destino. Se a última tarefa não terminou, rode de novo: "
        "o que já está igual é pulado.\n\n"
        "Se o problema se repetir, envie o arquivo superfastfiles.log (da pasta de dados) para o suporte.")
    box.setDetailedText(details)
    copy = box.addButton("Copiar detalhes", QMessageBox.ActionRole)
    folder = box.addButton("Abrir pasta do log", QMessageBox.ActionRole)
    box.addButton("Continuar", QMessageBox.AcceptRole)
    box.exec()
    if box.clickedButton() is copy:
        QGuiApplication.clipboard().setText(f"{summary}\n\n{details}")
    elif box.clickedButton() is folder:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs.LOG_FILE.parent)))
