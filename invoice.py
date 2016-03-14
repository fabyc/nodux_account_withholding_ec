# -*- coding: utf-8 -*-
#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.

from trytond.model import Workflow, ModelSQL, ModelView, fields
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Eval
from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.transaction import Transaction
from trytond.modules.company import CompanyReport
from trytond.wizard import Wizard, StateView, StateTransition, StateAction, \
    Button
from decimal import Decimal
from collections import defaultdict
from trytond.report import Report
from trytond import backend
from trytond.pyson import If, Eval, Bool, Id
from trytond.transaction import Transaction
from trytond.pool import Pool

__all__ = ['Invoice', 'WithholdingOutStart', 'WithholdingOut','Withholding','ReportWithholding']
        
__metaclass__ = PoolMeta
#customer->cliente

_STATES = {
    'readonly': Eval('state') != 'draft',
}
_STATES2 = {
    'invisible': Eval('type') != 'anticipo',
}

_DEPENDS = ['state']

_TYPE = [
    ('out_withholding','Comprobante de Retencion Cliente '),
    ('in_withholding','Comprobante de Retencion Proveedor '),
    ('anticipo', 'Anticipo a Cliente')
]

_TYPE2JOURNAL = {
    'out_withholding': 'revenue',
    'in_withholding': 'expense',
    'anticipo':'revenue',    
    'out_invoice': 'revenue',
    'in_invoice': 'expense',
    'out_credit_note': 'revenue',
    'in_credit_note': 'expense',
}

_WITHHOLDING_TYPE = {
    'out_invoice': 'out_withholding',
    'in_invoice' : 'in_withholding',
    }


