from PyQt5.QtCore import pyqtSignal, QTimer

from mytools.measurewidget import MeasureWidget, MeasureTask, CancelToken
from util.file import remove_if_exists


class MeasureWidgetWithSecondaryParameters(MeasureWidget):
    secondaryChanged = pyqtSignal(dict)

    def __init__(self, parent=None, controller=None):
        super().__init__(parent=parent, controller=controller)

        self._uiDebouncer = QTimer()
        self._uiDebouncer.setSingleShot(True)
        self._uiDebouncer.timeout.connect(self.on_debounced_gui)

        self._params = 0

        self._paramInputWidget.createWidgets(
            params={
                'Plo': [
                    'Pгет=',
                    {'parent': self, 'start': -30.0, 'end': 30.0, 'step': 1.0, 'value': -5.0, 'suffix': ' дБм'}
                ],
                'Pmod': [
                    'Pмод=',
                    {'parent': self, 'start': -30.0, 'end': 30.0, 'step': 1.0, 'value': -5.0, 'suffix': ' дБм'}
                ],
                'Flo_min': [
                    'Fгет.мин=',
                    {'parent': self, 'start': 0.0, 'end': 40.0, 'step': 1.0, 'decimals': 3, 'value': 0.6, 'suffix': ' ГГц'}
                ],
                'Flo_max': [
                    'Fгет.макс=',
                    {'parent': self, 'start': 0.0, 'end': 40.0, 'step': 1.0, 'decimals': 3, 'value': 6.6, 'suffix': ' ГГц'}
                ],
                'Flo_delta': [
                    'ΔFгет=',
                    {'parent': self, 'start': 0.0, 'end': 40.0, 'step': 0.1, 'decimals': 3, 'value': 1.0, 'suffix': ' ГГц'}
                ],
                'is_Flo_div2': [
                    '1/2 Fгет.',
                    {'parent': self, 'value': False}
                ],
                'Fmod_min': [
                    'Fмод.мин=',
                    {'parent': self, 'start': 0.0, 'end': 1000.0, 'step': 1.0, 'decimals': 3, 'value': 1.0, 'suffix': ' МГц'}
                ],
                'Fmod_max': [
                    'Fмод.макс=',
                    {'parent': self, 'start': 0.0, 'end': 1000.0, 'step': 1.0, 'decimals': 3, 'value': 501.0, 'suffix': ' МГц'}
                ],
                'Fmod_delta': [
                    'ΔFмод=',
                    {'parent': self, 'start': 0.0, 'end': 1000.0, 'step': 1.0, 'decimals': 3, 'value': 10.0, 'suffix': ' МГц'}
                ],
                'Uoffs': [
                    'Uсм=',
                    {'parent': self, 'start': 0.0, 'end': 1000.0, 'step': 1, 'decimals': 1, 'value': 250.0, 'suffix': ' мВ'}
                ],
                'Usrc': [
                    'Uпит.=',
                    {'parent': self, 'start': 4.75, 'end': 5.25, 'step': 0.25, 'value': 5.0, 'suffix': ' В'}
                ],
                'sa_rlev': [
                    'Ref. lev.=',
                    {'parent': self, 'start': -30.0, 'end': 30.0, 'step': 1.0, 'value': 10.0, 'suffix': ' дБ'}
                ],
                'sa_scale_y': [
                    'Scale y=',
                    {'parent': self, 'start': 0.0, 'end': 30.0, 'step': 1.0, 'value': 10.0, 'suffix': ' дБ'}
                ],
                'sa_span': [
                    'Span=',
                    {'parent': self, 'start': 0.0, 'end': 1000.0, 'step': 1.0, 'value': 10.0, 'suffix': ' МГц'}
                ],
                'sa_avg_state': [
                    'Avg.state=',
                    {'parent': self, 'value': False}
                ],
                'sa_avg_count': [
                    'Avg.count=',
                    {'parent': self, 'start': 0.0, 'end': 1000.0, 'step': 1.0, 'value': 16.0, 'suffix': ''}
                ],
                'sep_1': ['', {'parent': self, 'value': None}],
                'u_min': [
                    'Uмин.=',
                    {'parent': self, 'start': 0.0, 'end': 30.0, 'step': 0.05, 'value': 4.75, 'suffix': ' В'}
                ],
                'u_max': [
                    'Uмакс.=',
                    {'parent': self, 'start': 0.0, 'end': 30.0, 'step': 0.05, 'value': 5.25, 'suffix': ' В'}
                ],
                'u_delta': [
                    'ΔU=',
                    {'parent': self, 'start': 0.0, 'end': 30.0, 'step': 0.05, 'value': 0.05, 'suffix': ' В'}
                ],
            }
        )

    def _connectSignals(self):
        self._paramInputWidget.secondaryChanged.connect(self.on_params_changed)

    def check(self):
        print('subclass checking...')
        self._modeDuringCheck()
        self._threads.start(
            MeasureTask(
                self._controller.check,
                self.checkTaskComplete,
                self._token,
                [self._selectedDevice, self._params]
            ))

    def checkTaskComplete(self):
        res = super(MeasureWidgetWithSecondaryParameters, self).checkTaskComplete()
        if not res:
            self._token = CancelToken()
        return res

    def calibrate(self, what):
        print(f'calibrating {what}...')
        self._modeDuringMeasure()
        calibrations = {
            'LO': self._controller._calibrateLO,
            'RF': self._controller._calibrateRF,
            'Mod': self._controller._calibrateMod,
        }
        self._threads.start(
            MeasureTask(
                calibrations[what],
                self.calibrateTaskComplete,
                self._token,
                [self._selectedDevice, self._params]
            ))

    def calibrateTaskComplete(self):
        print('calibrate finished')
        self._modePreMeasure()
        self.calibrateFinished.emit()

    def measure(self):
        print('subclass measuring...')
        self._modeDuringMeasure()
        self._threads.start(
            MeasureTask(
                self._controller.measure,
                self.measureTaskComplete,
                self._token,
                [self._selectedDevice, self._params]
            ))

    def measureTaskComplete(self):
        res = super(MeasureWidgetWithSecondaryParameters, self).measureTaskComplete()
        if not res:
            self._token = CancelToken()
            self._modePreCheck()
        return res

    def cancel(self):
        if not self._token.cancelled:
            if self._threads.activeThreadCount() > 0:
                print('cancelling task')
            self._token.cancelled = True

    def on_params_changed(self):
        self.secondaryChanged.emit(self._paramInputWidget.params)

    def updateWidgets(self, params):
        self._paramInputWidget.updateWidgets(params)
        self._connectSignals()

    def on_debounced_gui(self):
        # remove_if_exists('cal_lo.ini')
        # remove_if_exists('cal_rf.ini')
        remove_if_exists('adjust.ini')
