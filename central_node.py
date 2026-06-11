import sys
import asyncio
import struct
import traceback
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakError

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QGroupBox, QStatusBar, QDialog,
    QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtGui import QFont, QColor
import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from collections import deque

# ── BLE Configuration ─────────────────────────────────────────────────────────
ADDRESS    = "48:23:35:F4:00:07"
RELAY_UUID = "11111111-0000-0000-0000-111111111111"
MEAS_UUID  = "22222222-0000-0000-0000-222222222222"
RECONNECT_DELAY = 5

NOISE_V_THRESHOLD = 0.55    # V  — max noise voltage with no load
NOISE_I_THRESHOLD = 0.356   # A  — max noise current with no load

MEAS_FMT = "<hhihhHB"
MEAS_LEN = struct.calcsize(MEAS_FMT)   # 15


# ── Logger ────────────────────────────────────────────────────────────────────
class Logger:
    FOLDER_NAME = "sensor_node1"

    def __init__(self):
        self._file     = None
        self.is_active = False

    def _log_path(self) -> Path:
        desktop  = Path.home() / "Desktop"
        folder   = desktop / self.FOLDER_NAME
        folder.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%d.%m.%y")
        return folder / f"sensor_node1-{date_str}.txt"

    def start(self):
        if self.is_active:
            return
        path       = self._log_path()
        new_file   = not path.exists()
        self._file = open(path, "a", encoding="utf-8")
        if new_file:
            self._file.write(
                "timestamp,v_rms_V,i_rms_A,p_W,s_VA,q_VAr,pf,"
                "freq_Hz,temp_C,humid_pct,relay_state\n"
            )
            self._file.flush()
        self.is_active = True
        return str(path)

    def stop(self):
        if not self.is_active:
            return
        self._file.close()
        self._file     = None
        self.is_active = False

    def write(self, row: dict):
        if not self.is_active or self._file is None:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._file.write(
            f"{ts},"
            f"{row['v_rms']:.2f},{row['i_rms']:.3f},{row['p_w']:.2f},"
            f"{row['s_va']:.2f},{row['q_var']:.2f},{row['pf']:.3f},"
            f"{row['freq']:.2f},{row['temp']:.2f},{row['humid']:.2f},"
            f"{'ON' if row['relay'] else 'OFF'}\n"
        )
        self._file.flush()


# ── Derived quantities ────────────────────────────────────────────────────────
def compute_derived(v_rms, i_rms, p_w):
    s_va  = v_rms * i_rms
    diff  = s_va ** 2 - p_w ** 2
    q_var = diff ** 0.5 if diff > 0 else 0.0
    pf    = (p_w / s_va) if s_va > 0 else 0.0
    return s_va, q_var, pf


