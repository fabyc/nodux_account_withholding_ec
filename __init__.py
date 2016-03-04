#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
from trytond.pool import Pool
from .invoice import *
from .account import *
def register():
    Pool.register(
        Invoice,
        WithholdingOutStart,
        FiscalYear, 
        Period,
        module='nodux_account_withholding_ec', type_='model')
    Pool.register(
        WithholdingOut,
        module='nodux_account_withholding_ec', type_='wizard')
    Pool.register(
        Withholding,
        ReportWithholding,
        Advanced,
        module='nodux_account_withholding_ec', type_='report')
