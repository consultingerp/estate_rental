from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import misc, DEFAULT_SERVER_DATETIME_FORMAT
from dateutil.relativedelta import relativedelta
import time
from datetime import datetime, timedelta
from odoo.tools.misc import formatLang
from dateutil.parser import parse

# if parse(self.start) <= parse(rec.order_date) and parse(self.end) >= parse(rec.order_date): 


class Estate_Rental(models.Model):
    _name = "estate.rental"
    _rec_name = "code"
    
    @api.model
    def create(self, vals):
        sequence = self.env['ir.sequence'].next_by_code('estate.rental')
        vals['code'] = str(sequence)
        return super(Estate_Rental, self).create(vals)

    customer = fields.Many2one('res.partner', string ='Customer')
    code = fields.Char('Code')
    date = fields.Datetime('Request Date', default=fields.Datetime.now())
    state = fields.Selection(
        string=u'State', default="Draft",
        selection=[('Draft', 'Draft'), ('Payment', 'Payment'), ('Rented', 'In Progress'), ('Done', 'Done')]
    )
    invoice_id = fields.Many2one('account.invoice', string='Invoice', store=True)
    service_invoice_id = fields.Many2one('account.invoice', string='Services Invoice', store=True)
    total_amount = fields.Float(
        string=u'Total Amount', compute="compute_total",
    )
    total_outstanding = fields.Float(
        string=u'Outstanding', compute="compute_outstanding",
    )
    payment_ids = fields.Many2many(
        'account.payment',
        string='All Payments', compute="_get_payment_ids")
    
    rental_line = fields.One2many(
        'rent.product.line', 'ref_id', string='Rental Lines')
    service_item = fields.One2many(
        'service.product.line', 'ref_id', string='Service Lines')
    outstanding_ids = fields.Many2many('rent.outstanding.record', string='Outstandings')    

    @api.one
    @api.depends('rental_line')
    def compute_total(self):
        amount = 0 
        amount2 = 0
        for rec in self.rental_line:
            amount += rec.total_amount
        for rex in self.service_item:
            amount2 += rex.total_amount
        self.total_amount = amount + amount2
    
    @api.one
    @api.depends('payment_ids','total_amount')
    def compute_outstanding(self):
        amount = 0
        if len(self.payment_ids) >= 1:
            for rec in self.payment_ids:
                amount += rec.amount
            self.total_outstanding = self.total_amount - amount

    @api.one
    @api.depends('invoice_id')
    def _get_payment_ids(self):
        payment_list = []
        for rec in self.invoice_id.payment_ids:
            payment_list.append(rec.id)
        self.payment_ids = payment_list

    @api.one
    def confirm_rent_request(self):
        if self.rental_line:
            for rec in self.rental_line:
                rec.write({'status': 'Occupied'}) #, 'product_id.status': 'Occupied'})
                rec.product_id.status = 'Occupied'
            self.state = 'Payment'
            
    def after_payment(self):
        for rec in self.rental_line:
            rec.product_id.unit -= rec.unit
        if self.total_outstanding <= 0:
            self.state = "Done"
        else:
            self.state = "Rented"
        return True

    @api.multi
    def create_invoice(self):
        invoice_list = [] 
        invoice = 0 
        for partner in self:
            invoice = self.env['account.invoice'].create({
                'partner_id': partner.customer.id,
                'account_id': partner.customer.property_account_payable_id.id,
                'fiscal_position_id': partner.customer.property_account_position_id.id,
                'branch_id': self.env.user.branch_id.id or 1
            })
            invoice = invoice
        line_values = {}
        line_value2 = {}
        for line in self.rental_line: 
            line_values = {
                'product_id': line.product_id.id,
                'price_unit': line.product_id.list_price or line.total_amount,
                'invoice_id': invoice.id,
                'account_id': line.product_id.categ_id.property_account_income_categ_id.id,
                'name': line.product_id.name,
                'quantity': line.unit
            }
            invoice.write({'invoice_line_ids': [(0, 0, line_values)]})
        for serv in self.service_item: 
            line_value2 = {
                'product_id': serv.product_id.id,
                'price_unit': serv.product_id.list_price or serv.rental_price,
                'invoice_id': invoice.id,
                'account_id': serv.product_id.categ_id.property_account_income_categ_id.id,
                'name': serv.product_id.name,
                'quantity': serv.unit
            }
            invoice.write({'invoice_line_ids': [(0, 0, line_value2)]})
        invoice_list.append(invoice.id) 
            # line_value2 = {
            #     'product_id': serv.product_id.id,
            #     'price_unit': serv.product_id.list_price or serv.rental_price,
            #     'invoice_id': invoice.id,
            #     'account_id': serv.product_id.categ_id.property_account_income_categ_id.id,
            #     'name': serv.product_id.name,
            #     'quantity': serv.unit
            # }
        # line_values.update(line_value2)
        
        self.invoice_id = invoice.id 
        find_id = self.env['account.invoice'].search([('id', '=', invoice.id)])
        find_id.action_invoice_open()
        return self.generate_receipt()
        # return invoice_list

    @api.multi
    def generate_receipt(self):
        search_view_ref = self.env.ref(
            'account.view_account_invoice_filter', False)
        form_view_ref = self.env.ref('account.invoice_form', False)
        tree_view_ref = self.env.ref('account.invoice_tree', False)

        return {
            'domain': [('id', '=', self.invoice_id.id)],
            'name': 'Invoices',
            'res_model': 'account.invoice',
            'type': 'ir.actions.act_window',
            'views': [(tree_view_ref.id, 'tree'), (form_view_ref.id, 'form')],
            'search_view_id': search_view_ref and search_view_ref.id,
        }

    @api.one
    def check_service_expiry(self):
        for each in self.service_item:
            if each.end_date:
                today = fields.Datetime.now()
                if each.end_date < today:
                    outst_record = self.env['rent.outstanding.record'].create({'customer': self.customer.id,
                                                                                'product_id': each.product_id.id,
                                                                                'amount_to_pay': each.rental_price,
                                                                                'last_paid_date': each.start_date,
                                                                                'expired_date': each.end_date,
                                                                                'code':each.code,
                                                                                'rental_period': 'Month',
                                                                                'ref_id': each.id,
                                                                                'parent_ref_id': self.id
                                                                                })
                    self.write({'outstanding_ids': [(4, [outst_record.id])]})

                    # raise ValidationError(_('Your {} service charge is due for \
                    #     payment and an outstanding record with reference {} has \
                    #     been generated for invoicing'.format(each.product_id.name, outst_record.code)))
                else:
                    raise ValidationError(_('Your {} service charge is not due for payment.'.format(each.product_id.name)))
                

    @api.multi
    def view_outstandings(self):
        search_view_ref = self.env.ref('estate_rental.rental_outstanding_search', False)
        form_view_ref = self.env.ref('estate_rental.rental_outstanding_line_form', False)
        tree_view_ref = self.env.ref('estate_rental.rental_outstanding_tree', False)

        return {
            'domain': [('id', 'in', self.outstanding_ids)],
            'name': 'Invoices',
            'res_model': 'rent.outstanding.record',
            'type': 'ir.actions.act_window',
            'views': [(tree_view_ref.id, 'tree'), (form_view_ref.id, 'form')],
            'search_view_id': search_view_ref and search_view_ref.id,
             }