# ── BLE worker (runs asyncio in a background QThread) ─────────────────────────
class BleWorker(QThread):
    measurement = pyqtSignal(dict)   # emits decoded measurement dict
    relay_state = pyqtSignal(bool)   # emits relay ON/OFF
    connected   = pyqtSignal(bool)   # emits True on connect, False on disconnect

    def __init__(self):
        super().__init__()
        self._relay_cmd  = None      # "on" | "off" | "toggle"
        self._loop       = None

    def send_relay(self, cmd: str):
        self._relay_cmd = cmd

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._ble_main())

    async def _ble_main(self):
        while True:
            try:
                async with BleakClient(ADDRESS) as client:
                    self.connected.emit(True)
                    await self._session(client)
                    self.connected.emit(False)
            except Exception:
                self.connected.emit(False)
            await asyncio.sleep(RECONNECT_DELAY)

    async def _session(self, client):
        def on_relay(sender, data):
            self.relay_state.emit(data[0] == 0x01)

        def on_meas(sender, data):
            if len(data) != MEAS_LEN:
                return
            v_raw, i_raw, p_raw, freq_raw, temp_raw, humid_raw, relay = \
                struct.unpack(MEAS_FMT, data)
            v_rms = v_raw   / 100.0
            i_rms = i_raw   / 1000.0
            p_w   = p_raw   / 100.0
            freq  = freq_raw / 100.0
            temp  = temp_raw / 100.0
            humid = humid_raw / 100.0
            if v_rms <= NOISE_V_THRESHOLD:
                v_rms = p_w = 0.0
            if i_rms <= NOISE_I_THRESHOLD:
                i_rms = p_w = 0.0
            s_va, q_var, pf = compute_derived(v_rms, i_rms, p_w)
            self.measurement.emit({
                "v_rms": v_rms, "i_rms": i_rms, "p_w": p_w,
                "s_va": s_va,   "q_var": q_var,  "pf": pf,
                "freq": freq,   "temp": temp,    "humid": humid,
                "relay": bool(relay)
            })

        await client.start_notify(RELAY_UUID, on_relay)
        await client.start_notify(MEAS_UUID,  on_meas)

        while client.is_connected:
            cmd = self._relay_cmd
            if cmd is not None:
                self._relay_cmd = None
                try:
                    val = {"on": 0x01, "off": 0x00, "toggle": 0xFF}[cmd]
                    await client.write_gatt_char(RELAY_UUID, bytes([val]))
                except Exception:
                    pass
            await asyncio.sleep(0.2)


# ── Plot window ───────────────────────────────────────────────────────────────
class PlotWindow(QDialog):
    MAX_POINTS = 120   # 2 minutes of 1 Hz data

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Live Plots")
        self.resize(820, 560)

        self._v = deque(maxlen=self.MAX_POINTS)
        self._i = deque(maxlen=self.MAX_POINTS)
        self._p = deque(maxlen=self.MAX_POINTS)
        self._t = deque(maxlen=self.MAX_POINTS)   # x-axis (seconds ago)

        self._fig = Figure(facecolor="#1e1e2e")
        self._canvas = FigureCanvas(self._fig)
        self._ax_v = self._fig.add_subplot(311)
        self._ax_i = self._fig.add_subplot(312)
        self._ax_p = self._fig.add_subplot(313)
        self._fig.tight_layout(pad=2.5)

        for ax, label, color in [
            (self._ax_v, "Vrms (V)",  "#89b4fa"),
            (self._ax_i, "Irms (A)",  "#a6e3a1"),
            (self._ax_p, "P (W)",     "#fab387"),
        ]:
            ax.set_facecolor("#181825")
            ax.set_ylabel(label, color="white", fontsize=8)
            ax.tick_params(colors="white", labelsize=7)
            for spine in ax.spines.values():
                spine.set_edgecolor("#45475a")

        layout = QVBoxLayout(self)
        layout.addWidget(self._canvas)

    def push(self, row: dict):
        self._v.append(row["v_rms"])
        self._i.append(row["i_rms"])
        self._p.append(row["p_w"])
        n = len(self._v)
        self._t = list(range(n))

        for ax, data, color in [
            (self._ax_v, self._v, "#89b4fa"),
            (self._ax_i, self._i, "#a6e3a1"),
            (self._ax_p, self._p, "#fab387"),
        ]:
            ax.cla()
            ax.set_facecolor("#181825")
            ax.plot(self._t, list(data), color=color, linewidth=1.2)
            ax.tick_params(colors="white", labelsize=7)
            for spine in ax.spines.values():
                spine.set_edgecolor("#45475a")

        labels = ["Vrms (V)", "Irms (A)", "P (W)"]
        for ax, label in zip([self._ax_v, self._ax_i, self._ax_p], labels):
            ax.set_ylabel(label, color="white", fontsize=8)

        self._ax_p.set_xlabel("samples (1 Hz)", color="white", fontsize=8)
        self._fig.tight_layout(pad=2.0)
        self._canvas.draw()


