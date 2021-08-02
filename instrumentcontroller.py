import ast
import time

import numpy as np

from collections import defaultdict
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal

from instr.instrumentfactory import mock_enabled, GeneratorFactory, SourceFactory, MultimeterFactory, AnalyzerFactory
from measureresult import MeasureResult
from secondaryparams import SecondaryParams
from util.file import load_ast_if_exists, pprint_to_file

GIGA = 1_000_000_000
MEGA = 1_000_000
KILO = 1_000
MILLI = 1 / 1_000


class InstrumentController(QObject):
    pointReady = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        addrs = load_ast_if_exists('instr.ini', default={
            'Анализатор': 'GPIB1::18::INSTR',
            'Источник': 'GPIB1::3::INSTR',
        })

        self.requiredInstruments = {
            'Анализатор': AnalyzerFactory(addrs['Анализатор']),
            'Источник': SourceFactory(addrs['Источник']),
        }

        self.deviceParams = {
            'ГУН': {
                'F': 1,
            },
        }

        self.secondaryParams = SecondaryParams(required={
            'u_src': [
                'Uп=',
                {'start': -10.0, 'end': 10.0, 'step': 0.5, 'value': 3.0, 'suffix': ' В'}
            ],
            'i_src_max': [
                'Iп.макс=',
                {'start': 0.0, 'end': 500.0, 'step': 1.0, 'value': 50.0, 'suffix': ' мА'}
            ],
            'u_vco_min': [
                'Uмин.=',
                {'start': -10.0, 'end': 10.0, 'step': 0.5, 'decimals': 2, 'value': 0.0, 'suffix': ' В'}
            ],
            'u_vco_max': [
                'Uмин.=',
                {'start': -10.0, 'end': 10.0, 'step': 0.5, 'decimals': 2, 'value': 10.0, 'suffix': ' В'}
            ],
            'u_vco_delta': [
                'ΔU=',
                {'start': -10.0, 'end': 10.0, 'step': 0.5, 'decimals': 2, 'value': 1.0, 'suffix': ' В'}
            ],
            'sa_center': [
                'Center=',
                {'start': 0.0, 'end': 30.0, 'step': 0.5, 'value': 1.0, 'suffix': ' ГГц'}
            ],
            'sa_span': [
                'Span=',
                {'start': 0.0, 'end': 30.0, 'step': 0.5, 'value': 1.0, 'suffix': ' ГГц'}
            ],
            'sa_rlev': [
                'Ref lev=',
                {'start': -30.0, 'end': 30.0, 'step': 1.0, 'value': 10.0, 'suffix': ' дБ'}
            ],
            'is_harm_relative': [
                'Отн.ур.гармоник',
                {'value': False}
            ],
            'is_u_src_drift': [
                'Дрейф от Uп',
                {'value': False}
            ],
            'u_src_drift': [
                'ΔUп',
                {'start': 0.0, 'end': 100.0, 'step': 1.0, 'value': 10.0, 'suffix': ' %'}
            ],
            'is_p_out_2': [
                'Выход 2',
                {'value': False}
            ],
        })
        self.secondaryParams.load_from_config('params.ini')

        self._calibrated_pows_lo = load_ast_if_exists('cal_lo.ini', default={})
        self._calibrated_pows_mod = load_ast_if_exists('cal_mod.ini', default={})
        self._calibrated_pows_rf = load_ast_if_exists('cal_rf.ini', default={})

        self._instruments = dict()
        self.found = False
        self.present = False
        self.hasResult = False
        self.only_main_states = False

        self.result = MeasureResult()

    def __str__(self):
        return f'{self._instruments}'

    # region connections
    def connect(self, addrs):
        print(f'searching for {addrs}')
        for k, v in addrs.items():
            self.requiredInstruments[k].addr = v
        self.found = self._find()

    def _find(self):
        self._instruments = {
            k: v.find() for k, v in self.requiredInstruments.items()
        }
        return all(self._instruments.values())

    def check(self, token, params):
        print(f'call check with {token} {params}')
        device, secondary = params
        self.present = self._check(token, device, secondary)
        print('sample pass')

    def _check(self, token, device, secondary):
        print(f'launch check with {self.deviceParams[device]} {self.secondaryParams}')
        self._init()
        return True
    # endregion

    # region calibrations
    def calibrate(self, token, params):
        print(f'call calibrate with {token} {params}')
        return self._calibrate(token, self.secondaryParams)

    def _calibrateLO(self, token, secondary):
        print('run calibrate LO with', secondary)
        result = {}
        self._calibrated_pows_lo = result
        return True

    def _calibrateRF(self, token, secondary):
        print('run calibrate RF')
        result = {}
        self._calibrated_pows_rf = result
        return True

    def _calibrateMod(self, token, secondary):
        print('calibrate mod gen')
        result = {}
        self._calibrated_pows_mod = result
        return True
    # endregion

    # region initialization
    def _clear(self):
        self.result.clear()

    def _init(self):
        self._instruments['Источник'].send('*RST')
        self._instruments['Анализатор'].send('*RST')
    # endregion

    def measure(self, token, params):
        print(f'call measure with {token} {params}')
        device, _ = params
        try:
            self.result.set_secondary_params(self.secondaryParams)
            self._measure(token, device)
            # self.hasResult = bool(self.result)
            self.hasResult = True  # HACK
        except RuntimeError as ex:
            print('runtime error:', ex)

    def _measure(self, token, device):
        param = self.deviceParams[device]
        secondary = self.secondaryParams.params
        print(f'launch measure with {token} {param} {secondary}')

        self._clear()
        _ = self._measure_s_params(token, param, secondary)
        return True

    def _measure_s_params(self, token, param, secondary):

        def set_read_marker(freq):
            sa.send(f':CALCulate:MARKer1:X {freq}Hz')
            if not mock_enabled:
                time.sleep(0.01)
            return float(sa.query(':CALCulate:MARKer:Y?'))

        src = self._instruments['Источник']
        sa = self._instruments['Анализатор']

        src_u = secondary['u_src']
        src_i_max = secondary['i_src_max'] * MILLI

        vco_u_min = secondary['u_vco_min']
        vco_u_max = secondary['u_vco_max']
        vco_u_delta = secondary['u_vco_delta']

        sa_center = secondary['sa_center'] * GIGA
        sa_span = secondary['sa_span'] * GIGA
        sa_rlev = secondary['sa_rlev'] * GIGA

        is_harm_relative = secondary['is_harm_relative']

        is_src_u_drift = secondary['is_u_src_drift']
        src_u_drift = secondary['u_src_drift']

        is_p_out_2 = secondary['is_p_out_2']

        vco_u_values = [
            round(x, 2) for x in
            np.arange(start=vco_u_min, stop=vco_u_max + 0.0002, step=vco_u_delta)
        ]

        # region main measure
        # TODO set source according to the source model
        src.send(f'APPLY p25v,{src_u}V,{src_i_max}A')
        src.send('OUTPut ON')

        sa.send(':CAL:AUTO OFF')
        sa.send(f':SENS:FREQ:SPAN {sa_span}')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV {sa_rlev}')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV 10')
        # sa.send(f'AVER:COUNT {sa_avg_count}')
        # sa.send(f'AVER {sa_avg_state}')
        sa.send(':CALC:MARK1:MODE POS')

        # TODO record sample data
        # if mock_enabled:
        #     with open('./mock_data/-5_1mhz.txt', mode='rt', encoding='utf-8') as f:
        #         index = 0
        #         mocked_raw_data = ast.literal_eval(''.join(f.readlines()))

        res = []
        for vco_u in vco_u_values:

            if token.cancelled:
                src.send('OUTPut OFF')
                sa.send(':CAL:AUTO ON')
                raise RuntimeError('measurement cancelled')

            # TODO implement calibrations if needed
            # lo_loss = self._calibrated_pows_lo.get(lo_pow, dict()).get(lo_freq, 0) / 2
            # mod_loss = self._calibrated_pows_mod.get(mod_pow, dict()).get(mod_f, 0)
            # out_loss = self._calibrated_pows_rf.get(lo_freq, dict()).get(mod_f, 0) / 2

            src.send(f'APPLY p25v,{vco_u}V,{src_i_max}A')

            if not mock_enabled:
                time.sleep(0.5)

            sa_center_freq = 0
            sa.send(f':SENSe:FREQuency:CENTer {sa_center_freq}')

            raw_point = {
                'src_u': src_u,
                'vco_u': vco_u,
            }

            # if mock_enabled:
            #     raw_point = mocked_raw_data[index]
            #     raw_point['out_loss'] = out_loss
            #     index += 1

            print(raw_point)
            res.append(raw_point)
            self._add_measure_point(raw_point)

        src.send('OUTPut OFF')
        sa.send(':CAL:AUTO ON')

        if not mock_enabled:
            with open('out.txt', mode='wt', encoding='utf-8') as f:
                f.write(str(res))
        # endregion
        return res

    def _add_measure_point(self, data):
        print('measured point:', data)
        self.result.add_point(data)
        self.pointReady.emit()

    def saveConfigs(self):
        pprint_to_file('params.ini', self.secondaryParams.params)

    @pyqtSlot(dict)
    def on_secondary_changed(self, params):
        self.secondaryParams.params = params

    @property
    def status(self):
        return [i.status for i in self._instruments.values()]
