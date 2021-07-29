import datetime
import os.path

from collections import defaultdict
from subprocess import Popen
from textwrap import dedent

import pandas as pd

from util.file import load_ast_if_exists, pprint_to_file

KHz = 1_000
MHz = 1_000_000
GHz = 1_000_000_000
mA = 1_000
mV = 1_000


class MeasureResult:
    def __init__(self):
        self._secondaryParams = None
        self._raw = list()
        self._report = dict()
        self._processed = list()
        self.ready = False

        self.data = defaultdict(list)
        self.data_i = dict()

        self.adjustment = load_ast_if_exists('adjust.ini', default=None)

    def __bool__(self):
        return self.ready

    def _process(self):
        self.ready = True

    def _process_point(self, data):
        # region calc
        p_lo = data['p_lo']
        f_lo = data['f_lo']
        f_lo_label = data['f_lo_label']

        p_rf = data['p_rf']
        f_rf = data['f_rf']
        f_pch = data['fpch']

        u_mul = data['u_mul']
        i_mul = data['i_mul']

        p_pch = data['pow_read']

        p_loss = data['loss']
        k_loss = p_pch - p_rf + p_loss
        # endregion

        if self.adjustment is not None:
            point = self.adjustment[len(self._processed)]
            k_loss += point['k_loss']

        self._report = {
            'p_lo': p_lo,
            'f_lo': f_lo,
            'p_rf': p_rf,
            'f_rf': f_rf,
            'f_pch': f_pch,
            'u_mul': round(u_mul, 1),
            'i_mul': round(i_mul * mA, 2),
            'p_pch': p_pch,
            'k_loss': round(k_loss, 2),
        }

        self.data[f_lo_label].append([f_pch, k_loss])
        self._processed.append({**self._report})

    def clear(self):
        self._secondaryParams.clear()
        self._raw.clear()
        self._report.clear()
        self._processed.clear()

        self.data.clear()

        self.ready = False

    def set_secondary_params(self, params):
        self._secondaryParams = dict(**params)

    def add_point(self, data):
        self._raw.append(data)
        self._process_point(data)

    def save_adjustment_template(self):
        if self.adjustment is None:
            print('measured, saving template')
            self.adjustment = [{
                'p_lo': p['p_lo'],
                'f_lo': p['f_lo'],
                'p_rf': p['p_rf'],
                'f_rf': p['f_rf'],
                'k_loss': 0,

            } for p in self._processed]

        pprint_to_file('adjust.ini', self.adjustment)

    def process_i(self, data):
        self.data_i[1] = [list(d.values()) for d in data]

    @property
    def report(self):
        return dedent("""        Генераторы:
        Pгет, дБм={p_lo}
        Fгет, ГГц={f_lo:0.2f}
        Pвх, дБм={p_rf}
        Fвх, ГГц={f_rf:0.2f}
        Fпч, МГц={f_pch:0.2f}
        
        Источник питания:
        U, В={u_mul}
        I, мА={i_mul}

        Анализатор:
        Pп, дБм={p_pch}
        
        Расчётные параметры:
        Кп, дБм={k_loss}""".format(**self._report))

    def export_excel(self):
        device = 'demod'
        path = 'xlsx'
        if not os.path.isdir(f'{path}'):
            os.makedirs(f'{path}')
        file_name_main = f'./{path}/{device}-stage3-{datetime.datetime.now().isoformat().replace(":", ".")}.xlsx'
        file_name_current = f'./{path}/{device}-stage4-{datetime.datetime.now().isoformat().replace(":", ".")}.xlsx'
        df = pd.DataFrame(self._processed)

        df.columns = [
            'Pгет, дБм',
            'Fгет, ГГц',
            'Pвх, дБм',
            'Fвх, ГГц',
            'Fпч, ГГц',
            'Uпит, В',
            'Iпит, мА',
            'Pпч, дБм',
            'Кп, дБм',
        ]
        df.to_excel(file_name_main, engine='openpyxl', index=False)

        df = pd.DataFrame({'u': v[0], 'i': v[1]} for v in self.data_i[1])
        df.columns = ['Uпит, В', 'Iпот, мА']
        df.to_excel(file_name_current, engine='openpyxl', index=False)

        full_path = os.path.abspath(file_name_main)
        Popen(f'explorer /select,"{full_path}"')
