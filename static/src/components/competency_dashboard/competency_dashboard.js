/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class HcdiCompetencyDashboard extends Component {
    static template = "hcdi_training.CompetencyDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            data: {
                total_employees: 0,
                total_trainings: 0,
                passed_count: 0,
                pass_rate: 0,
                departments: [],
                recent_activities: [],
            }
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        this.state.loading = true;
        try {
            const result = await this.orm.call(
                "hcdi.training.history",
                "get_competency_dashboard_data",
                []
            );
            this.state.data = result;
        } catch (error) {
            console.error("Error loading HCDI dashboard data:", error);
        } finally {
            this.state.loading = false;
        }
    }

    openTrainingHistory() {
        this.action.doAction({
            name: "Riwayat & Penilaian Training",
            type: "ir.actions.act_window",
            res_model: "hcdi.training.history",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
        });
    }
}

registry.category("actions").add("hcdi_competency_dashboard", HcdiCompetencyDashboard);
