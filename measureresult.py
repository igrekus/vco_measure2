import os
import openpyxl
import pandas as pd

from collections import defaultdict
from openpyxl.chart import LineChart, Series, Reference
from openpyxl.chart.axis import ChartLines
from textwrap import dedent

from forgot_again.file import load_ast_if_exists, pprint_to_file, make_dirs, open_explorer_at
from forgot_again.string import now_timestamp


class MeasureResult:
    device = 'vco'
    measurement_name = 'tune'
    path = 'xlsx'

    def __init__(self):
        self._secondaryParams = dict()
        self._raw = list()
        self._raw_x2 = list()
        self._raw_x3 = list()

        self._report = dict()

        self._processed = list()
        self._processed_x2 = list()
        self._processed_x3 = list()

        self.ready = False

        self.data1 = defaultdict(list)
        self.data2 = defaultdict(list)

        self.data3 = dict()
        self.data4 = dict()

        self.adjustment = load_ast_if_exists('adjust.ini', default=None)

    def __bool__(self):
        return self.ready

    def _process(self):
        harm_x2 = [list(d.values()) for d in self._raw_x2]
        self.data3[1] = harm_x2
        self._processed_x2 = harm_x2

        harm_x3 = [list(d.values()) for d in self._raw_x3]
        self.data4[1] = harm_x3
        self._processed_x3 = harm_x3

        self.ready = True

    def add_harmonics_measurement(self, x2, x3):
        self._raw_x2 = list(x2)
        self._raw_x3 = list(x3)

    def _process_point(self, data):
        u_src = data['u_src']
        u_control = data['u_control']

        f_tune = data['read_f']
        p_out = data['read_p']
        i_src = data['read_i']

        if self.adjustment is not None:
            point = self.adjustment[len(self._processed)]
            f_tune += point['f_tune']
            p_out += point['p_out']
            i_src += point['i_src']

        self._report = {
            'u_src': u_src,
            'u_control': u_control,
            'f_tune': f_tune,
            'p_out': p_out,
            'i_src': i_src,
        }

        self.data1[u_src].append([u_control, f_tune])
        self.data2[u_src].append([u_control, p_out])
        self._processed.append({**self._report})

    def clear(self):
        self._secondaryParams.clear()
        self._raw.clear()
        self._raw_x2.clear()
        self._raw_x3.clear()

        self._report.clear()

        self._processed.clear()
        self._processed_x2.clear()
        self._processed_x3.clear()

        self.data1.clear()
        self.data2.clear()
        self.data3.clear()
        self.data4.clear()

        self.ready = False

    def set_secondary_params(self, params):
        self._secondaryParams = dict(**params.params)

    def add_point(self, data):
        self._raw.append(data)
        self._process_point(data)

    def save_adjustment_template(self):
        if self.adjustment is None:
            print('measured, saving template')
            self.adjustment = [{
                'u_src': p['u_src'],
                'u_control': p['u_control'],
                'f_tune': 0,
                'p_out': 0,
                'i_src': 0,
            } for p in self._processed]
            pprint_to_file('adjust.ini', self.adjustment)

    @property
    def report(self):
        return dedent("""        Источник питания:
        Uпит, В={u_src}
        Uупр, В={u_control}
        Iпот, mA={i_src}

        Анализатор:
        Fвых, МГц={f_tune:0.3f}
        Pвых, дБм={p_out:0.3f}
        """.format(**self._report))

    def export_excel(self):
        make_dirs(self.path)
        fn = self._secondaryParams.get('file_name', None) or f'{self.device}-{self.measurement_name}-{now_timestamp()}'
        file_name = f'./{self.path}/{fn}.xlsx'

        u_dr_1, u_dr_2, u_dr_3 = 0, 0, 0

        udrs = list({point['u_src']: 0 for point in self._processed}.keys())
        try:
            u_dr_1 = udrs[0]
            u_dr_2 = udrs[1]
            u_dr_3 = udrs[2]
        except IndexError:
            pass

        result_harmonics_x2 = [[u_dr_1] + row for row in self._processed_x2]
        result_harmonics_x3 = [[u_dr_1] + row for row in self._processed_x3]

        df_harm_2 = pd.DataFrame(result_harmonics_x2, columns=['Uпит, В', 'Uупр, В', 'Pвых_2, дБм'])
        df_harm_3 = pd.DataFrame(result_harmonics_x3, columns=['Uпит, В', 'Uупр, В', 'Pвых_3, дБм'])

        df = pd.DataFrame(self._processed)
        df.columns=['Uпит, В', 'Uупр, В', 'Fвых, МГц', 'Pвых, дБм', 'Iпот, мА', ]

        df['fdiff'] = df.groupby('Uпит, В')['Fвых, МГц'].diff().shift(-1)
        df['udiff'] = df.groupby('Uпит, В')['Uупр, В'].diff().shift(-1)
        df['S, МГц/В'] = df[df['fdiff'].notna()].apply(lambda row: (row['fdiff'] / row['udiff']) * 100, axis = 1)
        df = df.drop(['fdiff', 'udiff'], axis=1)

        df = pd.merge(df, df_harm_2, how='left', on=['Uпит, В', 'Uупр, В'])
        df = pd.merge(df, df_harm_3, how='left', on=['Uпит, В', 'Uупр, В'])

        df['Pвых_2отн, дБм'] = df[df['Pвых_2, дБм'].notna()].apply(lambda row: -(row['Pвых, дБм'] - row['Pвых_2, дБм']), axis=1)
        df['Pвых_3отн, дБм'] = df[df['Pвых_3, дБм'].notna()].apply(lambda row: -(row['Pвых, дБм'] - row['Pвых_3, дБм']), axis=1)
        df['S, МГц/В'] = df['S, МГц/В'].fillna(0)

        df_udr_1 = df[df['Uпит, В'] == u_dr_1]
        df_udr_2 = df[df['Uпит, В'] == u_dr_2]
        df_udr_3 = df[df['Uпит, В'] == u_dr_3]

        cols = len(df_udr_1.columns)
        rows = len(df_udr_1)

        udr_1_s = [df_udr_1.columns.values.tolist()] + df_udr_1.values.tolist()
        udr_2_s = [df_udr_2.columns.values.tolist()] + (df_udr_2.values.tolist() or [[''] * cols] * rows)
        udr_3_s = [df_udr_3.columns.values.tolist()] + (df_udr_3.values.tolist() or [[''] * cols] * rows)

        print(udr_1_s)
        print(udr_2_s)
        print(udr_3_s)

        wb = openpyxl.Workbook()
        ws = wb.active

        out = []
        for r1, r2, r3 in zip(udr_1_s, udr_2_s, udr_3_s):
            row = r1 + ['', ''] + r2 + ['', ''] + r3
            out.append(row)

        for row in out:
            ws.append(row)

        _add_chart(
            ws=ws,
            xs=Reference(ws, range_string=f'{ws.title}!B2:B{rows}'),
            ys=[
                Reference(ws, range_string=f'{ws.title}!C2:C{rows}'),
                Reference(ws, range_string=f'{ws.title}!O2:O{rows}'),
                Reference(ws, range_string=f'{ws.title}!AA2:AA{rows}'),
            ],
            title='Диапазон перестройки',
            loc='B15',
            curve_labels=['Uпит = 4.7В', 'Uпит = 5.0В', 'Uпит = 5.3В'],
            ax_titles=['Uупр, В', 'Fвых, МГц'],
        )

        _add_chart(
            ws=ws,
            xs=Reference(ws, range_string=f'{ws.title}!B2:B{rows}'),
            ys=[
                Reference(ws, range_string=f'{ws.title}!D2:D{rows}'),
                Reference(ws, range_string=f'{ws.title}!P2:P{rows}'),
                Reference(ws, range_string=f'{ws.title}!AB2:AB{rows}'),
            ],
            title='Мощность',
            loc='M15',
            curve_labels=['Uпит = 4.7В', 'Uпит = 5.0В', 'Uпит = 5.3В'],
            ax_titles=['Uупр, В', 'Pвых, дБм'],
        )

        _add_chart(
            ws=ws,
            xs=Reference(ws, range_string=f'{ws.title}!B2:B{rows}'),
            ys=[
                Reference(ws, range_string=f'{ws.title}!I2:I{rows}'),
            ],
            title='Относительный уровень 2й гармоники',
            loc='B30',
            curve_labels=['Uпит = 4.7В'],
            ax_titles=['Uупр, В', 'Pвых х2, МГц'],
        )

        _add_chart(
            ws=ws,
            xs=Reference(ws, range_string=f'{ws.title}!B2:B{rows}'),
            ys=[
                Reference(ws, range_string=f'{ws.title}!J2:J{rows}'),
            ],
            title='Относительный уровень 3й гармоники',
            loc='M30',
            curve_labels=['Uпит = 4.7В'],
            ax_titles=['Uупр, В', 'Pвых х3, МГц'],
        )

        wb.save(file_name)
        open_explorer_at(os.path.abspath(file_name))


def _add_chart(ws, xs, ys, title, loc, curve_labels=None, ax_titles=None):
    chart = LineChart()

    for y, label in zip(ys, curve_labels):
        ser = Series(y, title=label)
        chart.append(ser)

    chart.set_categories(xs)
    chart.title = title

    chart.x_axis.minorGridlines = ChartLines()
    chart.x_axis.tickLblPos = 'low'

    if ax_titles:
        chart.x_axis.title = ax_titles[0]
        chart.y_axis.title = ax_titles[1]
    # chart.x_axis.tickLblSkip = 3

    ws.add_chart(chart, loc)
