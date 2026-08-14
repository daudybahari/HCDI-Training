# -*- coding: utf-8 -*-
{
    'name': 'HCDI Pengelolaan Training',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Training',
    'summary': 'Aplikasi Pengelolaan Training & Monitoring Kompetensi PT HCDI',
    'description': """
Aplikasi Pengelolaan Training End-to-End untuk PT Human Capital Development Indonesia (HCDI).
Fitur Utama:
- Integrasi eLearning & Assessment (Survey)
- Integrasi Document Approval (Cybrosys) untuk Pengajuan Training (SPR0-01)
- Perhitungan Nilai Akhir Berbobot (Pre-test, Quiz, Post-test)
- Penerbitan Sertifikat Otomatis dengan Sequence Unik & Auto-Email
- Tab Training History pada Profil Karyawan (hr.employee)
    """,
    'author': 'Technical Developer - HCDI',
    'website': 'https://www.hcdindonesia.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'website_slides',
        'survey',
        'mail',
        'document_approval', # SPR0-01: Cybrosys Document Approval Module
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_template_data.xml',
        'reports/certificate_report_template.xml',
        'views/menu_views.xml',
        'views/dashboard_views.xml',          # Training Dashboard
        'views/training_request_views.xml',   # SPR0-01
        'views/slide_channel_views.xml',
        'views/training_history_views.xml',
        'views/hr_employee_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hcdi_training/static/src/dashboard/training_dashboard.scss',
            'hcdi_training/static/src/dashboard/training_dashboard.xml',
            'hcdi_training/static/src/dashboard/training_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
