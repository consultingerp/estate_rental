# -*- coding: utf-8 -*-
{
    'name': 'Rental Application',
    'version': '1.0',
    'author': 'Maach Services',
    'description': """A rental application for odoo""",
    'summary': 'Run rental services for estates, shops, products etc ',
    'category': 'Base',
    # 'live_test_url': "https://www.youtube.com/watch?v=KEjxieAoGeA&feature=youtu.be",

    'depends': ['base', 'product', 'sale', 'analytic'], #'branch'
    'data': [
        'security/security_group.xml', 
        'sequence/sequence.xml',
        'views/rental_sales.xml',
        'data/product_data.xml',
        
    ],
    # 'qweb': [
    #     'static/src/xml/base.xml',
    # ],
    'price': 100.00,
    'currency': 'EUR',
    'installable': True,
    'auto_install': False,
}