class InheritProduct(models.Model):
    _inherit = "product.template"

    is_rent = fields.Boolean(
        string=u'Is Rental', default=False)
    status = fields.Selection(
        string=u'Status', default='Available',
        selection=[('Available', 'Available'), ('Occupied', 'Occupied')]
    )
    unit = fields.Float(
        string=u'Unit', default=None, required=True
    )


class Rental_Product(models.Model):
    _name = "rent.product.line"
    _rec_name = "code"

    @api.model
    def create(self, vals):
        sequence = self.env['ir.sequence'].next_by_code('rent.product.line')
        vals['code'] = str(sequence)
        return super(Rental_Product, self).create(vals)

    ref_id = fields.Many2one('estate.rental')
    code = fields.Char('Code')
    customer = fields.Many2one('res.partner', string ='Customer')    
    product_id = fields.Many2one('product.template', 
                                 string="Product", 
                                 required=True,
                                 domain="[('is_rent', '=', True), ('status', '=', 'Available')]")

    rental_period = fields.Selection(
        string=u'Rental period',required=True,
        selection=[('Days', 'Days'), ('Weeks', 'Week'), ('Month', 'Month'), ('Years', 'Year')]
    )
    extend = fields.Selection(
        string=u'Extend/Deallocation',required=True, default="Normal",
        selection=[('Normal', 'Normal'), ('Extend', 'Extend'), ('Deallocate', 'Deallocate'), ('Overdue', 'Overdue')]
    )

    status = fields.Selection(
        string=u'Status', readonly=True, selection=[('Available', 'Available'),
                                                    ('Occupied', 'Occupied')]
    )

    start_date = fields.Datetime('Start Date', required=True)
    end_date = fields.Datetime('End Date', readonly=True, compute="get_end_dates")
    rental_price = fields.Float(
        string=u'Rental Price', related="product_id.list_price",
    )
    unit = fields.Float(
        string=u'Unit(s)', default=1, required=True
    )
    total_amount = fields.Float(
        string=u'Amount Charge', compute="get_duration_pick")
    day_count = fields.Float(
        string=u'Duration', required=True, default=1
    )
    balance = fields.Float(
        string=u'Balance', required=False, default=0
    )

    @api.one                 
    @api.depends('end_date','start_date','rental_period','rental_price','unit')
    def get_duration_pick(self):                
        for rec in self:
            if rec.rental_period:
                rec.total_amount = rec.day_count * rec.rental_price * rec.unit
        return True  
    
    @api.one                 
    @api.depends('start_date','day_count','rental_period')
    def get_end_dates(self):
        number = 0
        if self.start_date:
            if self.rental_period == "Weeks":
                number = self.day_count * 7
            if self.rental_period == "Years":
                number = self.day_count * 365
            if self.rental_period == "Months":
                number = self.day_count * 30
            if self.rental_period == "Days":
                number = self.day_count * 1
            required_date = datetime.strptime(self.start_date, '%Y-%m-%d %H:%M:%S')
            self.end_date = required_date + timedelta(days=number)
    
    @api.one
    def check_expiry_and_extend(self):
        if not self.extend:
            raise ValidationError(_('Please select Extend/Deallocate Options'))
        else:
            if self.end_date:
                """Compare the end date to todays day, if todays date is greater than end date
                it will check to see if the extend option is extended / Deallocate. 
                - If extend, user will start over to put entries, retaining the Occupied status
                - If deallocate, the record unlinks from the line and set the product available
                - If Overdue, the record checks todays date, and calculate the extra days depending
                  on the period selected and add the amount to pay to the balance """
                rental = self.env['rent.product.line'].search([('product_id', '=', self.product_id.id)])
                today = fields.Datetime.now()
                if self.end_date < today:
                    end_date = datetime.strptime(self.end_date, '%Y-%m-%d %H:%M:%S')
                    duration = today - end_date
                    days = duration.days
                    if self.extend == "Overdue":
                        if self.rental_period == "Weeks":
                            number = self.rental_price *  (days / 7)
                        if self.rental_period == "Years":
                            number = self.rental_price * (days / 365)
                        if self.rental_period == "Months":
                            number = self.rental_price * (days / 30)
                        if self.rental_period == "Days":
                            number = self.rental_price * days
                        self.balance = number
                    elif self.extend == "Extend":
                        self.start_date = today
                        if self.start_date:
                            if self.rental_period == "Weeks":
                                number = self.day_count * 7
                            if self.rental_period == "Years":
                                number = self.day_count * 365
                            if self.rental_period == "Months":
                                number = self.day_count * 30
                            if self.rental_period == "Days":
                                number = self.day_count * 1
                            required_date = datetime.strptime(today, '%Y-%m-%d %H:%M:%S')
                            self.end_date = required_date + timedelta(days=number)
                    elif self.extend == "Deallocate":
                        self.product_id.status = 'Available'
                        self.status == 'Available'
                                                
                    # raise ValidationError(_('Your subscription to  {} has expired'.format(self.product_id.name)))
                   

