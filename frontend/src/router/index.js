import { createRouter, createWebHistory } from 'vue-router'

import HubLayout from '../views/HubLayout.vue'
import OperationsView from '../views/OperationsView.vue'

import DashboardView from '../views/DashboardView.vue'

import APSView from '../views/APSView.vue'

import CompareView from '../views/CompareView.vue'

import AnalysisView from '../views/AnalysisView.vue'

import EnergyView from '../views/EnergyView.vue'

import DataCenterView from '../views/DataCenterView.vue'

import LogisticsView from '../views/LogisticsView.vue'

import StaffingView from '../views/StaffingView.vue'

import MaterialsView from '../views/MaterialsView.vue'

import HealthView from '../views/HealthView.vue'

import AgentChatView from '../views/AgentChatView.vue'

import AssemblyIntegrationView from '../views/AssemblyIntegrationView.vue'

import OutsourcedSupplyView from '../views/OutsourcedSupplyView.vue'

import KnowledgeRagView from '../views/KnowledgeRagView.vue'

import AssemblyEmbedView from '../views/AssemblyEmbedView.vue'

import SupplyChainEmbedView from '../views/SupplyChainEmbedView.vue'

import LogisticsVrpEmbedView from '../views/LogisticsVrpEmbedView.vue'

const productionChildRoutes = [
  { path: 'dashboard', component: DashboardView },
  { path: 'database', component: DataCenterView },
  { path: 'aps', component: APSView },
  { path: 'compare', component: CompareView },
  { path: 'assistant', component: AgentChatView },
  { path: 'reports', component: AnalysisView },
  { path: 'energy', component: EnergyView },
  { path: 'health', component: HealthView },
  { path: 'logistics', component: LogisticsView },
  { path: 'staffing', component: StaffingView },
  { path: 'materials', component: MaterialsView },
]

const legacyProductionRedirects = [
  'dashboard',
  'database',
  'aps',
  'compare',
  'assistant',
  'reports',
  'energy',
  'health',
  'logistics',
  'staffing',
  'materials',
].map((name) => ({
  path: `/${name}`,
  redirect: `/home/production/${name}`,
}))

function legacyModuleRedirect(prefix, fallback) {
  return {
    path: `/${prefix}/:tab?`,
    redirect: (to) => `/home/${prefix}/${to.params.tab || fallback}`,
  }
}

export default createRouter({
  history: createWebHistory('/new-ui'),
  routes: [
    { path: '/', redirect: '/home' },

    {
      path: '/home',
      component: HubLayout,
      children: [
        { path: 'operations-tools', component: OperationsView },
        { path: '', component: AssemblyIntegrationView },
        { path: 'outsourced-supply', component: OutsourcedSupplyView },
        { path: 'logistics-resource', redirect: '/home/logistics-resource/experiment' },
        { path: 'logistics-resource/:tab', component: LogisticsVrpEmbedView },
        { path: 'logistics-vrp', redirect: '/home/logistics-resource/experiment' },
        {
          path: 'logistics-vrp/:tab',
          redirect: (to) => `/home/logistics-resource/${to.params.tab}`,
        },
        { path: 'knowledge', component: KnowledgeRagView },
        { path: 'production', redirect: '/home/production/dashboard' },
        ...productionChildRoutes.map((r) => ({
          path: `production/${r.path}`,
          component: r.component,
        })),
        { path: 'supply-chain', redirect: '/home/supply-chain/dashboard' },
        { path: 'supply-chain/:tab', component: SupplyChainEmbedView },
        { path: 'assembly', redirect: '/home/assembly/dashboard' },
        { path: 'assembly/:tab', component: AssemblyEmbedView },
      ],
    },

    legacyModuleRedirect('assembly', 'dashboard'),
    legacyModuleRedirect('supply-chain', 'dashboard'),

    { path: '/assembly-integration', redirect: '/home' },

    ...legacyProductionRedirects,
  ],
})