class Invoice:
    'Invoice'
    __name__ = 'account.invoice'   

    voucher = fields.Char(u'Comprobante Retencion', size= 20,)
    #number_w = fields.Char('Number', size=20, readonly=True, select=True)
    number_withholding = fields.Integer('Withholding Number', states={
            'invisible': Eval('type') != 'out_withholding',
            })
    
    total_amount_2 = fields.Function(fields.Numeric(u'Saldo a favor del cliente'), 'on_change_with_total_amount_2')
    total_amount = fields.Function(fields.Numeric('Total', digits=(16,
                Eval('currency_digits', 2)), depends=['currency_digits']),
        'on_change_with_total_amount_2')
    value_withholding_b = fields.Function(fields.Numeric(u'Valor a Retener Base'), 'on_change_with_value_withholding_b')
    untaxed_withholding_t = fields.Many2One('account.tax', u'Impuesto Retención')
    value_withholding_b = fields.Numeric(u'Valor a Retener Base', digits=(16,
                Eval('currency_digits', 2)), depends=['currency_digits'])
    value_withholding_t = fields.Numeric(u'Valor a Retener', digits=(16,
                Eval('currency_digits', 2)), depends=['currency_digits'])
    total_withholding = fields.Numeric(u'Total a Retener')
    base_imponible = fields.Numeric(u'Valor Base imponible')
    iva = fields.Numeric(u'Valor Impuesto')
            
    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        cls.state_string = super(Invoice, cls).state.translated('state')
        new_sel = [
            ('out_withholding', 'Comprobante de Retencion Cliente '),
            ('in_withholding', 'Comprobante de Retencion Proveedor '),
        ]
        if new_sel not in cls.type.selection:
            cls.type.selection.extend(new_sel)
            
                     
    def _withholdingOut(self):
        '''
        Return values to withholding.
        '''
        res = {}
        res['type'] = _WITHHOLDING_TYPE[self.type]
        res['base_imponible'] = self.taxes[0].base
        res['iva']= self.taxes[0].amount
        #res['origin'] = str(self)
        print "El numero es ", self.number
        res['number_w'] = self.number
        """
        res['ambiente'] = self.invoice_date
        """
        for field in ('description', 'comment'):
            res[field] = getattr(self, field)

        for field in ('company', 'party', 'invoice_address', 'currency',
                'journal', 'account', 'payment_term'):
            res[field] = getattr(self, field).id

        res['taxes'] = []
        to_create = [tax._credit() for tax in self.taxes if tax.manual]
        if to_create:
            res['taxes'].append(('create', to_create))
       
        return res
            
                
    @classmethod
    def withholdingOut(cls, invoices):
        '''
        Withholding and return ids of new withholdings.
        Return the list of new invoice
        '''
        MoveLine = Pool().get('account.move.line')
        new_invoices = []
        for invoice in invoices:
            new_invoice, = cls.create([invoice._withholdingOut()])
            new_invoices.append(new_invoice)
                
        return new_invoices
        
    def set_number(self):
        '''
        Set number to the invoice
        '''
        pool = Pool()
        Period = pool.get('account.period')
        Sequence = pool.get('ir.sequence.strict')
        Date = pool.get('ir.date')     
        if self.number: 
            return

        test_state = True
        if self.type in ('in_invoice', 'in_credit_note'):
            test_state = False

        accounting_date = self.accounting_date or self.invoice_date
        period_id = Period.find(self.company.id,
            date=accounting_date, test_state=test_state)
        period = Period(period_id)
        sequence = period.get_invoice_sequence(self.type)
        if not sequence:
            self.raise_user_error('no_invoice_sequence', {
                    'invoice': self.rec_name,
                    'period': period.rec_name,
                    })
        with Transaction().set_context(
                date=self.invoice_date or Date.today()):
            number = Sequence.get_id(sequence.id)
            vals = {'number': number}
            if (not self.invoice_date
                    and self.type in ('out_invoice', 'out_credit_note')):
                vals['invoice_date'] = Transaction().context['date']
        self.write([self], vals)
        
    @fields.depends('type', 'party', 'company')
    def on_change_type(self):
        Journal = Pool().get('account.journal')
        res = {}
        journals = Journal.search([
                ('type', '=', _TYPE2JOURNAL.get(self.type or 'out_invoice',
                        'revenue')),
                ], limit=1)
        if journals:
            journal, = journals
            res['journal'] = journal.id
            res['journal.rec_name'] = journal.rec_name
        res.update(self.__get_account_payment_term())
        return res
        
    def get_ventas(self):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        MoveLine = pool.get('account.move.line')
        invoices_paid= Invoice.search([('type','=','out_invoice'), ('state','=', 'paid')])
        invoices_posted = Invoice.search([('state','=', 'posted'), ('type','=','out_invoice')])
        lines = MoveLine.search([('state', '=', 'valid')])
        total_ventas_paid = 0
        total_ventas_posted = 0
        
        for i in invoices_paid:
            for l in lines:
                if i.move == l.move:
                    total_ventas_paid = total_ventas_paid + l.debit 
                    print total_ventas_paid   
                                     
        for i2 in invoices_posted:
            for l2 in lines:
                if i2.move == l2.move:
                    total_ventas_posted = total_ventas_posted + l2.debit
        total_ventas = total_ventas_paid + total_ventas_posted
        
        return total_ventas
 
    def get_value(self):
        MESSAGE_ANTICIPO = "Valor de Retencion es mayor que credito de cliente. \nDebe generar anticipo de '%s'"
        value = 0
        value_c = 0
        valor=0
        valor2=0
        party = self.party
        pool = Pool()
        total = pool.get('account.move.line')  
        invoice = pool.get('account.invoice')
        line_invoice = invoice.search([('number','=', self.number_w)])
        lines = total.search([('party','=', party)])
        asientos = total.search([('party','=', party)])
        for line_i in line_invoice:
            line_r = line_i
            move= line_i.move
            state = line_i.state
        moves = total.search([('description', '=', self.number_w)])
        moves2 = total.search([('move', '=', move)])
        for move2 in moves2:
            valor2= move2.debit + valor2
        for move in moves:
            valor = move.debit + valor
        for line in lines:
            value = line.debit + value
            value_c = line.credit + value_c
        value_total = value - value_c
        value_withholding = self.total_amount * (-1) 
        valor_conciliar = valor2 - valor
        if value_total < 0:
            value_total = value_total * (-1)
        if value_withholding > value_total:
            if state == 'paid':    
                anticipo = value_withholding - value_total
                self.raise_user_error(MESSAGE_ANTICIPO, anticipo)
                print "Debe generar anticipo de" ,anticipo
                pass
            else:
                anticipo = value_withholding - value_total
                if value_total == 0:
                    self.raise_user_error(MESSAGE_ANTICIPO, anticipo)
                    print line_r.get_reconcile_lines_for_amount(value_total)
                    pass
                else:
                    self.raise_user_error(MESSAGE_ANTICIPO, anticipo)
                    print line_r.get_reconcile_lines_for_amount(0)
                    pass
                """
                for move_reconciliated in moves:
                    if move_reconciliated.party:
                        if move_reconciliated.reconciliation:
                            print "Esta conciliado " ,move_reconciliated.reconciliation
                            
                        else:
                            amount = move_reconciliated.debit
                            print "A contabilizar ",line_r
                            print "Monto a conciliar " ,amount
                            print line_r.get_reconcile_lines_for_amount(value_total)
                            print "No esta conciliado, deben conciliarse las lineas"
                """
     
    @fields.depends('party')
    def on_change_with_total_amount_2(self, name=None):
        if self.party:
            value = 0
            value_c = 0
            party = self.party
            pool = Pool()
            total = pool.get('account.move.line')  
            lines = total.search([('party','=', party)])
            for line in lines:
                value = line.debit + value
                value_c = line.credit + value_c
            print "Valores totales debito y credito",value, value_c
            value_total = value_c - value
            
            if value_total < 0:
                return 0
            return value_total

    @classmethod
    @ModelView.button
    @Workflow.transition('validated')
    def validate_invoice(cls, invoices):
        for invoice in invoices:
            if invoice.type in ('in_withholding', 'out_withholding'):
                print "Esta ingresando aqui*** validar w**"
                #invoice.get_ventas()
                invoice.set_number()
                invoice.create_move()
            if invoice.type in ('delivery_note'):
                #invoice.get_ventas()
                invoice.set_number()
                
    @classmethod
    @ModelView.button
    @Workflow.transition('posted')
    def post(cls, invoices):
        Move = Pool().get('account.move')
        moves = []
        for invoice in invoices:
            print "Esta ingresando aqui*** contabilizar wi**"
            invoice.set_number()
            moves.append(invoice.create_move())
        for invoice in invoices:
            if invoice.type in ('out_withholding'):
                invoice.get_value()
        cls.write([i for i in invoices if i.state != 'posted'], {
                'state': 'posted',
                })
        Move.post([m for m in moves if m.state != 'posted'])              
        
        for invoice in invoices:
            if invoice.type in ('out_invoice', 'out_credit_note'):
                invoice.print_invoice()
                      
                
