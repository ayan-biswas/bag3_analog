# BSD 3-Clause License
#
# Copyright (c) 2018, Regents of the University of California
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# -*- coding: utf-8 -*-

from typing import Dict, Any, Tuple, Union, Optional

import pkg_resources
from pathlib import Path

from bag.design.module import Module
from bag.design.database import ModuleDB
from bag.util.immutable import Param
from bag.math import float_to_si_string


# noinspection PyPep8Naming
class bag3_analog__high_pass_diff(Module):
    """ Differential HPF
    # TODO: can we merge this with single HPF? or instantiate 2 subcells?
    """

    yaml_file = pkg_resources.resource_filename(__name__,
                                                str(Path('netlist_info',
                                                         'high_pass_diff.yaml')))

    def __init__(self, database: ModuleDB, params: Param, **kwargs: Any) -> None:
        Module.__init__(self, self.yaml_file, database, params, **kwargs)

    @classmethod
    def get_params_info(cls) -> Dict[str, str]:
        """Returns a dictionary from parameter names to descriptions.

        Returns
        -------
        param_info : Optional[Dict[str, str]]
            dictionary from parameter names to descriptions.
        """
        return dict(
            l='unit resistor length, in resolution units',
            w='unit resistor width, in resolution units',
            intent='resistor type.',
            nser='number of resistors in series in a branch.',
            ndum='number of dummy resistors (parallel, series).',
            res_in_info='input metal resistor information (None to remove).',
            res_out_info='output metal resistor information (None to remove).',
            sub_name='substrate name. Empty string to disable.',
            bias_diff='True for differential bias (biasp, biasn), False for common mode bias',
            connect_res_to_cap_res_metal='True to connect resistors to floating nodes of the cap\'s res_metal '
                                         '(instead of outp/outn)',
            connect_dum_to_sub='True to connect dummy resistor ports to substrate (instead of bias)',
            cap_val='Schematic value for analogLib cap. Can specify 1 value for ideal cap, or a tuple of 4 values to '
                    'additionally include parasitic caps at bias, input, and output nodes (in that order)',
            extracted='True if doing LVS or extraction. Removes analogLib caps',
        )

    @classmethod
    def get_default_param_values(cls) -> Dict[str, Any]:
        return dict(
            res_in_info=None,
            res_out_info=None,
            sub_name='VDD',
            bias_diff=True,
            connect_res_to_cap_res_metal=True,
            connect_dum_to_sub=False,
            cap_val=1e-9,
            extracted=False,
        )

    def design(self, l: int, w: int, intent: str, nser: int, ndum: Union[int, Tuple[int, int]],
               res_in_info: Optional[Tuple[int, int, int]], res_out_info: Optional[Tuple[int, int, int]], sub_name: str,
               bias_diff: bool, connect_res_to_cap_res_metal: bool, connect_dum_to_sub: bool,
               cap_val: Union[float, Tuple[float, float, float, float]], extracted: bool) -> None:
        """"""
        has_res_in = res_in_info is not None
        has_res_out = res_out_info is not None
        # if res_metals are not used for cap LVS, then resistors should connect directly to outp and outn
        connect_res_to_cap_res_metal = connect_res_to_cap_res_metal and has_res_out
        res_out_conn_pfx = 'nc_' if connect_res_to_cap_res_metal else ''

        if bias_diff:
            bias_p, bias_n = 'biasp', 'biasn'
        else:
            self.rename_pin('biasp', 'bias')
            self.remove_pin('biasn')
            bias_p = bias_n = 'bias'

        res_name_info = (
            ('XRESP', res_out_conn_pfx + 'outp', bias_p),
            ('XRESN', res_out_conn_pfx + 'outn', bias_n)
        )

        # Design resistors
        unit_params = dict(l=l, w=w, intent=intent)
        for (inst_name, out_name, bias_name) in res_name_info:
            self.design_resistor(inst_name, unit_params, nser, 1, out_name, bias_name, f'{out_name}_x', sub_name)

        # Design dummy resistors
        dum_names = ['XRESPD', 'XRESND']
        dum_conns = [sub_name] * 2 if connect_dum_to_sub else [bias_p, bias_n]
        dum_mid_conns_pfx = [sub_name + '_p', sub_name + '_n'] if dum_conns[0] == dum_conns[1] else dum_conns
        if isinstance(ndum, int):
            ndum = (ndum, 1)
        if len(ndum) == 2:
            ndum = (*ndum, True)
        ndum_par, ndum_ser, dum_connect_mid = ndum
        for name, conn, mid_pfx in zip(dum_names, dum_conns, dum_mid_conns_pfx):
            if not ndum:
                self.remove_instance(name)
            else:
                self.design_resistor(name, unit_params, ndum_ser, ndum_par, conn, conn, f'{mid_pfx}_dum_x',
                                     bulk=sub_name, connect_mid=dum_connect_mid)

        # Design metal resistors
        if has_res_in:
            self.instances['XMRESP1'].design(layer=res_in_info[0], w=res_in_info[1], l=res_in_info[2])
            self.instances['XMRESN1'].design(layer=res_in_info[0], w=res_in_info[1], l=res_in_info[2])
        else:
            self.remove_instance('XMRESP1')
            self.remove_instance('XMRESN1')

        if has_res_out:
            self.instances['XMRESP2'].design(layer=res_out_info[0], w=res_out_info[1], l=res_out_info[2])
            self.instances['XMRESN2'].design(layer=res_out_info[0], w=res_out_info[1], l=res_out_info[2])
        else:
            self.remove_instance('XMRESP2')
            self.remove_instance('XMRESN2')

        # Design capacitors
        cap_in_conn_pfx = 'nc_' if has_res_in else ''
        cap_out_conn_pfx = 'nc_' if has_res_out else ''
        cap_name_info = (
            ('XCAPP', 'inp', 'outp', bias_p, cap_in_conn_pfx),
            ('XCAPN', 'inn', 'outn', bias_n, cap_out_conn_pfx),
        )
        if extracted:
            for _name_info in cap_name_info:
                self.remove_instance(_name_info[0])
        else:
            if isinstance(cap_val, float):
                cap_val = (cap_val, 0, 0, 0)
            cc, cpb, cpi, cpo = [float_to_si_string(c) for c in cap_val]
            for (inst_name, in_name, out_name, bias_name, cc_pfx) in cap_name_info:
                cap_info_list = [(inst_name + 'C', cc, cc_pfx + in_name, cc_pfx + out_name)]
                if cpb != 0:
                    cap_info_list.append((inst_name + 'PB', cpb, bias_name, sub_name))
                if cpi != 0:
                    cap_info_list.append((inst_name + 'PI', cpi, in_name, sub_name))
                if cpo != 0:
                    cap_info_list.append((inst_name + 'PO', cpo, out_name, sub_name))
                cap_names = [cap_info[0] for cap_info in cap_info_list]
                self.array_instance(inst_name, cap_names)
                for (cap_name, param_val, plus_conn, minus_conn) in cap_info_list:
                    self.instances[cap_name].set_param('c', param_val)
                    self.reconnect_instance(cap_name, dict(PLUS=plus_conn, MINUS=minus_conn).items())

        self.rename_pin('BULK', sub_name)
