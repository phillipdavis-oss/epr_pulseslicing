import asyncio
import functools
import inspect
import sys
from pathlib import Path
import serial
import DG645
import numpy as np
from cniAPI import hex_sequence, make_connection, send_receive_cni
from constants import FLASHES, MINCURR
from laser_timing import Ui_MainWindow
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QTextBrowser,
    QTextEdit,
)
from serial.tools.list_ports import comports
from vironAPI import create_reader_writer, login_command, send_receive


def bool_to_code(b: bool) -> str:  # noqa: FBT001 ignore the positional boolean
    return "I" if b else "E"


def code_to_bool(c: str) -> bool:
    return c == "I"


class LaserGUI(QMainWindow, Ui_MainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.lasers = {"v1": {}, "v2": {}, "c1": {}, "c2": {}, "c3": {}, "c4": {}, "c5": {}}
        # lasers = [v for v in self.ui.__dict__.values() if '_enabled' in v.objectName()]
        for l in self.lasers:  # noqa: E741
            ll = self.ui.__dict__[l + "_enabled"]
            ll.clicked.connect(self.enable)
            ll = self.ui.__dict__[l + "_init"]
            ll.clicked.connect(self.initialize_handler)
            ll = self.ui.__dict__[l + "_power"]
            ll.sliderReleased.connect(self.set_power)
            ld = self.ui.__dict__[l + "_trig_diode"]
            ld.clicked.connect(self.set_trigger)
            ld.clicked.connect(self.set_timings)

            lq = self.ui.__dict__[l + "_trig_qs"]
            lq.clicked.connect(self.set_trigger)
            lq.clicked.connect(self.set_timings)
            self.lasers[l]["trig"] = bool_to_code(ld.isChecked()) + bool_to_code(lq.isChecked())

            ll = self.ui.__dict__[l + "_timing_diode"]
            ll.valueChanged.connect(self.set_timings)
            ll = self.ui.__dict__[l + "_timing_qs"]
            ll.valueChanged.connect(self.set_timings)

            if l.startswith("c"):
                ll = self.ui.__dict__[l + "_com"]
                for port in comports():
                    ll.addItem(port.device.split("-")[0].strip())

        # double_spin_boxes = self.findChildren(QDoubleSpinBox)
        # for box in double_spin_boxes:
        #     # Use QLocale to set scientific notation for large and small numbers
        #     locale = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        #     box.setLocale(locale)

        ll = self.ui.__dict__["save_settings"]
        ll.clicked.connect(self.save_settings)
        QApplication.instance().aboutToQuit.connect(self.save_settings)
        QApplication.instance().aboutToQuit.connect(self.close_connections)
        # want to run the save settings to device .ini when app is closed so that if it is reopened it will have the same settings

        ll = self.ui.__dict__["load_settings"]
        ll.clicked.connect(self.load_settings)
        ll = self.ui.__dict__["unlock_connections"]
        ll.clicked.connect(self.unlock_connections)

        ll = self.ui.__dict__["file_browser"]
        ll.clicked.connect(self.open_file_dialog)

        self.file_path_input = self.ui.__dict__["savepath"]

        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        # Ensure an event loop is created if one does not exist
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self.toggle_button_color)

        self.status_text = ""
        self.status_bar = self.findChildren(QTextBrowser, "status")[0]

        times = self.ui.__dict__["send_times"]
        times.clicked.connect(self.send_times)

        self.settings_config = QSettings("SherwinLab", "LaserControlApp")
        self.load_settings()

        self.make_laser_dict()

    def send_times(self) -> None:
        d = self.sender()
        self.loop.run_until_complete(self.send_times_device(d))

    async def send_times_device(self, l) -> None:
        if (
            not hasattr(self, "delay_gen")
            or self.delay_gen["reader"] is None
            or self.delay_gen["writer"] is None
        ):
            reader, writer, resp = await DG645.connect(ip="192.168.103.164", port="5025")
            self.delay_gen = {}
            self.delay_gen["reader"], self.delay_gen["writer"] = reader, writer
            self.status_update(resp)

        if self.delay_gen["reader"] is not None and self.delay_gen["writer"] is not None:
            cnis = [ll for ll in self.lasers if ll.startswith("c")]
            cni_diodes = [self.ui.__dict__[ll + "_timing_diode"].value() for ll in cnis]
            cni_qs = [self.ui.__dict__[ll + "_timing_qs"].value() for ll in cnis]

            virons = [ll for ll in self.lasers if ll.startswith("v")]
            viron_diodes = [self.ui.__dict__[ll + "_timing_diode"].value() for ll in virons]
            viron_qs = [self.ui.__dict__[ll + "_timing_qs"].value() for ll in virons]

            t0 = self.ui.__dict__["overall_timing"].value() * 1e3  # convert to ns
            A, B = t0, t0

            for laser in self.lasers:
                self.ui.__dict__[laser + "_timing_diode"].blockSignals(True)
                self.ui.__dict__[laser + "_timing_qs"].blockSignals(True)
                # block these as their values are about to change

            if all(
                np.diff(cni_diodes) < 1000,
            ):  # want to make sure they aren't sent too far apart -- within 1 ns all of them
                A = t0 + np.mean(cni_diodes)
                for laser in cnis:
                    self.ui.__dict__[laser + "_timing_diode"].setValue(np.mean(cni_diodes))
            else:
                self.status_update("CNI diode trigger values are too far apart (<1 us required).")

            if all(np.diff(viron_diodes) < 1000):
                B = t0 + np.mean(viron_diodes)
                for laser in virons:
                    self.ui.__dict__[laser + "_timing_diode"].setValue(np.mean(viron_diodes))
            else:
                self.status_update(
                    "Viron diode trigger values are too far apart (<1 us required).",
                )

            for laser in self.lasers:
                self.ui.__dict__[laser + "_timing_diode"].blockSignals(False)
                self.ui.__dict__[laser + "_timing_qs"].blockSignals(False)

            # TODO this needs to be a QLineEdit with some numpy float validation
            C = self.ui.__dict__["c1_timing_qs"].value()
            D = self.ui.__dict__["c2_timing_qs"].value()
            E = self.ui.__dict__["c3_timing_qs"].value()
            F = self.ui.__dict__["c4_timing_qs"].value()
            X = self.ui.__dict__["c5_timing_qs"].value()

            G = self.ui.__dict__["v1_timing_qs"].value()
            H = self.ui.__dict__["v2_timing_qs"].value()

            outstr = ""
            for ind, chan in enumerate([A, B, C, D, E, F, G, H]):
                outstr += await DG645.send_receive(
                    self.delay_gen["reader"],
                    self.delay_gen["writer"],
                    f"DLAY {ind},0,{chan * 1e-6:f}\n",
                )
                # outstr += await DG645.send_receive(self.sock, f"LINK {ind},0\n".encode("utf-8"))
                # outstr += await DG645.send_receive(self.sock, f"DISP 11,{ind}\n".encode("utf-8"))

            # outstr += await DG645.send_receive(self.sock, f"TSRC 1\n".encode("utf-8")) # trigger externally with rising edge
            # outstr += await DG645.send_receive(self.sock, f"HOLD 1e-3\n".encode("utf-8")) # holdoff 1 ms to account for some noise if there is any
            # outstr += await DG645.send_receive(self.sock, f"DISP 11,{2}\n".encode("utf-8"))

            self.status_update(outstr)
        else:
            self.status_update("Digitizer socket connection failed.\n")

    def open_file_dialog(self) -> None:
        # options = QFileDialog.Option.DontUseNativeDialog
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "*.ini")
        if file_path:
            self.file_path_input.setText(file_path)

    def unlock_connections(self) -> None:
        connections = [
            ii for ii in self.findChildren(QTextEdit) if ii.objectName().endswith(("_ip", "_mac"))
        ]
        connections += [
            ii for ii in self.findChildren(QComboBox) if ii.objectName().endswith("_com")
        ]
        for conn in connections:
            conn.setEnabled(not conn.isEnabled())
            if not conn.isEnabled():
                self.make_laser_dict()
            self.sender().setText(
                "Lock connection settings" if conn.isEnabled() else "Unlock connection settings",
            )
            self.sender().setStyleSheet(
                "QPushButton {\n"
                "    background-color:rgb(170, 255, 127);  /* orange background */\n"
                "    padding: 0px 0px;         /* Padding */\n"
                "    border-radius: 3px;        /* Rounded corners */\n"
                "    border: .5px solid gray;\n"
                "    color: black;\n"
                "}\n"
                "\n"
                "QPushButton:hover {\n"
                "    background-color:rgb(150, 255, 107);  /* Darker green on hover */\n"
                "}\n"
                "\n"
                "QPushButton:pressed {\n"
                "    background-color:rgb(130, 255, 87);  /* Even darker green when pressed */\n"
                "}\n"
                ""
                if conn.isEnabled()
                else "QPushButton {\n"
                "    background-color: rgb(255, 170, 0);  /* orange background */\n"
                "    padding: 0px 0px;         /* Padding */\n"
                "    border-radius: 3px;        /* Rounded corners */\n"
                "    border: .5px solid gray;\n"
                "    color: black;\n"
                "}\n"
                "\n"
                "QPushButton:hover {\n"
                "    background-color:rgb(255, 150, 0);  /* Darker green on hover */\n"
                "}\n"
                "\n"
                "QPushButton:pressed {\n"
                "    background-color: rgb(255, 130, 0);  /* Even darker green when pressed */\n"
                "}\n"
                "",
            )

    def not_initialized_handler(func) -> object:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            l = self.get_laser_name(self.sender())
            try:
                if inspect.iscoroutinefunction(func):
                    resp = await func(self, *args, **kwargs)
                else:
                    resp = func(self, *args, **kwargs)
            except (KeyError, serial.SerialException):
                self.initialize_button = self.findChildren(QPushButton, f"{l}_init")[0]
                self.flash_count = 0
                self.flash_timer.start(100)
                resp = f"{l}: Laser not initialized.\n"
            finally:
                if type(resp) != bytes:
                    self.status_update(resp)
                return resp

        return wrapper

    def get_laser_name(self, sender: object) -> str:
        return sender.objectName().split("_")[
            0
        ]  # relies on naming convention <laser><number>_<action>

    def make_laser_dict(self) -> None:
        lasers = [
            self.get_laser_name(ii)
            for ii in self.findChildren(QPushButton)
            if "_enabled" in ii.objectName()
        ]
        widgets = self.findChildren(QTextEdit)
        for laser in lasers:
            if laser.startswith("v"):
                ip = next(ii.toPlainText() for ii in widgets if ii.objectName() == laser + "_ip")
                host, port = ip.split(":")
                mac = next(ii.toPlainText() for ii in widgets if ii.objectName() == laser + "_mac")
                self.lasers[laser]["HOST"] = host
                self.lasers[laser]["PORT"] = port
                self.lasers[laser]["MAC"] = mac

    def enable(self) -> None:
        l = self.get_laser_name(self.sender())  # noqa: E741
        self.loop.run_until_complete(self.enable_laser(l))

    async def enable_laser(self, l) -> None:
        if l.startswith("v"):
            await self.send_receive_laser(
                l,
                "$FIRE\n" if self.sender().text() == "Fire" else "$STANDBY\n",
            )

        elif l.startswith("c"):
            data = bytearray([0x7F, 5, 0x21, self.sender().text() == "Fire", 0, 0, 0])  # Test data
            outstr = await self.send_receive_laser(l, data)
            if outstr is not None:  # only do this if serialException is not raised
                en = int(hex_sequence(outstr).split(" ")[3])
                resp = f"{l}: {'Enabled' if en else 'Disabled'}.\n"

        self.sender().setText("Disable" if self.sender().text() == "Fire" else "Fire")

        if "resp" in locals():
            self.status_update(resp)

    def initialize_handler(self, *args, **kwargs) -> None:
        self.loop.run_until_complete(self.initialize(*args, **kwargs))

    async def initialize(self, *args, **kwargs) -> None:
        l = self.get_laser_name(self.sender())  # noqa: E741
        if l.startswith("v"):
            if self.sender().isChecked():
                await self.init_laser(l)
                await self.set_power_laser(l)
                await self.set_trigger_laser(l)
            else:
                await self.send_receive_laser(l, "$STOP\n")
        elif l.startswith("c"):
            if self.sender().isChecked():
                await self.init_laser(l)
                await self.set_power_laser(l)
                await self.set_trigger_laser(l)
            else:
                try:
                    self.lasers[l]["serial"].close()
                    del self.lasers[l]["serial"]
                except KeyError:
                    pass

    def set_power(self, l=None) -> None:
        if l is None:
            l = self.get_laser_name(self.sender())  # noqa: E741
        self.loop.run_until_complete(self.set_power_laser(l))

    @not_initialized_handler  # in case maxcurr is not defined
    async def set_power_laser(self, l=None) -> None:
        if l.startswith("v"):
            return await self.send_receive_laser(
                l,
                f"$DCURR {MINCURR + (self.lasers[l]['maxcurr'] - MINCURR) / 100 * self.ui.__dict__[l + '_power'].value()}\n",
            )
        if l.startswith("c"):
            gears = np.array([5, 10, 20, 30, 50, 60, 80, 100])
            setting = self.ui.__dict__[l + "_power"].value()
            diff = np.abs(gears - setting)
            gear = np.argmin(diff)  # gear id is 0,1,..,6
            self.ui.__dict__[l + "_power"].setValue(gears[gear])

            data = bytearray([0x7F, 5, 0x23, gear, 0, 0, 0])  # Test data

            # outstr = self.loop.run_until_complete(send_receive_cni(
            #     self.lasers[l]["serial"], data
            # ))
            outstr = await self.send_receive_laser(l, data)
            if outstr is not None:  # only do this if serialException is not raised
                gear = int(hex_sequence(outstr).split(" ")[3])
                resp = f"{l}: Power set to {gears[gear]}%.\n"

            return resp

    def set_trigger(self, *args, **kwargs) -> None:
        l = self.get_laser_name(self.sender())  # noqa: E741
        self.loop.run_until_complete(self.set_trigger_laser(l))

    async def set_trigger_laser(self, l=None) -> None:
        if l is None:
            l = self.get_laser_name(self.sender())  # noqa: E741

        if "_trig_" in self.sender().objectName():
            trig_button = self.sender()
        else:  # need to handle auto-send from init
            trig_button = self.ui.__dict__[l + "_trig_qs"]

        trigger_buttons = [
            ii for ii in self.findChildren(QPushButton) if f"{l}_trig_" in ii.objectName()
        ]

        other = next(
            ii for ii in trigger_buttons if trig_button.objectName() not in ii.objectName()
        )
        trig = ""

        if l.startswith("v"):
            if "reader" in self.lasers[l] or "writer" in self.lasers[l]:
                # checked means interal, unchecked (default) means external
                trig = bool_to_code(
                    self.ui.__dict__[l + "_trig_diode"].isChecked(),
                ) + bool_to_code(self.ui.__dict__[l + "_trig_qs"].isChecked())

                if trig == "IE":
                    # IE is forbidden, can't trigger internal then external -- that would be non-causal
                    if "_trig_" in self.sender().objectName():
                        trig = bool_to_code(trig_button.isChecked()) + bool_to_code(
                            trig_button.isChecked(),
                        )
                        other.setChecked(trig_button.isChecked())
                    else:  # just default to EE in case it is screwed up on init
                        trig = "EE"

                self.lasers[l]["trig"] = trig
            elif "_trig_" in self.sender().objectName():
                self.sender().setChecked(not self.sender().isChecked())

            await self.send_receive_laser(
                l,
                f"$TRIG {trig}\n",
            )  # this will handle non-connected errors

        elif l.startswith("c"):
            trig = int(not trig_button.isChecked())  # want 0x01 if unchecked, 0x00 if checked

            data = bytearray([0x7F, 5, 0x01, trig, 0, 0, 0])
            outstr = await self.send_receive_laser(l, data)

            if outstr is not None:  # only do this if serialException is not raised
                other.setChecked(trig_button.isChecked())

                int_trig = bool(int(hex_sequence(outstr).split(" ")[3]))
                self.lasers[l]["trig"] = "II" if not int_trig else "EE"

                resp = f"{l}: Trigger set to {'Internal' if not int_trig else 'External'}.\n"
            elif "_trig_" in self.sender().objectName():
                self.sender().setChecked(
                    not self.sender().isChecked(),
                )  # if sent here by a trigger button but there is an error, flip it

            if "resp" in locals():
                self.status_update(resp)

        for button in [trig_button, other]:
            button.setText("Internal" if button.isChecked() else "External")

    def set_timings(self, *args, **kwargs) -> None:
        l = self.get_laser_name(self.sender())  # noqa: E741
        if l.startswith("v"):
            self.loop.run_until_complete(self.set_timings_laser(l))
        if l.startswith("c"):
            self.loop.run_until_complete(self.set_timings_laser(l))

    def save_settings(self):
        self.loop.run_until_complete(self.save_settings_laser())

    async def save_settings_laser(self):
        def save_widgets(settings):
            for child in buttons:
                if not any([child.objectName().endswith(ii) for ii in skipped_names]):
                    settings.setValue(f"{child.objectName()}", child.isChecked())

            for child in timings:
                if not any([child.objectName().endswith(ii) for ii in skipped_names]):
                    settings.setValue(f"{child.objectName()}", child.value())
                    settings.setValue(f"{child.objectName()}_enabled", child.isEnabled())

            for child in inputs:
                if not any([child.objectName().endswith(ii) for ii in skipped_names]):
                    settings.setValue(f"{child.objectName()}", child.toPlainText())
                    settings.setValue(f"{child.objectName()}_enabled", child.isEnabled())

            for child in dropdowns:
                if not any([child.objectName().endswith(ii) for ii in skipped_names]):
                    settings.setValue(f"{child.objectName()}", child.currentText())

            for child in sliders:
                if not any([child.objectName().endswith(ii) for ii in skipped_names]):
                    settings.setValue(f"{child.objectName()}", child.value())

        buttons = self.findChildren(QPushButton)
        timings = self.findChildren(QDoubleSpinBox)
        inputs = self.findChildren(QTextEdit)
        dropdowns = self.findChildren(QComboBox)
        sliders = self.findChildren(QSlider)
        # children = set(buttons + timings + inputs + dropdowns)
        skipped_names = set(
            ["status", "_enabled", "_settings", "unlock_connections", "_init", "send_times"],
        )  # all the stuff that doesn't need to be saved

        if not isinstance(self.sender(), QApplication):
            path = Path(self.file_path_input.toPlainText())
            if Path(path).parent.exists() and Path(path).suffix == ".ini":
                save = False
                if Path(path).exists():
                    response = QMessageBox.warning(
                        self,
                        "File Overwrite Warning",
                        f"The file {path} already exists. Do you want to overwrite it?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )

                    if response == QMessageBox.StandardButton.Yes:
                        save = True
                    else:
                        resp = "File save cancelled.\n"
                else:
                    save = True

                if save:
                    settings = QSettings(str(path), QSettings.Format.IniFormat)

                    save_widgets(settings)
                    settings.sync()

                    resp = f"Saved succesfully to {path.name}.\n"
            else:
                resp = "'.ini' path error.\n"

            self.status_update(resp)

        save_widgets(self.settings_config)
        self.settings_config.sync()

    def load_settings(self):
        # self.loop.run_until_complete(self.load_settings_laser)
        self.load_settings_laser()

    def load_settings_laser(self):
        settings = None
        if self.sender() is not None:
            path = Path(self.file_path_input.toPlainText())
            if Path(path).parent.exists() and Path(path).suffix == ".ini":
                settings = QSettings(str(path), QSettings.Format.IniFormat)
                loadfrom = path.name
                resp = f"Loaded from {loadfrom}.\n"
            else:
                resp = "'.ini' path error.\n"
        else:
            settings = self.settings_config  # handle for initial opening of the gui
            loadfrom = "previous"
            resp = f"Loaded from {loadfrom}.\n"

        if settings is not None:
            for setting in settings.allKeys():
                if not setting.endswith(
                    "_enabled",
                ):  # skip the buttons 'enabled' settings since they do not correspond to a real widget
                    try:
                        widget = self.ui.__dict__[setting]
                        widget.blockSignals(True)
                        if "_timing" in setting and not setting.endswith("_enabled"):
                            # this is the timing valuebox
                            # will also have sister value for enable
                            widget.setValue(float(settings.value(setting)))
                            widget.setEnabled(settings.value(setting + "_enabled") == "true")
                        elif setting.endswith("_power"):
                            widget.setValue(int(settings.value(setting)))
                        elif "_trig_" in setting:
                            widget.setChecked(settings.value(setting) == "true")
                            widget.setText(
                                "Internal" if settings.value(setting) == "true" else "External",
                            )
                        elif setting.endswith("_ip") or setting.endswith("_mac"):
                            widget.setText(settings.value(setting))
                        elif setting.endswith("_com"):
                            widget.setCurrentText(settings.value(setting))
                        elif setting == "savepath":
                            widget.setText(settings.value(setting))
                        widget.blockSignals(False)
                    except KeyError:
                        pass

        self.status_update(resp)

    # @not_initialized_handler
    async def set_timings_laser(self, laser) -> None:
        timing_inputs = [
            ii for ii in self.findChildren(QDoubleSpinBox) if f"{laser}_timing" in ii.objectName()
        ]
        timing_inputs.sort(key=lambda x: x.objectName())
        for ind, timing_input in enumerate(timing_inputs):
            # should be sorted to have diode then input
            # want the timing input to be disabled if it is fixed by internal triggering
            # signalling is blocked to not double-trigger
            timing_input.blockSignals(True)

            self.lasers[laser]["qsdelay"] = (
                179 if laser.startswith("v") else 244
            )  # us, hard coded 179 for viron, 244 for cni

            if bool(ind):  # only change QS enabled/disabled
                timing_input.setEnabled(self.lasers[laser]["trig"][ind] == "E")
            else:
                timing_input.setEnabled(False)

            if self.lasers[laser]["trig"] == "EE":
                if timing_input.objectName().endswith("qs"):
                    timing_input.setValue(timing_inputs[1].value())

                elif timing_input.objectName().endswith("diode"):
                    timing_input.setValue(timing_inputs[1].value() - self.lasers[laser]["qsdelay"])

            timing_input.blockSignals(False)

        self.status_update(
            f"{laser}: Timing values set to FL={timing_inputs[0].value()}ns and QS={timing_inputs[1].value()}ns.\n",
        )

    # @not_initialized_handler
    async def init_laser(self, laser: str) -> None:
        status_text = ""
        try:
            # if True:
            if laser.startswith("v"):
                if not ("reader" in self.lasers[laser] or "writer" in self.lasers[laser]):
                    reader, writer, resp = await create_reader_writer(
                        host=self.lasers[laser]["HOST"],
                        port=self.lasers[laser]["PORT"],
                        mac=self.lasers[laser]["MAC"],
                    )
                    status_text += f"{laser}: {resp}\n"
                    resp = await send_receive(
                        reader,
                        writer,
                        login_command(self.lasers[laser]["MAC"]),
                    )
                    status_text += f"{laser}: {resp}\n"
                    maxcurr = await send_receive(reader, writer, "$MAXCURR ?\n")
                    qsdelay = await send_receive(reader, writer, "$QSDELAY ?\n")
                    self.lasers[laser]["reader"] = reader
                    self.lasers[laser]["writer"] = writer
                    self.lasers[laser]["maxcurr"] = float(
                        maxcurr.replace("\r", "").replace("\x00", "").split(" ")[1],
                    )
                    self.lasers[laser]["qsdelay"] = (
                        float(qsdelay.replace("\r", "").replace("\x00", "").split(" ")[1]) * 1000
                    )  # switch qsdelay to ns from us
                    status_text += f"{laser}: {maxcurr}\n"
                    status_text += f"{laser}: {qsdelay}\n"

                if "reader" in self.lasers[laser] and "writer" in self.lasers[laser]:
                    resp = await send_receive(
                        self.lasers[laser]["reader"],
                        self.lasers[laser]["writer"],
                        "$STANDBY\n",
                    )
                    self.sender().setText("Standby")

                status_text += f"{laser}: {resp}\n"
            elif laser.startswith("c"):
                if "serial" not in self.lasers[laser]:
                    self.lasers[laser]["serial"] = await make_connection(
                        self.ui.__dict__[laser + "_com"].currentText(),
                    )
                    if self.lasers[laser]["serial"].is_open:
                        data = bytearray([0x5D, 0x01, 0x01])  # Test data
                        outstr = await send_receive_cni(self.lasers[laser]["serial"], data)
                        if "DPS" in repr(outstr):  # check if communicating correctly
                            self.status_update(f"{laser}: Initialized.\n")

        except (AttributeError, serial.SerialException):  # no writer/reader
            self.sender().setText("Initialize")
            self.sender().setChecked(False)
            status_text += f"{laser}: Could not initialize (power off or wrong COM?)\n"
            raise KeyError  # raise error to trigger decorator handling
        finally:
            return status_text
            # return status_text

    @not_initialized_handler
    async def send_receive_laser(self, laser: str, command: str | bytearray) -> str | bytes:
        if laser.startswith("v"):
            resp = await send_receive(
                self.lasers[laser]["reader"],
                self.lasers[laser]["writer"],
                command,
            )
            return f"{laser}: {resp}\n"
        if laser.startswith("c"):
            resp = await send_receive_cni(self.lasers[laser]["serial"], command)
            return resp
            # return f"{laser}: {repr(resp)}\n"
            # raise Exception("Telnet send-receive is sent to {laser}, which has a serial-based communication protocol.")

    def toggle_button_color(self) -> None:
        self.initialize_button.setStyleSheet(
            "background-color: red" if self.flash_count % 2 else "",
        )

        self.flash_count += 1

        if self.flash_count >= FLASHES:
            self.flash_timer.stop()
            self.initialize_button.setStyleSheet("")

    def scroll_to_top(self):
        # Create a cursor at the end of the document and move the cursor there
        cursor = self.status_bar.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.status_bar.setTextCursor(cursor)

    def status_update(self, resp):
        self.status_text = resp + self.status_text
        self.status_bar.setText(self.status_text)
        self.scroll_to_top()

    def close_connections(self):
        self.loop.run_until_complete(self.close_connections_devices())

    async def close_connections_devices(self):
        for laser in self.lasers:
            if "serial" in self.lasers[laser]:
                if self.lasers[laser]["serial"].is_open:
                    self.lasers[laser]["serial"].close()
            elif "writer" in self.lasers[laser]:
                self.lasers[laser].close()
                await self.lasers[laser].wait_closed()
        if hasattr(self, "sock"):
            DG645.close(self.sock)


def main() -> None:
    app = QApplication(sys.argv)
    window = LaserGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
