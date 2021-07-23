import ast
import time

import numpy as np

from collections import defaultdict
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal

from instr.instrumentfactory import mock_enabled, GeneratorFactory, SourceFactory, \
    MultimeterFactory, AnalyzerFactory
from measureresult import MeasureResult
from util.file import load_ast_if_exists, pprint_to_file


class InstrumentController(QObject):
    pointReady = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        addrs = load_ast_if_exists('instr.ini', default={
            'Анализатор': 'GPIB1::18::INSTR',
            'P LO': 'GPIB1::6::INSTR',
            'P RF': 'GPIB1::20::INSTR',
            'Источник': 'GPIB1::3::INSTR',
            'Мультиметр': 'GPIB1::22::INSTR',
        })
        self.requiredInstruments = {
            'Анализатор': AnalyzerFactory(addrs['Анализатор']),
            'P LO': GeneratorFactory(addrs['P LO']),
            'P RF': GeneratorFactory(addrs['P RF']),
            'Источник': SourceFactory(addrs['Источник']),
            'Мультиметр': MultimeterFactory(addrs['Мультиметр']),
        }

        self.deviceParams = {
            'Демодулятор': {
                'F': 1,
            },
        }

        self.secondaryParams = load_ast_if_exists('params.ini', default={
            'Usrc': 5.0,
            'Flo_min': 1.0,
            'Flo_max': 3.0,
            'Flo_delta': 0.5,
            'is_Flo_x2': False,
            'Plo': -5.0,
            'Prf': -5.0,
            'loss': 0.82,
            'ref_level': 10.0,
            'scale_y': 5.0,
            'Umin': 4.75,
            'Umax': 5.25,
            'Udelta': 0.05,
        })

        self._calibrated_pows_lo = load_ast_if_exists('cal_lo.ini', default={})
        self._calibrated_pows_rf = load_ast_if_exists('cal_rf.ini', default={})

        self._deltas = load_ast_if_exists('deltas.ini', default={
            5: 0.9, 10: 0.82, 20: 0.82, 30: 0.82, 40: 0.82, 50: 0.86,
            60: 0.86, 70: 0.86, 80: 0.86, 90: 0.86, 100: 0.93, 150: 0.98,
            200: 0.99, 250: 1.02, 300: 1.05, 350: 1.1, 400: 1.15, 450: 1.51
        })

        self._instruments = dict()
        self.found = False
        self.present = False
        self.hasResult = False

        self.result = MeasureResult()

    def __str__(self):
        return f'{self._instruments}'

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

    def _calibrateLO(self, token, secondary):
        print('run calibrate LO with', secondary)

        gen_lo = self._instruments['P LO']
        sa = self._instruments['Анализатор']

        secondary = self.secondaryParams

        pow_lo = secondary['Plo']
        freq_lo_start = secondary['Flo_min']
        freq_lo_end = secondary['Flo_max']
        freq_lo_step = secondary['Flo_delta']
        freq_lo_x2 = secondary['is_Flo_x2']

        freq_lo_values = [round(x, 3) for x in
                          np.arange(start=freq_lo_start, stop=freq_lo_end + 0.0001, step=freq_lo_step)]

        sa.send(':CAL:AUTO OFF')
        sa.send(':SENS:FREQ:SPAN 1MHz')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV 10')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV 5')
        sa.send(':CALC:MARK1:MODE POS')

        gen_lo.send(f':OUTP:MOD:STAT OFF')
        gen_lo.send(f'SOUR:POW {pow_lo}dbm')

        result = {}
        for freq in freq_lo_values:

            if freq_lo_x2:
                freq *= 2

            if token.cancelled:
                gen_lo.send(f'OUTP:STAT OFF')
                time.sleep(0.5)

                gen_lo.send(f'SOUR:POW {pow_lo}dbm')

                gen_lo.send(f'SOUR:FREQ {freq_lo_start}GHz')
                raise RuntimeError('calibration cancelled')

            gen_lo.send(f'SOUR:FREQ {freq}GHz')
            gen_lo.send(f'OUTP:STAT ON')

            if not mock_enabled:
                time.sleep(0.35)

            sa.send(f':SENSe:FREQuency:CENTer {freq}GHz')
            sa.send(f':CALCulate:MARKer1:X:CENTer {freq}GHz')

            if not mock_enabled:
                time.sleep(0.35)

            pow_read = float(sa.query(':CALCulate:MARKer:Y?'))
            loss = abs(pow_lo - pow_read)
            if mock_enabled:
                loss = 10

            print('loss: ', loss)
            result[freq] = loss

        pprint_to_file('cal_lo.ini', result)

        gen_lo.send(f'OUTP:STAT OFF')
        sa.send(':CAL:AUTO ON')
        self._calibrated_pows_lo = result
        return True

    def _calibrateRF(self, token, secondary):
        print('run calibrate RF with', secondary)

        gen_rf = self._instruments['P RF']
        sa = self._instruments['Анализатор']

        secondary = self.secondaryParams

        freq_lo_start = secondary['Flo_min']
        freq_lo_end = secondary['Flo_max']
        freq_lo_step = secondary['Flo_delta']

        pow_lo = secondary['Plo']
        pow_rf = secondary['Prf']

        freq_lo_values = [round(x, 3) for x in np.arange(start=freq_lo_start, stop=freq_lo_end + 0.002, step=freq_lo_step)]
        freq_rf_deltas_and_losses = [[k / 1_000, v] for k, v in self._deltas.items()]

        sa.send(':CAL:AUTO OFF')
        sa.send(':SENS:FREQ:SPAN 1MHz')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV 10')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV 5')
        sa.send(':CALC:MARK1:MODE POS')

        result = defaultdict(dict)

        for freq_lo in freq_lo_values:
            for freq_rf_delta, loss in freq_rf_deltas_and_losses:

                if token.cancelled:
                    gen_rf.send(f'OUTP:STAT OFF')

                    time.sleep(0.5)

                    gen_rf.send(f'SOUR:POW {pow_rf}dbm')
                    gen_rf.send(f'SOUR:FREQ {freq_rf_deltas_and_losses[0][0]}GHz')
                    raise RuntimeError('calibration cancelled')

                freq_rf = freq_lo + freq_rf_delta
                gen_rf.send(f'SOUR:FREQ {freq_rf}GHz')
                gen_rf.send(f'SOUR:POW {pow_rf}dbm')
                gen_rf.send(f'OUTP:STAT ON')

                if not mock_enabled:
                    time.sleep(0.35)

                center_freq = freq_rf
                sa.send(f':SENSe:FREQuency:CENTer {center_freq}GHz')
                sa.send(f':CALCulate:MARKer1:X:CENTer {center_freq}GHz')

                if not mock_enabled:
                    time.sleep(0.35)

                pow_read = float(sa.query(':CALCulate:MARKer:Y?'))
                loss = abs(pow_rf - pow_read)
                if mock_enabled:
                    loss = 10

                print('loss: ', loss)
                result[freq_lo][freq_rf_delta] = loss

        result = {k: v for k, v in result.items()}
        pprint_to_file('cal_rf.ini', result)

        gen_rf.send(f'OUTP:STAT OFF')
        sa.send(':CAL:AUTO ON')
        self._calibrated_pows_rf = result
        return True

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
        secondary = self.secondaryParams
        print(f'launch measure with {token} {param} {secondary}')

        self._clear()
        _, i_res = self._measure_s_params(token, param, secondary)
        self.result.process_i(i_res)
        return True

    def _clear(self):
        self.result.clear()

    def _init(self):
        self._instruments['P LO'].send('*RST')
        self._instruments['P RF'].send('*RST')
        self._instruments['Источник'].send('*RST')
        self._instruments['Мультиметр'].send('*RST')
        self._instruments['Анализатор'].send('*RST')

    def _measure_s_params(self, token, param, secondary):
        gen_lo = self._instruments['P LO']
        gen_rf = self._instruments['P RF']
        src = self._instruments['Источник']
        mult = self._instruments['Мультиметр']
        sa = self._instruments['Анализатор']

        src_u = secondary['Usrc']
        src_i = 200   # mA

        u_start = secondary['Umin']
        u_end = secondary['Umax']
        u_step = secondary['Udelta']

        freq_lo_start = secondary['Flo_min']
        freq_lo_end = secondary['Flo_max']
        freq_lo_step = secondary['Flo_delta']
        freq_lo_x2 = secondary['is_Flo_x2']

        pow_lo = secondary['Plo']
        pow_rf = secondary['Prf']

        p_loss = secondary['loss']
        ref_level = secondary['ref_level']
        scale_y = secondary['scale_y']

        freq_lo_values = [round(x, 3) for x in np.arange(start=freq_lo_start, stop=freq_lo_end + 0.002, step=freq_lo_step)]
        freq_rf_deltas_and_losses = [[k / 1_000, v] for k, v in self._deltas.items()]
        u_values = [round(x, 3) for x in np.arange(start=u_start, stop=u_end + 0.002, step=u_step)]

        src.send(f'APPLY p6v,{src_u}V,{src_i}mA')

        sa.send(':CAL:AUTO OFF')
        sa.send(':SENS:FREQ:SPAN 1MHz')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV {ref_level}')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV {scale_y}')

        gen_lo.send(f':OUTP:MOD:STAT OFF')
        # gen_rf.send(f':OUTP:MOD:STAT OFF')

        if mock_enabled:
            with open('./mock_data/-5db.txt', mode='rt', encoding='utf-8') as f:
                index = 0
                mocked_raw_data = ast.literal_eval(''.join(f.readlines()))

        res = []
        for freq_lo in freq_lo_values:

            freq_lo_label = float(freq_lo)
            if freq_lo_x2:
                freq_lo *= 2
                freq_lo_label *= 2

            gen_lo.send(f'SOUR:FREQ {freq_lo}GHz')

            for freq_rf_delta, loss in freq_rf_deltas_and_losses:

                if token.cancelled:
                    gen_lo.send(f'OUTP:STAT OFF')
                    gen_rf.send(f'OUTP:STAT OFF')

                    if not mock_enabled:
                        time.sleep(0.5)

                    src.send('OUTPut OFF')

                    gen_rf.send(f'SOUR:POW {pow_rf}dbm')
                    gen_lo.send(f'SOUR:POW {pow_lo}dbm')

                    gen_rf.send(f'SOUR:FREQ {freq_lo_start + freq_rf_deltas_and_losses[0][0]}GHz')
                    gen_lo.send(f'SOUR:FREQ {freq_lo_start}GHz')
                    raise RuntimeError('measurement cancelled')

                delta_lo = round(self._calibrated_pows_lo.get(freq_lo, 0), 2)
                gen_lo.send(f'SOUR:POW {pow_lo + delta_lo}dbm')
                delta_rf = round(self._calibrated_pows_rf.get(freq_lo, dict()).get(freq_rf_delta, 0), 2)
                gen_rf.send(f'SOUR:POW {pow_rf + delta_rf}dbm')

                freq_rf = (freq_lo if not freq_lo_x2 else (freq_lo / 2)) + freq_rf_delta
                gen_rf.send(f'SOUR:FREQ {freq_rf}GHz')

                src.send('OUTPut ON')

                gen_lo.send(f'OUTP:STAT ON')
                gen_rf.send(f'OUTP:STAT ON')

                time.sleep(0.01)
                if not mock_enabled:
                    time.sleep(0.5)

                i_mul_read = float(mult.query('MEAS:CURR:DC? 1A,DEF'))

                center_freq = freq_rf_delta
                sa.send(':CALC:MARK1:MODE POS')
                sa.send(f':SENSe:FREQuency:CENTer {center_freq}GHz')
                sa.send(f':CALCulate:MARKer1:X:CENTer {center_freq}GHz')

                if not mock_enabled:
                    time.sleep(0.5)

                pow_read = float(sa.query(':CALCulate:MARKer:Y?'))

                raw_point = {
                    'f_lo': freq_lo,
                    'f_lo_label': freq_lo_label,
                    'f_rf': freq_rf,
                    'p_lo': pow_lo,
                    'p_rf': pow_rf,
                    'fpch': freq_rf_delta,
                    'u_mul': src_u,
                    'i_mul': i_mul_read,
                    'pow_read': pow_read,
                    'loss': loss,
                }

                if mock_enabled:
                    raw_point = mocked_raw_data[index]
                    raw_point['loss'] = loss
                    raw_point['fpch'] = freq_rf_delta
                    raw_point['f_lo_label'] = freq_lo_label
                    index += 1

                print(raw_point)

                res.append(raw_point)
                self._add_measure_point(raw_point)

        if not mock_enabled:
            with open('out.txt', mode='wt', encoding='utf-8') as f:
                f.write(str(res))

        gen_lo.send(f'OUTP:STAT OFF')
        gen_rf.send(f'OUTP:STAT OFF')

        if not mock_enabled:
            time.sleep(0.5)

        src.send('OUTPut OFF')

        gen_rf.send(f'SOUR:POW {pow_rf}dbm')
        gen_lo.send(f'SOUR:POW {pow_lo}dbm')

        gen_rf.send(f'SOUR:FREQ {freq_lo_start + freq_rf_deltas_and_losses[0][0]}GHz')
        gen_lo.send(f'SOUR:FREQ {freq_lo_start}GHz')

        sa.send(':CAL:AUTO ON')

        # measure current
        # temporary hacky implementation
        if mock_enabled:
            with open('./mock_data/current.txt', mode='rt', encoding='utf-8') as f:
                index = 0
                mocked_raw_data = ast.literal_eval(''.join(f.readlines()))

        i_res = []
        for u in u_values:
            if token.cancelled:
                src.send('OUTPut OFF')
                raise RuntimeError('measurement cancelled')

            src.send(f'APPLY p6v,{u}V,{src_i}mA')
            src.send('OUTPut ON')

            time.sleep(0.1)
            if not mock_enabled:
                time.sleep(0.5)

            # u_mul_read = float(mult.query('MEAS:VOLT?'))
            i_mul_read = float(mult.query('MEAS:CURR:DC? 1A,DEF'))

            raw_point = {
                'u_mul': u,
                # 'u_mul': u_mul_read,
                'i_mul': i_mul_read * 1_000,
            }

            if mock_enabled:
                raw_point = mocked_raw_data[index]
                raw_point['i_mul'] *= 1_000
                index += 1

            print(raw_point)

            i_res.append(raw_point)

        if not mock_enabled:
            time.sleep(0.5)
        src.send('OUTPut OFF')
        return res, i_res

    def _add_measure_point(self, data):
        print('measured point:', data)
        self.result.add_point(data)
        self.pointReady.emit()

    def saveConfigs(self):
        pprint_to_file('params.ini', self.secondaryParams)

    @pyqtSlot(dict)
    def on_secondary_changed(self, params):
        self.secondaryParams = params

    @property
    def status(self):
        return [i.status for i in self._instruments.values()]
