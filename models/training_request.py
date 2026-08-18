from odoo import models, fields, api, _
from odoo.exceptions import UserError

class HcdiTrainingRequest(models.Model):
    _name = 'hcdi.training.request'
    _description = 'Pengajuan Training / TNA Request (SPR0-01)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Training Request Title',
        required=True,
        tracking=True,
        placeholder='e.g. Data Analytics & Python Training Request'
    )
    manager_id = fields.Many2one(
        'res.users',
        string='Requesting Manager',
        default=lambda self: self.env.user,
        required=True,
        tracking=True
    )
    trainer_id = fields.Many2one(
        'res.users',
        string='Trainer',
        tracking=True,
        help='Trainer appointed by HR L&D after approval. This user will be set as Responsible on the eLearning Course.'
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        required=True,
        tracking=True
    )
    reason = fields.Text(
        string='Training Needs & Rationale (TNA)',
        required=True,
        help='Description of training needs or urgent project rationale'
    )
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Medium'),
        ('2', 'High / Urgent')
    ], string='Priority', default='1', tracking=True)

    estimated_date = fields.Date(
        string='Estimated Training Date'
    )
    target_participant_ids = fields.Many2many(
        'hr.employee.public',
        string='Training Participants'
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'hcdi_training_request_attachment_rel',
        'request_id',
        'attachment_id',
        string='File Attachment',
        help='Upload supporting documents or proof files'
    )

    # Integrasi dengan Modul Document Approval (Cybrosys)
    approval_team_id = fields.Many2one(
        'document.approval.team',
        string='Approval Team',
        help='Select HR Approval Team'
    )
    approval_id = fields.Many2one(
        'document.approval',
        string='Document Approval',
        readonly=True,
        copy=False
    )
    approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting', 'Waiting HR Approval'),
        ('approved', 'Approved'),
        ('reject', 'Rejected')
    ], string='Approval Status', related='approval_id.state', store=True, readonly=True, default='draft', tracking=True)

    # Relasi ke Course eLearning yang dihasilkan
    course_id = fields.Many2one(
        'slide.channel',
        string='eLearning Course',
        readonly=True,
        copy=False
    )

    # Proxy Fields & Actions untuk Integrasi Full Workflow Approval Cybrosys di HCDI Form
    show_approve = fields.Boolean(
        string='Bisa Approve/Reject',
        compute='_compute_show_approve'
    )
    approval_step_ids = fields.One2many(
        related='approval_id.step_ids',
        string='Tahapan Approval Cybrosys',
        readonly=True
    )

    @api.depends('approval_id', 'approval_id.show_approve', 'approval_id.state')
    def _compute_show_approve(self):
        """Mengecek apakah user yang sedang login adalah approver / team lead sah untuk dokumen approval Cybrosys ini."""
        for rec in self:
            if rec.approval_id and rec.approval_state == 'waiting':
                rec.approval_id._compute_show_approve()
                rec.show_approve = rec.approval_id.show_approve
            else:
                rec.show_approve = False

    def action_approve_request(self):
        """Memanggil wizard Setujui (Approve) bawaan Cybrosys document.approval."""
        self.ensure_one()
        if not self.approval_id:
            raise UserError(_("Dokumen approval belum dibuat!"))
        return self.approval_id.action_approve()

    def action_reject_request(self):
        """Memanggil wizard Tolak (Reject) bawaan Cybrosys document.approval."""
        self.ensure_one()
        if not self.approval_id:
            raise UserError(_("Dokumen approval belum dibuat!"))
        return self.approval_id.action_reject()

    def action_submit_for_approval(self):
        """Membuat record Document Approval Cybrosys dan mengirimkan pengajuan ke workflow approval."""
        for rec in self:
            if not rec.approval_team_id:
                raise UserError(_("Silakan pilih 'Tim Approval HR L&D' terlebih dahulu sebelum mengajukan!"))
            
            if not rec.approval_id:
                doc_approval = self.env['document.approval'].create({
                    'name': f"Pengajuan Training: {rec.name}",
                    'team_id': rec.approval_team_id.id,
                    'description': rec.reason,
                    'approve_initiator_id': rec.create_uid.id or self.env.uid,
                })
                rec.approval_id = doc_approval.id

                # Copy file attachment pendukung dari Pengajuan ke Dokumen Approval Cybrosys
                if rec.attachment_ids:
                    for att in rec.attachment_ids:
                        self.env['document.approval.file'].create({
                            'approval_id': doc_approval.id,
                            'name': att.name,
                            'file': att.datas,
                        })
            
            # Kirim dokumen approval ke status waiting
            rec.approval_id.action_send_for_approval()
            rec.message_post(body=_("Pengajuan training telah dikirim ke Tim Approval HR L&D."))

    def action_create_course(self):
        """Membuat Course pada modul eLearning oleh HR L&D.
        HANYA BISA DIKLIK JIKA STATUS APPROVAL = APPROVED.
        Memerlukan penunjukan trainer_id oleh HR L&D.
        """
        for rec in self:
            if rec.course_id:
                raise UserError(_("Course eLearning untuk pengajuan ini sudah pernah dibuat!"))

            if rec.approval_state != 'approved':
                raise UserError(_(
                    "GAGAL MEMBUAT COURSE!\n"
                    "Berdasarkan aturan bisnis, Course Training HANYA dapat dibuat jika status pengajuan sudah APPROVED oleh HR L&D.\n"
                    f"Status saat ini: {dict(rec._fields['approval_state'].selection).get(rec.approval_state or 'draft')}"
                ))

            if not rec.trainer_id:
                raise UserError(_("Silakan tentukan 'Trainer Pelatihan' terlebih dahulu sebelum membuat Course eLearning!"))

            # 1. Buat Course pada modul eLearning (slide.channel) dengan Trainer yang ditunjuk oleh HR
            new_course = self.env['slide.channel'].create({
                'name': rec.name,
                'description': rec.reason,
                'user_id': rec.trainer_id.id, # Otomatis menjadi "Responsible" di tampilan Course!
            })
            rec.course_id = new_course.id

            # 2. Otomatis mendaftarkan akun Partner seluruh Calon Peserta ke daftar Anggota Resmi Course eLearning (slide.channel.partner)
            # PENJELASAN KODE: Tanpa logika ini, Odoo akan mengunci materi & ujian dari peserta karena menganggap mereka "Belum Terdaftar (Not Enrolled)".
            # Dengan _action_add_members(), seluruh Calon Peserta otomatis bisa membuka & mengerjakan soal ujian di portal Odoo.
            # 2. Otomatis mendaftarkan partner karyawan sebagai anggota resmi Course eLearning agar bisa mengerjakan ujian di portal
            employees = self.env['hr.employee'].sudo().browse(rec.target_participant_ids.ids)
            participant_partners = employees.mapped(
                lambda emp: emp.work_contact_id or (emp.user_id and emp.user_id.partner_id)
            ).filtered(lambda p: p)
            if participant_partners:
                new_course._action_add_members(participant_partners)

            # 3. Otomatis mendaftarkan seluruh Calon Peserta ke Progres Training (hcdi.training.history) dengan status 'draft'
            history_obj = self.env['hcdi.training.history'].sudo()
            created_count = 0
            for participant in rec.target_participant_ids:
                existing = history_obj.search([
                    ('employee_id', '=', participant.id),
                    ('channel_id', '=', new_course.id)
                ], limit=1)
                if not existing:
                    history_obj.create({
                        'employee_id': participant.id,
                        'channel_id': new_course.id,
                        'execution_state': 'draft',
                    })
                    created_count += 1

            rec.message_post(body=_("Course eLearning '%s' berhasil dibuat dengan Trainer Responsible: %s. %d peserta otomatis terdaftar sebagai Anggota Course & Progres Training.") % (new_course.name, rec.trainer_id.name, created_count))

            return {
                'name': _('Course eLearning'),
                'type': 'ir.actions.act_window',
                'res_model': 'slide.channel',
                'res_id': new_course.id,
                'view_mode': 'form',
            }

