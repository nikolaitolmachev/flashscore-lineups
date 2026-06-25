"""Lineups - PyQt5 entry point."""

import sys
import logging

from PyQt5 import QtGui, QtWidgets

from services.interface import ICON_PATH, UiMainWindow


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon(str(ICON_PATH)))
    main_window = QtWidgets.QMainWindow()
    ui = UiMainWindow()
    ui.setup_ui(main_window)
    main_window.show()
    sys.exit(app.exec_())