# ── Value label helper ────────────────────────────────────────────────────────
def make_value_label(value="—", unit=""):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    val_lbl = QLabel(value)
    val_lbl.setFont(QFont("Consolas", 18, QFont.Bold))
    val_lbl.setStyleSheet("color: #cdd6f4;")
    unit_lbl = QLabel(unit)
    unit_lbl.setFont(QFont("Segoe UI", 10))
    unit_lbl.setStyleSheet("color: #6c7086;")
    unit_lbl.setAlignment(Qt.AlignBottom)
    h.addWidget(val_lbl)
    h.addWidget(unit_lbl)
    h.addStretch()
    return w, val_lbl


def make_tile(title: str, value="—", unit="") -> tuple:
    box = QGroupBox(title)
    box.setStyleSheet("""
        QGroupBox {
            font: 9pt 'Segoe UI';
            color: #6c7086;
            border: 1px solid #313244;
            border-radius: 6px;
            margin-top: 8px;
            padding: 6px 10px 6px 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
        }
    """)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(8, 4, 8, 8)
    w, lbl = make_value_label(value, unit)
    layout.addWidget(w)
    return box, lbl


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sensor Node 1 — Energy Monitor")
        self.setMinimumWidth(680)
        self.setStyleSheet("background-color: #1e1e2e; color: #cdd6f4;")

        self._logger      = Logger()
        self._plot_window = None
        self._relay_on    = False

        self._build_ui()

        self._worker = BleWorker()
        self._worker.measurement.connect(self._on_measurement)
        self._worker.relay_state.connect(self._on_relay_state)
        self._worker.connected.connect(self._on_connected)
        self._worker.start()

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        # Title
        title = QLabel("Sensor Node 1 — Energy Monitor")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet("color: #89b4fa; padding-bottom: 4px;")
        root.addWidget(title)

        # ── Measurement grid ──────────────────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(8)

        def add_tile(row, col, label, unit):
            tile, lbl = make_tile(label, "—", unit)
            grid.addWidget(tile, row, col)
            return lbl

        self._lbl_vrms  = add_tile(0, 0, "Vrms",      "V")
        self._lbl_s     = add_tile(0, 1, "S — Apparent Power", "VA")
        self._lbl_irms  = add_tile(1, 0, "Irms",      "A")
        self._lbl_p     = add_tile(1, 1, "P — Active Power",   "W")
        self._lbl_freq  = add_tile(2, 0, "Frequency", "Hz")
        self._lbl_q     = add_tile(2, 1, "Q — Reactive Power", "VAr")
        self._lbl_pf    = add_tile(3, 1, "Power Factor",       "")

        root.addLayout(grid)

        # ── Environmental + relay row ─────────────────────────────────────────
        env_relay = QHBoxLayout()
        env_relay.setSpacing(8)

        temp_box, self._lbl_temp   = make_tile("Temperature", "—", "°C")
        humid_box, self._lbl_humid = make_tile("Humidity",    "—", "%")
        env_relay.addWidget(temp_box, 1)
        env_relay.addWidget(humid_box, 1)

        relay_box = QGroupBox("Relay")
        relay_box.setStyleSheet("""
            QGroupBox {
                font: 9pt 'Segoe UI'; color: #6c7086;
                border: 1px solid #313244; border-radius: 6px;
                margin-top: 8px; padding: 6px 10px 6px 10px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        """)
        relay_inner = QHBoxLayout(relay_box)
        relay_inner.setSpacing(8)

        self._relay_indicator = QLabel("OFF")
        self._relay_indicator.setFont(QFont("Consolas", 14, QFont.Bold))
        self._relay_indicator.setStyleSheet("color: #6c7086; min-width: 40px;")

        btn_on  = self._make_btn("ON",     "#a6e3a1", "#1e1e2e", lambda: self._worker.send_relay("on"))
        btn_off = self._make_btn("OFF",    "#f38ba8", "#1e1e2e", lambda: self._worker.send_relay("off"))
        btn_tog = self._make_btn("TOGGLE", "#fab387", "#1e1e2e", lambda: self._worker.send_relay("toggle"))

        relay_inner.addWidget(self._relay_indicator)
        relay_inner.addWidget(btn_on)
        relay_inner.addWidget(btn_off)
        relay_inner.addWidget(btn_tog)
        env_relay.addWidget(relay_box, 2)

        root.addLayout(env_relay)

        # ── Bottom controls ───────────────────────────────────────────────────
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self._btn_log_start = self._make_btn("Start Logging", "#a6e3a1", "#1e1e2e", self._start_logging)
        self._btn_log_stop  = self._make_btn("Stop Logging",  "#f38ba8", "#1e1e2e", self._stop_logging)
        self._btn_log_stop.setEnabled(False)
        btn_plot = self._make_btn("Show Plots", "#89b4fa", "#1e1e2e", self._show_plots)

        controls.addWidget(self._btn_log_start)
        controls.addWidget(self._btn_log_stop)
        controls.addStretch()
        controls.addWidget(btn_plot)
        root.addLayout(controls)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status = QStatusBar()
        self._status.setStyleSheet("color: #6c7086; font: 9pt 'Segoe UI';")
        self.setStatusBar(self._status)
        self._status.showMessage("Connecting…")

    def _make_btn(self, text, bg, fg, slot):
        btn = QPushButton(text)
        btn.setFont(QFont("Segoe UI", 9))
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg}; color: {fg};
                border: none; border-radius: 5px;
                padding: 6px 14px;
            }}
            QPushButton:hover   {{ opacity: 0.85; }}
            QPushButton:disabled {{ background-color: #313244; color: #45475a; }}
        """)
        btn.clicked.connect(slot)
        return btn

    # ── Slots ─────────────────────────────────────────────────────────────────
    @pyqtSlot(dict)
    def _on_measurement(self, row: dict):
        self._lbl_vrms.setText(f"{row['v_rms']:.2f}")
        self._lbl_irms.setText(f"{row['i_rms']:.3f}")
        self._lbl_p.setText(f"{row['p_w']:.2f}")
        self._lbl_s.setText(f"{row['s_va']:.2f}")
        self._lbl_q.setText(f"{row['q_var']:.2f}")
        self._lbl_pf.setText(f"{row['pf']:.3f}")
        self._lbl_freq.setText(f"{row['freq']:.2f}")
        self._lbl_temp.setText(f"{row['temp']:.2f}")
        self._lbl_humid.setText(f"{row['humid']:.2f}")

        self._logger.write(row)

        if self._plot_window and self._plot_window.isVisible():
            self._plot_window.push(row)

        self._update_status()

    @pyqtSlot(bool)
    def _on_relay_state(self, on: bool):
        self._relay_on = on
        self._relay_indicator.setText("ON" if on else "OFF")
        self._relay_indicator.setStyleSheet(
            "color: #a6e3a1; min-width: 40px;" if on
            else "color: #6c7086; min-width: 40px;"
        )

    @pyqtSlot(bool)
    def _on_connected(self, connected: bool):
        self._update_status(connected=connected)

    def _update_status(self, connected: bool = True):
        conn_str = "Connected" if connected else "Disconnected"
        log_str  = "Logging active" if self._logger.is_active else "Not logging"
        self._status.showMessage(f"{conn_str}  |  {log_str}")

    def _start_logging(self):
        path = self._logger.start()
        self._btn_log_start.setEnabled(False)
        self._btn_log_stop.setEnabled(True)
        self._update_status()

    def _stop_logging(self):
        self._logger.stop()
        self._btn_log_start.setEnabled(True)
        self._btn_log_stop.setEnabled(False)
        self._update_status()

    def _show_plots(self):
        if self._plot_window is None:
            self._plot_window = PlotWindow(self)
        self._plot_window.show()
        self._plot_window.raise_()

    def closeEvent(self, event):
        self._logger.stop()
        self._worker.terminate()
        event.accept()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
    