class Service_Product(models.Model):
    _name = "service.product.line"
    _rec_name = "code"

    @api.model
    def create(self, vals):
        sequence = self.env['ir.sequence'].next_by_code('service.product.line')
        vals['code'] = str(sequence)
        return super(Service_Product, self).create(vals)

    ref_id = fields.Many2one('estate.rental')
    code = fields.Char('Code')
    customer = fields.Many2one('res.partner', related="ref_id.customer", string ='Customer')    
    product_id = fields.Many2one('product.template', 
                                 string="Product", 
                                 required=True,
                                 domain="[('is_rent', '=', True), ('status', '=', 'Available')]")

    rental_period = fields.Selection(
        string=u'Rental period',required=True, default="Month",
        selection=[('Days', 'Days'), ('Weeks', 'Week'), ('Month', 'Month'), ('Years', 'Year')]
    )
     
    start_date = fields.Datetime('Start Date', required=True)
    end_date = fields.Datetime('End Date')#, compute="get_end_dates")
    rental_price = fields.Float(
        string=u'Rental Price', related="product_id.list_price",
    )
    unit = fields.Float(
        string=u'Unit(s)', default=1, required=False
    )
    total_amount = fields.Float(
        string=u'Amount Charge', compute="get_duration_pick")
    day_count = fields.Float(
        string=u'Duration', required=True, default=1
    )
    balance = fields.Float(
        string=u'Balance', required=False, default=0
    )

    @api.one                 
    @api.depends('end_date','start_date','rental_period','rental_price','unit')
    def get_duration_pick(self):                
        for rec in self:
            if rec.rental_period:
                rec.total_amount = rec.day_count * rec.rental_price * rec.unit
        return True  
    
    # # @api.one                 
    # @api.onchange('start_date')
    # def get_end_dates(self):
    #     pass
        #number = 0
        # if self.start_date:
        #     if self.rental_period == "Weeks":
        #         number = self.day_count * 7
        #     if self.rental_period == "Years":
        #         number = self.day_count * 365
        #     if self.rental_period == "Months":
        #         number = self.day_count * 30
        #     if self.rental_period == "Days":
        #         number = self.day_count * 1
        #     required_date = datetime.strptime(self.start_date, '%Y-%m-%d %H:%M:%S')
        #     self.end_date = required_date + timedelta(days=number)
    