class WithholdingOutStart(ModelView):
    'Withholding Out Start'
    __name__ = 'nodux_account_withholding_ec.out_withholding.start'
    
class WithholdingOut(Wizard):
    'Withholding Out'
    __name__ = 'nodux_account_withholding_ec.out_withholding'
    #crear referencias:
    start = StateView('nodux_account_withholding_ec.out_withholding.start',
        'nodux_account_withholding_ec.out_withholding_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Withholding', 'withholdingOut', 'tryton-ok', default=True),
            ])
    withholdingOut = StateAction('account_invoice.act_invoice_form')
        
    @classmethod
    def __setup__(cls):
        super(WithholdingOut, cls).__setup__()
     
    def do_withholdingOut(self, action):
        pool = Pool()
        Invoice = pool.get('account.invoice')

        invoices = Invoice.browse(Transaction().context['active_ids'])
        print "el tipo de factura", invoices
        for invoice in invoices:
            if invoice.type != 'out_invoice':
                self.raise_user_error('No puede generar un comprobante de retencion desde %s',invoice.type)
        #presentar errores 
        
        out_withholding = Invoice.withholdingOut(invoices)

        data = {'res_id': [i.id for i in out_withholding]}
        if len(out_withholding) == 1:
            action['views'].reverse()
            
        return action, data
       
class Withholding(CompanyReport):
    'Withholding'
    __name__ = 'account.invoice.withholding'

    @classmethod
    def __setup__(cls):
        super(Withholding, cls).__setup__()

    @classmethod
    def parse(cls, report, objects, data, localcontext=None):
        localcontext['company'] = Transaction().context.get('company')
        localcontext['invoice'] = Transaction().context.get('invoice')
        return super(Withholding, cls).parse(report,
                objects, data, localcontext)
                
class ReportWithholding(CompanyReport):
    'Report Withholding'
    __name__ = 'account.invoice.report_withholding'

    @classmethod
    def __setup__(cls):
        super(ReportWithholding, cls).__setup__()

    @classmethod
    def parse(cls, report, objects, data, localcontext=None):
        localcontext['party'] = Transaction().context.get('party')
        localcontext['company'] = Transaction().context.get('company')
        localcontext['invoice'] = Transaction().context.get('invoice')
        return super(ReportWithholding, cls).parse(report,
                objects, data, localcontext)