class RentOutstanding(models.Model):
    _name = "rent.outstanding.record"
    _rec_name = "code"
 
    code = fields.Char('Reference', readonly=True)
    ref_id = fields.Many2one('service.product.line')  
    parent_ref_id = fields.Many2one('estate.rental')  
    customer = fields.Many2one('res.partner', string ='Customer')    
    product_id = fields.Many2one('product.template', 
                                 string="Product", 
                                 required=True,
                                 domain="[('is_rent', '=', True), ('status', '=', 'Available')]")
 
    last_paid_date = fields.Datetime('Start Date', required=True)
    expired_date = fields.Datetime('End Date',)
      
    amount_to_pay = fields.Float(
        string=u'Amount To Pay')
    rental_period = fields.Selection(
        string=u'Rental period',required=True, default="Month",
        selection=[('Days', 'Days'), ('Weeks', 'Week'), ('Month', 'Month'), ('Years', 'Year')]
    )
    invoice_id = fields.Many2one('account.invoice', string='Invoice', store=True)
    
    
    @api.multi
    def create_invoice(self):
        rental_service = self.env['estate.product.line'].search([('code', '=', self.code)])
        invoice_list = [] 
        invoice = 0 
        for partner in self:
            invoice = self.env['account.invoice'].create({
                'partner_id': partner.customer.id,
                'account_id': partner.customer.property_account_payable_id.id,
                'fiscal_position_id': partner.customer.property_account_position_id.id,
                'branch_id': self.env.user.branch_id.id or 1
            })
            invoice = invoice
        line_values = {}
        for line in self: 
            line_values = {
                'product_id': line.product_id.id,
                'price_unit': line.product_id.list_price or line.amount_to_pay,
                'invoice_id': invoice.id,
                'account_id': line.product_id.categ_id.property_account_income_categ_id.id,
                'name': 'Service Charge for ' + str(line.product_id.name),
                'quantity': line.ref_id.unit or 1
            }
            invoice.write({'invoice_line_ids': [(0, 0, line_values)]})
            invoice_list.append(invoice.id)
        parent_ref_id.invoice_id = invoice.id 
        self.invoice_id = invoice.id 
        find_id = self.env['account.invoice'].search([('id', '=', invoice.id)])
        find_id.action_invoice_open()
        return self.generate_receipt()
    
    @api.multi
    def generate_receipt(self):
        search_view_ref = self.env.ref(
            'account.view_account_invoice_filter', False)
        form_view_ref = self.env.ref('account.invoice_form', False)
        tree_view_ref = self.env.ref('account.invoice_tree', False)

        return {
            'domain': [('id', '=', self.invoice_id.id)],
            'name': 'Invoices',
            'res_model': 'account.invoice',
            'type': 'ir.actions.act_window',
            'views': [(tree_view_ref.id, 'tree'), (form_view_ref.id, 'form')],
            'search_view_id': search_view_ref and search_view_ref.id,
        }
        
    def add_to_line(self):
        rental_service = self.env['service.product.line'].search([('code', '=', self.code)])
        if rental_service:
            rental_service.write({'start_date':fields.Datetime.now(), 
                                  'product_id':self.product_id.id, 
                                  'rental_price':self.product_id.list_price,
                                  'rental_period': self.rental_period})
        else:
            raise ValidationError(_('There is no Existing reference code {} to Service lines'.format(self.code)))

           
class accountpayment(models.Model):
    _inherit = "account.payment"

    rent = fields.Boolean(
        string=u'Is Rental', default=False)
    bank = fields.Many2one('res.partner.bank', string="Bank")
    
    
    @api.multi
    def post(self):
        res = super(accountpayment, self).post()
        domain_inv = [('invoice_id', 'in', [item.id for item in self.invoice_ids])]
        rec = self.env['estate.rental'].search(domain_inv, limit=1)
        
        domain_outstanding_inv = [('invoice_id', 'in', [item.id for item in self.invoice_ids])]
        rec_out = self.env['rent.outstanding.record'].search(domain_outstanding_inv, limit=1)
        if rec:
            rec.write({'payment_ids': [(4, [self.id])], 'rent': True})
            rec.after_payment()
        if rec_out:
            rec_out.add_to_line()
        return res
